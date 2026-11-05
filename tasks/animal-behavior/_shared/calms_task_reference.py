"""Public-Train-only CalMS reference submission for the three source tasks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from calms_freeze import snapshot
from calms_runner import _role_packet
from calms_task_common import load_contract, stage_public_cache


MODEL_SOURCE = '''"""Small public-Train-only CalMS linear pose classifier."""
import numpy as np

def _features(keypoints, scores):
    n = len(keypoints)
    xy = keypoints.astype(np.float64, copy=False).copy()
    xy[:, :, 0, :] /= 1024.0
    xy[:, :, 1, :] /= 570.0
    position = xy.reshape(n, 28)
    motion = np.zeros_like(position)
    motion[1:] = position[1:] - position[:-1]
    centers = xy.mean(axis=-1)
    separation = centers[:, 0] - centers[:, 1]
    return np.concatenate((position, motion, separation,
                           scores.reshape(n, 14).astype(np.float64)), axis=1)

class Model:
    def __init__(self, task, groups, weights, intercepts):
        self.task, self.groups = task, groups
        self.weights, self.intercepts = weights, intercepts

    def predict_proba(self, keypoints, scores, context):
        if context.get("task") != self.task or context.get("group") not in self.groups:
            raise ValueError("task/group mismatch")
        i = self.groups.index(context["group"])
        weights, intercept = self.weights[i], self.intercepts[i]
        if context.get("class_count") != len(intercept):
            raise ValueError("class count mismatch")
        logits = _features(keypoints, scores) @ weights.T + intercept
        logits -= logits.max(axis=1, keepdims=True)
        probabilities = np.exp(logits)
        return probabilities / probabilities.sum(axis=1, keepdims=True)

def load_model(config, weights_path):
    if (not isinstance(config, dict) or config.get("schema") != "bpb-calms21-public-reference/1"
            or config.get("task") not in ("task1", "task2", "task3")
            or not isinstance(config.get("groups"), list) or not config["groups"]):
        raise ValueError("reference configuration mismatch")
    groups = config["groups"]
    expected = {f"weights_{i}" for i in range(len(groups))} | {f"intercept_{i}" for i in range(len(groups))}
    with np.load(weights_path, allow_pickle=False) as arrays:
        if set(arrays.files) != expected:
            raise ValueError("reference weights mismatch")
        weights = [arrays[f"weights_{i}"] for i in range(len(groups))]
        intercepts = [arrays[f"intercept_{i}"] for i in range(len(groups))]
    return Model(config["task"], groups, weights, intercepts)
'''


def _features(keypoints: np.ndarray, scores: np.ndarray) -> np.ndarray:
    n = len(keypoints)
    xy = keypoints.astype(np.float64, copy=False).copy()
    xy[:, :, 0, :] /= 1024.0
    xy[:, :, 1, :] /= 570.0
    position = xy.reshape(n, 28)
    motion = np.zeros_like(position)
    motion[1:] = position[1:] - position[:-1]
    centers = xy.mean(axis=-1)
    separation = centers[:, 0] - centers[:, 1]
    return np.concatenate((position, motion, separation, scores.reshape(n, 14).astype(np.float64)), axis=1)


def export(task_dir: Path, public_dir: Path, output: Path) -> dict:
    contract = load_contract(task_dir)
    packet = public_dir.parent
    _role_packet(packet, "valid", contract["public_manifest_sha256"])
    manifest = json.loads((public_dir / "manifest.json").read_text(encoding="utf-8"))
    groups = contract["groups"]
    vocab_by_group = manifest.get("vocab_by_group", {"annotator-id_0": manifest.get("vocab")})
    if set(groups) != set(vocab_by_group):
        raise ValueError("reference group binding mismatch")
    arrays = {}
    total_frames = 0
    for index, group in enumerate(groups):
        classes = len(vocab_by_group[group])
        count = np.zeros(classes, dtype=np.int64)
        sums = np.zeros((classes, 72), dtype=np.float64)
        square = np.zeros(72, dtype=np.float64)
        grand = np.zeros(72, dtype=np.float64)
        for row in manifest["splits"]["train"]:
            if row.get("group", "annotator-id_0") != group:
                continue
            with np.load(public_dir / "train" / row["file"], allow_pickle=False) as source:
                keypoints, scores, labels = source["keypoints"], source["scores"], source["labels"]
            features = _features(keypoints, scores)
            grand += features.sum(axis=0)
            square += np.square(features).sum(axis=0)
            for class_id in range(classes):
                mask = labels == class_id
                count[class_id] += int(mask.sum())
                sums[class_id] += features[mask].sum(axis=0)
        if not count.sum():
            raise ValueError("reference Train group empty")
        total_frames += int(count.sum())
        mean = grand / count.sum()
        variance = np.maximum(square / count.sum() - np.square(mean), 1e-6)
        centroids = np.vstack([sums[c] / count[c] if count[c] else mean for c in range(classes)])
        weights = centroids / variance
        intercept = -0.5 * np.square(centroids / np.sqrt(variance)).sum(axis=1)
        intercept += np.log((count + 1) / (count.sum() + classes))
        arrays[f"weights_{index}"] = weights
        arrays[f"intercept_{index}"] = intercept
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh submission directory required")
    os.umask(0o077)
    output.mkdir(mode=0o700, parents=True)
    with os.fdopen(os.open(output / "model.py", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        stream.write(MODEL_SOURCE)
    with os.fdopen(os.open(output / "config.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump({"schema": "bpb-calms21-public-reference/1", "task": contract["source_task"],
                   "groups": groups}, stream, sort_keys=True)
        stream.write("\n")
    with os.fdopen(os.open(output / "weights.npz", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        np.savez(stream, **arrays)
    snapshot(output)
    return {"task": contract["task_id"], "groups": len(groups),
            "train_frames": total_frames, "source": "public Train only"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    public = parser.add_mutually_exclusive_group(required=True)
    public.add_argument("--public-dir", type=Path)
    public.add_argument("--public-cache", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.public_cache:
        contract = load_contract(args.task)
        with tempfile.TemporaryDirectory(prefix="bpb-calms-reference-public-") as temp:
            packet = Path(temp).resolve() / "packet"
            stage_public_cache(args.task, contract, packet)
            result = export(args.task, packet / "public", args.output)
    else:
        result = export(args.task, args.public_dir, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
