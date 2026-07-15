#!/usr/bin/env python3
"""bciciv-2a per-subject training + inference runner.

The BPB scorer's `evaluate_external.py` invokes this as an isolated child
process (one call per subject). It:

  1. Imports the agent-submitted `MIAgentModel` from an evaluator-controlled
     copy of `mi_agent_model.py`. The child process runs with -I / no user
     site-packages / no evaluator env vars, so the agent's model code cannot
     escape to read private labels or the label file path.
  2. Loads the T-session GDF for the given subject, does the frozen
     preprocessing (22 EEG channels, 4-38 Hz bandpass, resample to 128 Hz,
     0-4 s window per 768 cue) → (288, 22, 512) features + (288,) labels
     from GDF annotations 769/770/771/772 mapped to 1..4.
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
CUE_ANNOTATION = "768"                              # trial-start marker
CLASS_ANNOTATIONS = {"769": 1, "770": 2, "771": 3, "772": 4}
UNKNOWN_ANNOTATION = "783"                          # E-session cue (label hidden)

# Training hyperparameters — frozen so per-subject metrics are comparable.
LR = 1e-3
BATCH_SIZE = 64
MAX_EPOCHS = 100
EARLY_STOP_PATIENCE = 20
SEED = 42


def load_epochs(gdf_path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """Return (X: (288,22,512), y: (288,) with labels 1..4 or None for E session)."""
    raw = mne.io.read_raw_gdf(str(gdf_path), preload=True, verbose="ERROR")
    eeg_names = [c for c in raw.ch_names if c.startswith("EEG-")]
    if len(eeg_names) < N_CH:
        raise RuntimeError(f"{gdf_path.name}: expected >= {N_CH} EEG-* channels, got {len(eeg_names)}")
    raw.pick(eeg_names[:N_CH])
    raw.filter(BAND_L, BAND_H, verbose="ERROR")
    raw.resample(SFREQ_TARGET, verbose="ERROR")

    events, ann_dict = mne.events_from_annotations(raw, verbose="ERROR")
    ann_dict = {str(k): int(v) for k, v in ann_dict.items()}

    if CUE_ANNOTATION not in ann_dict:
        raise RuntimeError(f"{gdf_path.name}: no '{CUE_ANNOTATION}' cue annotation")
    cue_id = ann_dict[CUE_ANNOTATION]
    cue_events = events[events[:, 2] == cue_id]

    # tmax uses inclusive/exclusive quirk in MNE: to get exactly N_TIMES samples,
    # pass tmax = TMAX - 1/sfreq so mne's ceil-based length gives 512.
    epochs = mne.Epochs(
        raw, cue_events, event_id=cue_id,
        tmin=TMIN, tmax=TMAX - 1.0 / SFREQ_TARGET,
        baseline=None, preload=True, verbose="ERROR", proj=False,
    )
    X = epochs.get_data().astype(np.float32)
    if X.shape != (288, N_CH, N_TIMES):
        raise RuntimeError(f"{gdf_path.name}: bad epoch shape {X.shape}, expected (288, {N_CH}, {N_TIMES})")

    # Labels from GDF: T-session encodes class via annotations 769-772 near
    # each cue; E-session uses 783 (unknown), so we must fall back to the
    # .mat file (handled by the caller with --label-mat).
    has_class_ann = any(k in ann_dict for k in CLASS_ANNOTATIONS)
    if not has_class_ann:
        return X, None

    class_ann_ids = {ann_dict[k]: v for k, v in CLASS_ANNOTATIONS.items() if k in ann_dict}
    # For each cue sample, find the next class annotation within a 4-second window.
    labels = np.full(len(cue_events), -1, dtype=np.int64)
    for i, cue_sample in enumerate(cue_events[:, 0]):
        window_lo = cue_sample
        window_hi = cue_sample + int(round(4.0 * raw.info["sfreq"]))
        mask = (events[:, 0] >= window_lo) & (events[:, 0] <= window_hi) & \
               np.isin(events[:, 2], list(class_ann_ids.keys()))
        matches = events[mask]
        if len(matches):
            labels[i] = class_ann_ids[matches[0, 2]]

    if (labels == -1).any():
        raise RuntimeError(f"{gdf_path.name}: could not resolve labels for {int((labels==-1).sum())} trials")
    return X, labels


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
    agent_module = load_agent_module(model_source)

    X_train_all, y_train_all = load_epochs(train_gdf)  # (288, 22, 512), (288,) labels 1..4
    if y_train_all is None:
        raise RuntimeError(f"{train_gdf.name}: T-session GDF must contain class annotations")
    X_test, _ = load_epochs(test_gdf)  # E session, labels hidden — parent scorer holds them

    # Sanity: split indices must cover all 288 trials without overlap
    train_set = set(train_idx.tolist())
    val_set = set(val_idx.tolist())
    if not train_set.isdisjoint(val_set):
        raise RuntimeError("train/val indices overlap")
    if train_set | val_set != set(range(288)):
        raise RuntimeError("train + val indices must cover 288 T-session trials")

    Xtr = torch.tensor(X_train_all[train_idx], dtype=torch.float32)
    ytr = torch.tensor(y_train_all[train_idx] - 1, dtype=torch.long)  # 1..4 → 0..3
    Xva = torch.tensor(X_train_all[val_idx], dtype=torch.float32)
    yva = torch.tensor(y_train_all[val_idx] - 1, dtype=torch.long)
    Xte = torch.tensor(X_test, dtype=torch.float32)

    torch.manual_seed(SEED)
    np.random.seed(SEED)

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
        train_ds, batch_size=BATCH_SIZE, shuffle=True,
        generator=torch.Generator().manual_seed(SEED),
    )

    best_val_loss = float("inf")
    best_state = None
    stale = 0
    for epoch in range(MAX_EPOCHS):
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
        for i in range(0, len(Xte), BATCH_SIZE):
            batch = Xte[i:i + BATCH_SIZE].to(device)
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
