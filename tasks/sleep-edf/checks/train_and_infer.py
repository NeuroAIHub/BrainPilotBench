#!/usr/bin/env python3
"""sleep-edf training + inference runner.

The BPB scorer's `evaluate_external.py` invokes this as an isolated child
process. It:

  1. Imports the agent-submitted `SleepAgentModel` from an evaluator-controlled
     copy of `sleep_agent_model.py`. The child runs with -I / no user
     site-packages / no evaluator env vars, so the agent's model code cannot
     escape to read the private hypnogram directory or its path.
  2. For every subject in --train-subjects and --val-subjects, loads both
     PSG + Hypnogram recordings, does the frozen preprocessing (pick
     `EEG Fpz-Cz`, 0.3-35 Hz bandpass, resample to 100 Hz, crop head/tail
     Wake to 30 min each, cut into non-overlapping 30 s epochs, scale
     MNE volts to microvolts) → per-epoch features (1, 3000) plus labels
     0..4 from the hypnogram annotations.
  3. Concatenates train epochs across subjects 0-13 → one big pool with a
     class-weighted CrossEntropyLoss. Trains a fresh SleepAgentModel with
     Adam lr=1e-3, batch 64, up to 20 epochs, early-stops on val loss
     (patience 5). Val is subjects 14-15.
  4. For each subject in --test-subjects, loads recordings, predicts,
     writes `subject_id,epoch_id,predicted_label` rows to --out.

Prediction labels are 0..4 (Wake / N1 / N2 / N3 / REM). The parent
scorer compares against the private hypnogram labels loaded from the
same test EDF files directly (annotations are inside the Hypnogram
EDF, not a separate .mat file — unlike bciciv-2a).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import mne
import torch
import torch.nn as nn

warnings.filterwarnings("ignore")
mne.set_log_level("ERROR")

# Preprocessing constants — fixed by the task contract.
SFREQ_TARGET = 100.0
BAND_L = 0.3
BAND_H = 35.0
WINDOW_S = 30.0
N_TIMES = int(round(WINDOW_S * SFREQ_TARGET))  # 3000
EEG_CHANNEL = "EEG Fpz-Cz"
CROP_WAKE_MINS = 30
MICROVOLTS_PER_VOLT = 1e6

# Hypnogram annotation → BPB label mapping.
LABEL_MAPPING = {
    "Sleep stage W": 0,
    "Sleep stage 1": 1,
    "Sleep stage 2": 2,
    "Sleep stage 3": 3,
    "Sleep stage 4": 3,   # stage 4 merged into N3
    "Sleep stage R": 4,
}
N_CLASSES = 5

# Training hyperparameters — frozen so runs are comparable.
LR = 1e-3
BATCH_SIZE = 64
MAX_EPOCHS = 20
EARLY_STOP_PATIENCE = 5
SEED = 42


def _to_microvolts(data: np.ndarray) -> np.ndarray:
    """Convert MNE's SI-unit EEG arrays to microvolts (the sleep-staging
    community convention — MOABB/braindecode expose µV-scale arrays)."""
    return (np.asarray(data) * MICROVOLTS_PER_VOLT).astype(np.float32)


def preprocess_recording(
    raw: mne.io.BaseRaw,
    annotations: mne.Annotations,
    source_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the production preprocessing contract to an already-loaded recording.

    The injectable Raw/Annotations boundary lets CI use a compact deterministic
    fixture while production still enters through MNE's EDF readers.
    """
    raw = raw.copy()
    if EEG_CHANNEL not in raw.ch_names:
        raise RuntimeError(f"{source_name}: expected channel '{EEG_CHANNEL}', got {raw.ch_names}")
    raw.pick([EEG_CHANNEL])
    raw.load_data(verbose="ERROR")
    raw.filter(BAND_L, BAND_H, verbose="ERROR")
    raw.resample(SFREQ_TARGET, verbose="ERROR")

    raw.set_annotations(annotations)

    # Head/tail Wake crop: keep at most 30 min of Wake at each end.
    # Following the SleepPhysionet convention: find the first and last
    # non-Wake annotation, extend by CROP_WAKE_MINS minutes on each side.
    non_wake = [(o, d) for o, d, desc in zip(annotations.onset, annotations.duration, annotations.description)
                if desc in LABEL_MAPPING and LABEL_MAPPING[desc] != 0]
    if non_wake:
        first_nw = min(o for o, _ in non_wake)
        last_nw = max(o + d for o, d in non_wake)
        crop_min = max(0.0, first_nw - CROP_WAKE_MINS * 60.0)
        crop_max = min(raw.times[-1], last_nw + CROP_WAKE_MINS * 60.0)
        if crop_max > crop_min:
            raw.crop(tmin=crop_min, tmax=crop_max, verbose="ERROR")

    # Refresh annotations after crop (mne re-anchors onsets)
    events, ann_dict = mne.events_from_annotations(raw, chunk_duration=WINDOW_S, verbose="ERROR")
    ann_dict = {str(k): int(v) for k, v in ann_dict.items()}
    # event_id restricted to the six known Sleep stage strings; drops "?" and "Movement time"
    event_id = {k: ann_dict[k] for k in LABEL_MAPPING if k in ann_dict}
    if not event_id:
        raise RuntimeError(f"{source_name}: no recognized sleep-stage annotations in {list(ann_dict)}")

    epochs = mne.Epochs(
        raw, events, event_id=event_id,
        tmin=0.0, tmax=WINDOW_S - 1.0 / SFREQ_TARGET,
        baseline=None, preload=True, proj=False, verbose="ERROR",
    )
    X = _to_microvolts(epochs.get_data())
    # inv: event_id integer → BPB label
    id_to_desc = {v: k for k, v in event_id.items()}
    y = np.asarray(
        [LABEL_MAPPING[id_to_desc[int(e)]] for e in epochs.events[:, 2]],
        dtype=np.int64,
    )
    if X.shape[0] == 0:
        raise RuntimeError(f"{source_name}: no valid 30 s epochs after crop")
    if X.shape[1:] != (1, N_TIMES):
        raise RuntimeError(f"{source_name}: bad epoch shape {X.shape}, expected (N, 1, {N_TIMES})")
    return X, y


