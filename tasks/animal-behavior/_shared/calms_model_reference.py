"""Fit and export a frozen, public-Train-only Task1 reference submission."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from calms_freeze import freeze
from calms_reference import _read
from calms_prepare import verify_prepared


MODEL_SOURCE = '''"""Fixed CalMS21 pose reference; trained on public Task1 Train only."""
import numpy as np

def _features(keypoints, scores):
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

class Model:
    def __init__(self, weights, intercept):
        self.weights = weights
        self.intercept = intercept

    def predict_proba(self, keypoints, scores, context):
        if context["task"] != "task1" or context["group"] != "annotator-id_0" or context["class_count"] != 4:
            raise ValueError("reference supports Task1 classic classification only")
        logits = _features(keypoints, scores) @ self.weights.T + self.intercept
        logits -= logits.max(axis=1, keepdims=True)
        probabilities = np.exp(logits)
        return probabilities / probabilities.sum(axis=1, keepdims=True)

def load_model(config, weights_path):
    if config != {"schema": "bpb-calms21-reference-config/1", "task": "task1"}:
        raise ValueError("configuration mismatch")
    with np.load(weights_path, allow_pickle=False) as source:
        if set(source.files) != {"weights", "intercept"}:
            raise ValueError("weights schema mismatch")
        return Model(source["weights"], source["intercept"])
'''


def export(prepared: Path, output: Path) -> dict:
    verify_prepared(prepared, include_owner=False)
    manifest = json.loads((prepared / "public/manifest.json").read_text(encoding="utf-8"))
    rows = manifest["splits"]["train"]
    count = np.zeros(4, dtype=np.int64)
    totals = np.zeros((4, 72), dtype=np.float64)
    squared = np.zeros(72, dtype=np.float64)
    grand = np.zeros(72, dtype=np.float64)
    for row in rows:
        x, labels = _read(prepared / "public", row, "train")
        grand += x.sum(axis=0)
        squared += np.square(x).sum(axis=0)
        for class_id in range(4):
            mask = labels == class_id
            count[class_id] += int(mask.sum())
            totals[class_id] += x[mask].sum(axis=0)
    if np.any(count == 0):
        raise ValueError("all classes required in Train")
    mean = grand / count.sum()
    variance = np.maximum(squared / count.sum() - mean * mean, 1e-6)
    centroids = totals / count[:, None]
    weights = centroids / variance
    intercept = -0.5 * np.square(centroids / np.sqrt(variance)).sum(axis=1)
    intercept += np.log(count / count.sum())
    if output.exists():
        raise FileExistsError("fresh output required")
    staging = output.with_name(output.name + "-staging")
    if staging.exists():
        raise FileExistsError("staging path exists")
    staging.mkdir(mode=0o700, parents=True)
    (staging / "model.py").write_text(MODEL_SOURCE, encoding="utf-8")
    (staging / "config.json").write_text(json.dumps({"schema": "bpb-calms21-reference-config/1", "task": "task1"}), encoding="utf-8")
    with (staging / "weights.npz").open("xb") as stream:
        np.savez(stream, weights=weights, intercept=intercept)
    for child in staging.iterdir():
        os.chmod(child, 0o600)
    result = freeze(staging, output)
    for child in staging.iterdir():
        child.unlink()
    staging.rmdir()
    return {"frozen": result, "train_sequences": len(rows), "train_frames": int(count.sum())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.prepared, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
