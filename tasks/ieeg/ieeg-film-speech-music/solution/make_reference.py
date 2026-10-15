#!/usr/bin/env python3
"""Fit one small power-spectrum model on a fixed number of Train participants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

import numpy as np
from safetensors.numpy import save_file
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
BANDS = ((1, 4), (4, 8), (8, 13), (13, 30), (30, 80), (80, 120))


def features(x):
    power = np.abs(np.fft.rfft(x, n=512, axis=-1)) ** 2 / 512
    frequencies = np.fft.rfftfreq(512, d=1 / 256)
    rows = []
    for lower, upper in BANDS:
        band = np.log10(power[:, :, (frequencies >= lower) & (frequencies < upper)].mean(axis=-1) + 1e-20)
        rows.extend((np.median(band, axis=1), np.quantile(band, 0.75, axis=1)))
    return np.column_stack(rows).astype(np.float32)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-data", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--train-subjects", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    if args.submission.exists() and any(args.submission.iterdir()):
        raise ValueError("Reference submission directory must be empty")
    subjects = sorted(path for path in args.public_data.iterdir() if path.is_dir())
    if len(subjects) < args.train_subjects:
        raise ValueError("The reference needs the requested public Train participants")
    train_subjects = subjects[:args.train_subjects]
    xs, ys = [], []
    for subject in train_subjects:
        with np.load(subject / "train.npz", allow_pickle=False) as data:
            arrays, ids = data["x"], data["ids"].tolist()
        labels = json.loads((subject / "train_labels.json").read_text())
        xs.append(features(arrays))
        ys.append(np.asarray([labels[identifier] for identifier in ids], dtype=np.int64))
    train_x, train_y = np.concatenate(xs), np.concatenate(ys)
    scaler = StandardScaler().fit(train_x)
    classifier = LogisticRegression(C=1.0, solver="liblinear", max_iter=500).fit(scaler.transform(train_x), train_y)
    args.submission.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "solution" / "model.py", args.submission / "model.py")
    (args.submission / "config.json").write_text(json.dumps({
        "feature_mean": scaler.mean_.astype(np.float32).tolist(),
        "feature_scale": scaler.scale_.astype(np.float32).tolist()}, indent=2) + "\n")
    save_file({"linear.weight": classifier.coef_.astype(np.float32),
               "linear.bias": classifier.intercept_.astype(np.float32)},
              str(args.submission / "weights.safetensors"))
    print(json.dumps({"status": "reference_fit_train_only", "train_subjects": len(train_subjects),
                      "train_windows": len(train_y), "validation_windows_used_in_fit": 0,
                      "validation_labels_used_in_fit": False, "test_used": False}))


if __name__ == "__main__":
    main()