def load_subject_recording(psg_path: Path, hyp_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (X: (N,1,3000), y: (N,) labels 0..4) for one PSG + Hypnogram pair.

    Applies: single-channel pick, 0.3-35 Hz filter, resample to 100 Hz,
    head/tail Wake crop (30 min each), 30 s non-overlapping epoching,
    label mapping, V→µV scaling. `Movement time` / `Sleep stage ?` epochs
    are dropped.
    """
    if not psg_path.exists():
        raise RuntimeError(f"missing PSG file: {psg_path}")
    if not hyp_path.exists():
        raise RuntimeError(f"missing hypnogram file: {hyp_path}")

    raw = mne.io.read_raw_edf(str(psg_path), preload=False, verbose="ERROR")
    annotations = mne.read_annotations(str(hyp_path))
    return preprocess_recording(raw, annotations, psg_path.name)


def load_subjects(subject_ids: list[int], manifest: dict, edf_root: Path) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate all epochs across a list of subject ids (both recordings each)."""
    Xs, ys = [], []
    for sid in subject_ids:
        entry = manifest.get(str(sid))
        if entry is None:
            raise RuntimeError(f"manifest missing subject {sid}")
        for rec in entry["recordings"].values():
            X, y = load_subject_recording(
                psg_path=edf_root / rec["psg"],
                hyp_path=edf_root / rec["hypnogram"],
            )
            Xs.append(X)
            ys.append(y)
    return np.concatenate(Xs, axis=0), np.concatenate(ys, axis=0)


def load_agent_module(model_source: Path):
    if not model_source.exists():
        raise RuntimeError(f"agent model file missing: {model_source}")
    spec = importlib.util.spec_from_file_location("sleep_agent_model", str(model_source))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "SleepAgentModel"):
        raise RuntimeError("submitted sleep_agent_model.py does not define class SleepAgentModel")
    return module


