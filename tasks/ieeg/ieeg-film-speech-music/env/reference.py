#!/usr/bin/env python3
"""Fit a small real-data baseline on train and report validation only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.signal import welch
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


BANDS = ((1, 4), (4, 8), (8, 13), (13, 30), (30, 80), (80, 120))


def features(x: np.ndarray, sample_hz: int) -> np.ndarray:
    frequencies, power = welch(x, fs=sample_hz, nperseg=sample_hz, axis=-1)
    columns = []
    for lower, upper in BANDS:
        within = (frequencies >= lower) & (frequencies < upper)
        band = np.log10(np.mean(power[:, :, within], axis=-1) + 1e-20)
        columns.extend((np.median(band, axis=1), np.quantile(band, 0.75, axis=1)))
    return np.column_stack(columns)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    args = parser.parse_args()
    public = args.prepared / "public"
    subjects = [path for path in public.iterdir() if path.is_dir()]
    if len(subjects) != 1:
        raise ValueError("This representative baseline expects one prepared real participant")
    subject_dir = subjects[0]
    metadata = json.loads((subject_dir / "metadata.json").read_text())
    train = np.load(subject_dir / "train.npz", allow_pickle=False)
    validation = np.load(subject_dir / "validation.npz", allow_pickle=False)
    train_labels = json.loads((subject_dir / "train_labels.json").read_text())
    val_labels = json.loads((subject_dir / "validation_labels.json").read_text())
    x_train = features(train["x"], metadata["sampling_hz"])
    x_val = features(validation["x"], metadata["sampling_hz"])
    y_train = np.array([train_labels[item] for item in train["ids"]])
    y_val = np.array([val_labels[item] for item in validation["ids"]])
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, solver="liblinear", max_iter=500))
    model.fit(x_train, y_train)
    probabilities = model.predict_proba(x_val)[:, 1]
    lineage = json.loads((args.prepared / "private" / "lineage.json").read_text())
    val_lineage = lineage["splits"]["validation"]
    grouped = {}
    for item, prediction in zip(validation["ids"], probabilities):
        grouped.setdefault(val_lineage[item]["block"], []).append((float(prediction), int(val_labels[item])))
    if len(grouped) != 2:
        raise ValueError("Validation requires two source blocks")
    class_hits = {0: [], 1: []}
    for entries in grouped.values():
        labels = {label for _, label in entries}
        if len(labels) != 1:
            raise ValueError("Mixed labels within a validation block")
        label = labels.pop()
        class_hits[label].append(int((sum(probability for probability, _ in entries) / len(entries) >= 0.5) == label))
    if len(class_hits[0]) != 1 or len(class_hits[1]) != 1:
        raise ValueError("Validation needs one block of each condition")
    print(json.dumps({
        "status": "real_data_train_validation_baseline_only",
        "participant_count": 1,
        "train_windows": len(y_train),
        "validation_windows": len(y_val),
        "validation_block_balanced_accuracy": (class_hits[0][0] + class_hits[1][0]) / 2,
        "test_used": False,
    }, indent=2))


if __name__ == "__main__":
    main()
