"""Deterministic, modest Task1 pose reference on public Train/derived Valid.

This is a local preparation probe, not an Agent submission or official Test score.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from calms_metrics import CLASSIC_VOCAB, score_sequences
from calms_prepare import _file_digest, _private_file, verify_prepared


def _features(keypoints: np.ndarray, scores: np.ndarray) -> np.ndarray:
    n = len(keypoints)
    xy = keypoints.astype(np.float64, copy=False).copy()
    xy[:, :, 0, :] /= 1024.0
    xy[:, :, 1, :] /= 570.0
    positions = xy.reshape(n, 28)
    movement = np.zeros_like(positions)
    movement[1:] = positions[1:] - positions[:-1]
    centers = xy.mean(axis=-1)
    separation = centers[:, 0] - centers[:, 1]
    return np.concatenate((positions, movement, separation,
                           scores.reshape(n, 14).astype(np.float64)), axis=1)


def _read(public: Path, row: dict[str, object], role: str) -> tuple[np.ndarray, np.ndarray]:
    filename = row["file"]
    if not isinstance(filename, str) or len(filename) != 68 or not filename.endswith(".npz") or any(c not in "0123456789abcdef" for c in filename[:-4]):
        raise ValueError("unsafe prepared filename")
    path = public / role / filename
    _private_file(path)
    if _file_digest(path) != (row["bytes"], row["sha256"]):
        raise ValueError("prepared sequence bytes or SHA-256 mismatch")
    with np.load(path, allow_pickle=False) as data:
        if set(data.files) != {"keypoints", "scores", "labels"}:
            raise ValueError("prepared sequence array keys mismatch")
        keypoints, scores, labels = data["keypoints"], data["scores"], data["labels"]
    if keypoints.shape != (row["frames"], 2, 2, 7) or scores.shape != (row["frames"], 2, 7) or labels.shape != (row["frames"],):
        raise ValueError("prepared sequence shape mismatch")
    return _features(keypoints, scores), labels


def run(prepared: Path) -> dict[str, object]:
    verify_prepared(prepared, include_owner=False)
    public = prepared / "public"
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "bpb-calms21-public/1" or manifest.get("task") != "task1" or manifest.get("vocab") != CLASSIC_VOCAB:
        raise ValueError("public preparation manifest mismatch")
    train_rows = manifest["splits"]["train"]
    valid_rows = manifest["splits"]["valid"]
    if not train_rows or not valid_rows or {r["id"] for r in train_rows} & {r["id"] for r in valid_rows}:
        raise ValueError("Train/Valid membership mismatch")
    feature_count = 72
    count = np.zeros(4, dtype=np.int64)
    totals = np.zeros((4, feature_count), dtype=np.float64)
    squared = np.zeros(feature_count, dtype=np.float64)
    grand = np.zeros(feature_count, dtype=np.float64)
    for row in train_rows:
        x, labels = _read(public, row, "train")
        grand += x.sum(axis=0)
        squared += np.square(x).sum(axis=0)
        for class_id in range(4):
            mask = labels == class_id
            count[class_id] += int(mask.sum())
            totals[class_id] += x[mask].sum(axis=0)
    if np.any(count == 0):
        raise ValueError("reference requires each classic class in public Train")
    mean = grand / count.sum()
    variance = np.maximum(squared / count.sum() - mean * mean, 1e-6)
    centroids = totals / count[:, None]
    # Diagonal shared-covariance discriminant; no held-out parameter tuning.
    weights = centroids / variance
    intercept = -0.5 * np.square(centroids / np.sqrt(variance)).sum(axis=1)
    intercept += np.log(count / count.sum())
    truth, predicted = {}, {}
    for row in valid_rows:
        x, labels = _read(public, row, "valid")
        logits = x @ weights.T + intercept
        logits -= logits.max(axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        truth[row["id"]] = labels
        predicted[row["id"]] = probabilities
    metrics = score_sequences(truth, predicted, task="task1", vocab=CLASSIC_VOCAB)
    return {"schema": "bpb-calms21-reference-evidence/1", "task": "task1",
            "protocol": "pose and confidence diagonal shared-covariance classifier; no tuning",
            "source_sha256": manifest["source_sha256"],
            "public_manifest_sha256": _file_digest(public / "manifest.json")[1],
            "train_sequences": len(train_rows), "train_frames": int(count.sum()),
            "valid_sequences": len(valid_rows), "valid_frames": metrics["frames"],
            "valid_f1": metrics["f1"], "valid_f1_by_class": metrics["f1_by_class"],
            "official_test_scored": False, "agent_run_started": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.prepared)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