def compute_class_weights(y: np.ndarray) -> torch.Tensor:
    """Inverse-frequency class weights, normalized to mean=1 for stability."""
    counts = np.bincount(y, minlength=N_CLASSES).astype(np.float64)
    # Guard against zero-count classes: floor at 1 to avoid /0.
    counts = np.maximum(counts, 1.0)
    inv = counts.sum() / counts
    inv = inv * N_CLASSES / inv.sum()  # normalize to mean = 1
    return torch.tensor(inv, dtype=torch.float32)


def load_manifest(manifest_dir: Path) -> dict:
    p = manifest_dir / "subjects.json"
    if not p.exists():
        raise RuntimeError(f"missing manifests/subjects.json under {manifest_dir}")
    import json
    return json.loads(p.read_text(encoding="utf-8"))


def fit_model_from_arrays(
    model_source: Path,
    Xtr: np.ndarray,
    ytr: np.ndarray,
    Xva: np.ndarray,
    yva: np.ndarray,
    device: torch.device,
    *,
    max_epochs: int = MAX_EPOCHS,
    batch_size: int = BATCH_SIZE,
    seed: int = SEED,
) -> nn.Module:
    """Shared model-import/training path used by production and CI smoke tests."""
    if Xtr.shape[1:] != (1, N_TIMES) or Xva.shape[1:] != (1, N_TIMES):
        raise RuntimeError("Sleep arrays do not match the (N, 1, 3000) model contract")
    if ytr.shape != (len(Xtr),) or yva.shape != (len(Xva),):
        raise RuntimeError("Sleep labels do not align with their feature arrays")

    agent_module = load_agent_module(model_source)
    torch.manual_seed(seed)
    np.random.seed(seed)

    Xtr_t = torch.tensor(Xtr, dtype=torch.float32)
    ytr_t = torch.tensor(ytr, dtype=torch.long)
    Xva_t = torch.tensor(Xva, dtype=torch.float32)
    yva_t = torch.tensor(yva, dtype=torch.long)

    class_weights = compute_class_weights(ytr).to(device)
    print(f"  class weights (Wake,N1,N2,N3,REM): "
          f"{['%.3f' % w for w in class_weights.detach().cpu().tolist()]}",
          file=sys.stderr, flush=True)

    model = agent_module.SleepAgentModel().to(device)
    with torch.no_grad():
        dummy = torch.randn(2, 1, N_TIMES, device=device)
        out = model(dummy)
    if tuple(out.shape) != (2, N_CLASSES):
        raise RuntimeError(f"SleepAgentModel forward output shape is {tuple(out.shape)}, expected (2, {N_CLASSES})")

    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(Xtr_t, ytr_t),
        batch_size=batch_size, shuffle=True,
        generator=torch.Generator().manual_seed(seed),
        num_workers=0, pin_memory=(device.type == "cuda"),
    )

    best_val_loss = float("inf")
    best_state = None
    stale = 0
    for epoch in range(max_epochs):
        model.train()
        for xb, yb in loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()

        model.eval()
        val_loss_num = 0.0
        val_count = 0
        with torch.no_grad():
            for i in range(0, len(Xva_t), batch_size):
                bx = Xva_t[i:i + batch_size].to(device)
                by = yva_t[i:i + batch_size].to(device)
                logits = model(bx)
                loss = criterion(logits, by)
                val_loss_num += float(loss.item()) * bx.shape[0]
                val_count += bx.shape[0]
        val_loss = val_loss_num / max(val_count, 1)
        print(f"  epoch {epoch+1:3d}: val_loss={val_loss:.4f}", file=sys.stderr, flush=True)

        if val_loss < best_val_loss - 1e-4:
            best_val_loss = val_loss
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= EARLY_STOP_PATIENCE:
                print(f"  early stop at epoch {epoch+1}", file=sys.stderr, flush=True)
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model


def predict_array(
    model: nn.Module,
    X: np.ndarray,
    device: torch.device,
    *,
    batch_size: int = BATCH_SIZE,
) -> np.ndarray:
    """Run the production batched inference path on one preprocessed recording."""
    if X.shape[1:] != (1, N_TIMES):
        raise RuntimeError("Sleep inference array does not match the (N, 1, 3000) model contract")
    X_t = torch.tensor(X, dtype=torch.float32)
    preds_list = []
    with torch.no_grad():
        for i in range(0, len(X_t), batch_size):
            logits = model(X_t[i:i + batch_size].to(device))
            preds_list.append(torch.argmax(logits, dim=1).cpu().numpy())
    return np.concatenate(preds_list)


