#!/usr/bin/env python3
"""bciciv-2a per-subject training + inference runner.

The BPB scorer's `evaluate_external.py` invokes this as an isolated child
process (one call per subject). It:

  1. Imports the agent-submitted `MIAgentModel` from an evaluator-controlled
     copy of `mi_agent_model.py`. The child process runs with -I / no user
     site-packages / no evaluator env vars, so the agent's model code cannot
     escape to read private labels or the label file path.
  2. Loads the T-session GDF for the given subject, does the frozen
     preprocessing (22 EEG channels, 4-38 Hz bandpass, cue-relative [0,4 s)
     epochs, resample to 128 Hz, scale to microvolts) → (288, 22, 512)
     features + (288,) labels from GDF annotations 769/770/771/772 mapped
     to 1..4.
  3. Splits the 288 trials by the manifest's fixed stratified 230/58
     train_trial_indices / val_trial_indices (seed=42).
  4. Trains a fresh `MIAgentModel()` with Adam lr=1e-3, batch 64, up to 100
     epochs, early stops on val loss (patience 20).
  5. Loads the E-session GDF for the same subject, produces (288, 22, 512)
     features, predicts, and writes CSV rows `sample_id,predicted_label_1to4`
     to `--out`.

Prediction labels are in 1..4 to match BCI Competition IV's `classlabel`
convention (LEFT=1, RIGHT=2, FEET=3, TONGUE=4); the parent scorer compares
against the private `A0xE.mat` `classlabel` field directly.
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

# Preprocessing constants — fixed by the task contract, must not be changed.
SFREQ_TARGET = 128.0
BAND_L = 4.0
BAND_H = 38.0
TMIN = 0.0
TMAX = 4.0
N_CH = 22
N_TIMES = int(round((TMAX - TMIN) * SFREQ_TARGET))  # 512
EXPECTED_TRIALS = 288
TRIAL_START_ANNOTATION = "768"
CLASS_ANNOTATIONS = {"769": 1, "770": 2, "771": 3, "772": 4}
UNKNOWN_ANNOTATION = "783"
CUE_OFFSET_S = 2.0
MICROVOLTS_PER_VOLT = 1e6

# Training hyperparameters — frozen so per-subject metrics are comparable.
LR = 1e-3
BATCH_SIZE = 64
MAX_EPOCHS = 100
EARLY_STOP_PATIENCE = 20
SEED = 42


def _resolve_cue_events(
    events: np.ndarray,
    ann_dict: dict[str, int],
    sfreq: float,
    source_name: str,
    expected_trials: int = EXPECTED_TRIALS,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Select MI cue events and labels, validating the Dataset 2a timeline."""
    present_class_annotations = set(CLASS_ANNOTATIONS).intersection(ann_dict)
    has_unknown_annotation = UNKNOWN_ANNOTATION in ann_dict

    if present_class_annotations and has_unknown_annotation:
        raise RuntimeError(f"{source_name}: contains both labeled and unknown cue annotations")

    if present_class_annotations:
        missing = set(CLASS_ANNOTATIONS).difference(ann_dict)
        if missing:
            raise RuntimeError(f"{source_name}: missing class cue annotations {sorted(missing)}")
        event_id_to_label = {
            ann_dict[annotation]: label
            for annotation, label in CLASS_ANNOTATIONS.items()
        }
        cue_ids = np.asarray(list(event_id_to_label), dtype=events.dtype)
        cue_events = events[np.isin(events[:, 2], cue_ids)]
        labels = np.asarray(
            [event_id_to_label[int(event_id)] for event_id in cue_events[:, 2]],
            dtype=np.int64,
        )
        counts = np.bincount(labels, minlength=5)[1:]
        if expected_trials % 4 != 0:
            raise RuntimeError(f"{source_name}: expected trial count must be divisible by 4")
        if not np.array_equal(counts, np.full(4, expected_trials // 4)):
            raise RuntimeError(f"{source_name}: unexpected class counts {counts.tolist()}")
    elif has_unknown_annotation:
        cue_id = ann_dict[UNKNOWN_ANNOTATION]
        cue_events = events[events[:, 2] == cue_id]
        labels = None
    else:
        expected = sorted([*CLASS_ANNOTATIONS, UNKNOWN_ANNOTATION])
        raise RuntimeError(f"{source_name}: no MI cue annotation; expected one of {expected}")

    if len(cue_events) != expected_trials:
        raise RuntimeError(
            f"{source_name}: found {len(cue_events)} MI cues, expected {expected_trials}"
        )

    if TRIAL_START_ANNOTATION not in ann_dict:
        raise RuntimeError(f"{source_name}: no '{TRIAL_START_ANNOTATION}' trial-start annotation")
    trial_start_id = ann_dict[TRIAL_START_ANNOTATION]
    trial_starts = events[events[:, 2] == trial_start_id]
    if len(trial_starts) != len(cue_events):
        raise RuntimeError(
            f"{source_name}: found {len(trial_starts)} trial starts for {len(cue_events)} MI cues"
        )

    offsets = cue_events[:, 0] - trial_starts[:, 0]
    expected_offset = CUE_OFFSET_S * sfreq
    if not np.all(np.abs(offsets - expected_offset) <= 1.0):
        unique_offsets = np.unique(offsets).tolist()
        raise RuntimeError(
            f"{source_name}: MI cues are not {CUE_OFFSET_S:g} s after trial starts; "
            f"sample offsets={unique_offsets} at sfreq={sfreq:g}"
        )

    return cue_events, labels


def _to_microvolts(data: np.ndarray) -> np.ndarray:
    """Convert MNE's SI-unit EEG arrays to MOABB's microvolt array contract."""
    return (np.asarray(data) * MICROVOLTS_PER_VOLT).astype(np.float32)


def preprocess_raw(
    raw: mne.io.BaseRaw,
    source_name: str,
    expected_trials: int = EXPECTED_TRIALS,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Apply the production preprocessing contract to an already-loaded recording.

    The injectable Raw boundary lets CI use a small deterministic synthetic EEG
    fixture while production still enters through MNE's GDF reader.
    """
    raw = raw.copy().load_data(verbose="ERROR")
    eeg_names = [c for c in raw.ch_names if c.startswith("EEG-")]
    if len(eeg_names) < N_CH:
        raise RuntimeError(f"{source_name}: expected >= {N_CH} EEG-* channels, got {len(eeg_names)}")
    raw.pick(eeg_names[:N_CH])
    raw.filter(BAND_L, BAND_H, verbose="ERROR")

    events, ann_dict = mne.events_from_annotations(raw, verbose="ERROR")
    ann_dict = {str(k): int(v) for k, v in ann_dict.items()}
    native_sfreq = float(raw.info["sfreq"])
    cue_events, labels = _resolve_cue_events(
        events, ann_dict, native_sfreq, source_name, expected_trials
    )

    # MNE includes tmax. Exclude one native sample before epoch resampling to
    # define the benchmark's explicit cue-relative half-open interval [0, 4 s).
    native_tmax = TMAX - 1.0 / native_sfreq
    cue_ids = sorted(set(int(event_id) for event_id in cue_events[:, 2]))
    epochs = mne.Epochs(
        raw, cue_events, event_id=cue_ids,
        tmin=TMIN, tmax=native_tmax,
        baseline=None, preload=True, verbose="ERROR", proj=False,
    )
    epochs.resample(SFREQ_TARGET, verbose="ERROR")
    X = _to_microvolts(epochs.get_data())
    expected_shape = (expected_trials, N_CH, N_TIMES)
    if X.shape != expected_shape:
        raise RuntimeError(f"{source_name}: bad epoch shape {X.shape}, expected {expected_shape}")
    return X, labels


def load_epochs(gdf_path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """Return cue-relative microvolt epochs and labels for one Dataset 2a session."""
    raw = mne.io.read_raw_gdf(str(gdf_path), preload=True, verbose="ERROR")
    return preprocess_raw(raw, gdf_path.name)


def load_agent_module(model_source: Path):
    if not model_source.exists():
        raise RuntimeError(f"agent model file missing: {model_source}")
    spec = importlib.util.spec_from_file_location("mi_agent_model", str(model_source))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "MIAgentModel"):
        raise RuntimeError("submitted mi_agent_model.py does not define class MIAgentModel")
    return module


def train_one_subject(
    model_source: Path,
    train_gdf: Path,
    test_gdf: Path,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    device: torch.device,
) -> np.ndarray:
    """Train fresh MIAgentModel, return (288,) predictions in 1..4 for E session."""
    X_train_all, y_train_all = load_epochs(train_gdf)  # (288, 22, 512), (288,) labels 1..4
    if y_train_all is None:
        raise RuntimeError(f"{train_gdf.name}: T-session GDF must contain class annotations")
    X_test, _ = load_epochs(test_gdf)  # E session, labels hidden — parent scorer holds them

    return train_from_arrays(
        model_source=model_source,
        X_train_all=X_train_all,
        y_train_all=y_train_all,
        X_test=X_test,
        train_idx=train_idx,
        val_idx=val_idx,
        device=device,
    )


def train_from_arrays(
    model_source: Path,
    X_train_all: np.ndarray,
    y_train_all: np.ndarray,
    X_test: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    device: torch.device,
    *,
    max_epochs: int = MAX_EPOCHS,
    batch_size: int = BATCH_SIZE,
    seed: int = SEED,
) -> np.ndarray:
    """Shared model-import/training/inference path used by production and CI smoke tests."""
    agent_module = load_agent_module(model_source)
    trial_count = len(X_train_all)
    if X_train_all.shape[1:] != (N_CH, N_TIMES) or X_test.shape[1:] != (N_CH, N_TIMES):
        raise RuntimeError("BCI arrays do not match the (N, 22, 512) model contract")
    if y_train_all.shape != (trial_count,):
        raise RuntimeError(f"training labels have shape {y_train_all.shape}, expected ({trial_count},)")

    # Sanity: split indices must cover all training trials without overlap.
    train_set = set(train_idx.tolist())
    val_set = set(val_idx.tolist())
    if not train_set.isdisjoint(val_set):
        raise RuntimeError("train/val indices overlap")
    if train_set | val_set != set(range(trial_count)):
        raise RuntimeError(f"train + val indices must cover {trial_count} T-session trials")

    Xtr = torch.tensor(X_train_all[train_idx], dtype=torch.float32)
    ytr = torch.tensor(y_train_all[train_idx] - 1, dtype=torch.long)  # 1..4 → 0..3
    Xva = torch.tensor(X_train_all[val_idx], dtype=torch.float32)
    yva = torch.tensor(y_train_all[val_idx] - 1, dtype=torch.long)
    Xte = torch.tensor(X_test, dtype=torch.float32)

    torch.manual_seed(seed)
    np.random.seed(seed)

    model = agent_module.MIAgentModel().to(device)
    # Contract sanity: 2-sample dummy pass must give (2, 4)
    with torch.no_grad():
        dummy = torch.randn(2, N_CH, N_TIMES, device=device)
        out = model(dummy)
    if tuple(out.shape) != (2, 4):
        raise RuntimeError(f"MIAgentModel forward output shape is {tuple(out.shape)}, expected (2, 4)")

    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss()

    train_ds = torch.utils.data.TensorDataset(Xtr, ytr)
    loader = torch.utils.data.DataLoader(
        train_ds, batch_size=batch_size, shuffle=True,
        generator=torch.Generator().manual_seed(seed),
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
        with torch.no_grad():
            val_logits = model(Xva.to(device))
            val_loss = float(criterion(val_logits, yva.to(device)).item())

        if val_loss < best_val_loss - 1e-4:
            best_val_loss = val_loss
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= EARLY_STOP_PATIENCE:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    # Inference on E session — batched to fit in GPU memory
    preds = []
    with torch.no_grad():
        for i in range(0, len(Xte), batch_size):
            batch = Xte[i:i + batch_size].to(device)
            logits = model(batch)
            preds.append(torch.argmax(logits, dim=1).cpu().numpy())
    return (np.concatenate(preds) + 1).astype(np.int64)  # back to 1..4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-source", required=True, help="path to submitted mi_agent_model.py")
    ap.add_argument("--subject-id", type=int, required=True)
    ap.add_argument("--train-gdf", required=True, help="A0xT.gdf")
    ap.add_argument("--test-gdf", required=True, help="A0xE.gdf")
    ap.add_argument("--train-idx", required=True,
                    help="comma-separated int indices for the 230 stratified train trials in T session")
    ap.add_argument("--val-idx", required=True,
                    help="comma-separated int indices for the 58 stratified val trials in T session")
    ap.add_argument("--out", required=True, help="output CSV path (sample_id,predicted_label)")
    args = ap.parse_args()

    # Sanity: the child process must not carry evaluator secrets or paths.
    for forbidden in ("BPB_BCI2A_PRIVATE_EVAL_DIR", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        if os.environ.get(forbidden):
            print(f"child process received forbidden env var: {forbidden}", file=sys.stderr)
            return 2

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_idx = np.asarray([int(x) for x in args.train_idx.split(",")], dtype=np.int64)
    val_idx = np.asarray([int(x) for x in args.val_idx.split(",")], dtype=np.int64)

    preds = train_one_subject(
        model_source=Path(args.model_source),
        train_gdf=Path(args.train_gdf),
        test_gdf=Path(args.test_gdf),
        train_idx=train_idx,
        val_idx=val_idx,
        device=device,
    )
    if preds.shape != (288,):
        print(f"predictions have shape {preds.shape}, expected (288,)", file=sys.stderr)
        return 3

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "predicted_label"])
        for i, p in enumerate(preds):
            w.writerow([i, int(p)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
