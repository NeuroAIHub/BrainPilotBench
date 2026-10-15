#!/usr/bin/env python3
"""Fit one fixed, offline ridge reference on the public sub1 train split."""

from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import sys

import numpy as np


TASK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_DIR / "env"))
sys.path.insert(0, str(TASK_DIR / "checks"))
from prepare import ARCHIVE_SHA256, reject_symlinks, sha256_file, validate_cache_dir  # noqa: E402
from score import score_subject  # noqa: E402


WINDOW_SAMPLES = 100
RIDGE_ALPHA = 1.0
SUBJECT = "sub1"


def log_power(ecog: np.ndarray) -> np.ndarray:
    if ecog.ndim != 2 or ecog.shape[1] != 62 or ecog.shape[0] % WINDOW_SAMPLES:
        raise ValueError("sub1 ECoG must have 62 channels and complete 100-sample windows")
    windows = ecog.reshape(-1, WINDOW_SAMPLES, 62).astype(np.float64)
    windows -= windows.mean(axis=1, keepdims=True)
    return np.log1p(np.mean(windows * windows, axis=1))


def window_targets(flexion: np.ndarray) -> np.ndarray:
    if flexion.ndim != 2 or flexion.shape[1] != 5 or flexion.shape[0] % WINDOW_SAMPLES:
        raise ValueError("Finger flexion must have five columns and complete 100-sample windows")
    return flexion.reshape(-1, WINDOW_SAMPLES, 5).mean(axis=1)


def read_prepared(cache_dir: Path) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    prepared = cache_dir / "prepared"
    reject_symlinks(prepared)
    receipt_path = prepared / "preparation_receipt.json"
    reject_symlinks(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("source_sha256") != ARCHIVE_SHA256:
        raise ValueError("Preparation receipt does not identify the pinned source ZIP")
    records = receipt["files"][SUBJECT]
    arrays: dict[str, np.ndarray] = {}
    for name in ("train_ecog", "train_flexion", "valid_ecog", "valid_flexion"):
        path = prepared / SUBJECT / f"{name}.npy"
        reject_symlinks(path)
        record = records[name]
        if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
            raise ValueError(f"Prepared input differs from its receipt: {name}")
        arrays[name] = np.load(path, mmap_mode="r", allow_pickle=False)
    if arrays["train_ecog"].shape != (319_000, 62) or arrays["train_flexion"].shape != (319_000, 5):
        raise ValueError("sub1 train arrays have unexpected shapes")
    if arrays["valid_ecog"].shape != (79_000, 62) or arrays["valid_flexion"].shape != (79_000, 5):
        raise ValueError("sub1 validation arrays have unexpected shapes")
    return arrays, receipt


def run(cache_dir: Path) -> None:
    arrays, source_receipt = read_prepared(cache_dir)
    train_features = log_power(arrays["train_ecog"])
    valid_features = log_power(arrays["valid_ecog"])
    train_targets = window_targets(arrays["train_flexion"])

    feature_mean = train_features.mean(axis=0)
    feature_std = train_features.std(axis=0)
    feature_std[feature_std == 0] = 1.0
    train_standard = (train_features - feature_mean) / feature_std
    valid_standard = (valid_features - feature_mean) / feature_std
    target_mean = train_targets.mean(axis=0)
    regularized = np.einsum("ni,nj->ij", train_standard, train_standard) + RIDGE_ALPHA * np.eye(62)
    cross_product = np.einsum("ni,nj->ij", train_standard, train_targets - target_mean)
    weights = np.linalg.solve(regularized, cross_product)
    valid_window_prediction = np.einsum("ni,ij->nj", valid_standard, weights) + target_mean
    valid_prediction = np.repeat(valid_window_prediction, WINDOW_SAMPLES, axis=0)
    if not np.isfinite(valid_prediction).all():
        raise ValueError("Reference prediction contains nonfinite values")
    correlations = score_subject(valid_prediction, arrays["valid_flexion"])
    mean_correlation = float(np.mean(correlations))

    output = cache_dir / "reference" / SUBJECT
    reject_symlinks(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite reference output in {output}")
    output.mkdir(parents=True)
    model_path = output / "model.npz"
    prediction_path = output / "valid_prediction.npy"
    with model_path.open("xb") as stream:
        np.savez(stream, feature_mean=feature_mean, feature_std=feature_std,
                 target_mean=target_mean, weights=weights,
                 window_samples=WINDOW_SAMPLES, ridge_alpha=RIDGE_ALPHA)
    with prediction_path.open("xb") as stream:
        np.save(stream, valid_prediction, allow_pickle=False)

    score_script = TASK_DIR / "checks" / "score.py"
    receipt = {
        "schema": "bpb-invasive-reference-receipt/1",
        "task_id": "ieeg-finger-flexion-bciciv4",
        "scope": "sub1 public validation only; offline fixed reference; not an Agent or official competition score",
        "source_sha256": source_receipt["source_sha256"],
        "preparation_receipt_sha256": sha256_file(cache_dir / "prepared" / "preparation_receipt.json"),
        "protocol_sha256": sha256_file(TASK_DIR / "protocol.json"),
        "prepare_script_sha256": sha256_file(TASK_DIR / "env" / "prepare.py"),
        "reference_script_sha256": sha256_file(Path(__file__)),
        "score_script_sha256": sha256_file(score_script),
        "packages": {"numpy": version("numpy"), "scipy": version("scipy")},
        "feature": "log1p of mean squared mean-centered ECoG in independent nonoverlapping 100-sample windows",
        "target": "mean flexion in each 100-sample training window",
        "predictive_time_scope": "offline noncausal 100-sample windows; window prediction repeated at 1000 Hz",
        "standardization_fit": "train only",
        "ridge_alpha": RIDGE_ALPHA,
        "train_samples": 319_000,
        "valid_samples": 79_000,
        "scored_finger_indices_zero_based": [0, 1, 2, 4],
        "valid_pearson_r_by_finger": dict(zip(("thumb", "index", "middle", "little"), correlations)),
        "valid_four_finger_mean_pearson_r": mean_correlation,
        "outputs": {
            "model": {"path": str(model_path), "bytes": model_path.stat().st_size, "sha256": sha256_file(model_path)},
            "prediction": {"path": str(prediction_path), "shape": list(valid_prediction.shape),
                           "bytes": prediction_path.stat().st_size, "sha256": sha256_file(prediction_path)},
        },
    }
    receipt_path = output / "reference_receipt.json"
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"receipt": str(receipt_path), "valid_four_finger_mean_pearson_r": mean_correlation}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    run(validate_cache_dir(args.cache_dir))


if __name__ == "__main__":
    main()