def train_and_predict(
    model_source: Path,
    train_subjects: list[int],
    val_subjects: list[int],
    test_subjects: list[int],
    train_edf_root: Path,
    test_edf_root: Path,
    manifest: dict,
    device: torch.device,
) -> list[tuple[int, int, int]]:
    """Return list of (subject_id, epoch_id, predicted_label) rows for the test set."""
    print(f"sleep-edf: loading train subjects {train_subjects}", file=sys.stderr, flush=True)
    Xtr, ytr = load_subjects(train_subjects, manifest, train_edf_root)
    print(f"  train pool: X.shape={Xtr.shape}, class counts={np.bincount(ytr, minlength=N_CLASSES).tolist()}",
          file=sys.stderr, flush=True)

    print(f"sleep-edf: loading val subjects {val_subjects}", file=sys.stderr, flush=True)
    Xva, yva = load_subjects(val_subjects, manifest, train_edf_root)
    print(f"  val pool: X.shape={Xva.shape}", file=sys.stderr, flush=True)
    model = fit_model_from_arrays(model_source, Xtr, ytr, Xva, yva, device)

    # Inference on test subjects — process one subject at a time to keep memory bounded.
    rows: list[tuple[int, int, int]] = []
    for sid in test_subjects:
        print(f"sleep-edf: inferring on test subject {sid}", file=sys.stderr, flush=True)
        entry = manifest.get(str(sid))
        if entry is None:
            raise RuntimeError(f"manifest missing test subject {sid}")
        epoch_offset = 0
        for rec in entry["recordings"].values():
            X, _ = load_subject_recording(
                psg_path=test_edf_root / rec["psg"],
                hyp_path=test_edf_root / rec["hypnogram"],
            )
            preds = predict_array(model, X, device)
            for j, p in enumerate(preds):
                rows.append((sid, epoch_offset + j, int(p)))
            epoch_offset += len(preds)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-source", required=True, help="path to submitted sleep_agent_model.py")
    ap.add_argument("--train-subjects", required=True, help="comma-separated int subject ids (default: 0..13)")
    ap.add_argument("--val-subjects", required=True, help="comma-separated int subject ids (default: 14,15)")
    ap.add_argument("--test-subjects", required=True, help="comma-separated int subject ids (default: 16..19)")
    ap.add_argument("--train-edf-root", required=True, help="dir containing subject 0-15 PSG + Hypnogram EDF")
    ap.add_argument("--test-edf-root", required=True, help="dir containing subject 16-19 PSG + Hypnogram EDF")
    ap.add_argument("--manifest-dir", required=True, help="dir containing subjects.json (subject → filenames)")
    ap.add_argument("--out", required=True, help="output CSV: subject_id,epoch_id,predicted_label")
    args = ap.parse_args()

    # Sanity: the child process must not carry evaluator secrets or paths.
    for forbidden in ("BPB_SLEEP_EDF_PRIVATE_EVAL_DIR", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        if os.environ.get(forbidden):
            print(f"child process received forbidden env var: {forbidden}", file=sys.stderr)
            return 2

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    manifest = load_manifest(Path(args.manifest_dir))
    train_subjects = [int(x) for x in args.train_subjects.split(",")]
    val_subjects = [int(x) for x in args.val_subjects.split(",")]
    test_subjects = [int(x) for x in args.test_subjects.split(",")]

    rows = train_and_predict(
        model_source=Path(args.model_source),
        train_subjects=train_subjects,
        val_subjects=val_subjects,
        test_subjects=test_subjects,
        train_edf_root=Path(args.train_edf_root),
        test_edf_root=Path(args.test_edf_root),
        manifest=manifest,
        device=device,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject_id", "epoch_id", "predicted_label"])
        for sid, eid, p in rows:
            w.writerow([sid, eid, p])
    print(f"sleep-edf: wrote {len(rows)} predictions to {out_path}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
