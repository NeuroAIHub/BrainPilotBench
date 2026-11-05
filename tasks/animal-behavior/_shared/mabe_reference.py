"""Small pose-only supervised reference on the public train/validation split.

This checks the prepared data and scoring path. It is a Bench baseline, not
the ResiFuse architecture and not a paper-comparable score. Test labels are
never opened here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from mabe_metrics import score_supervised_segmentation
from mabe_pose_valid import pose_valid_frames


def features(pose: np.ndarray) -> np.ndarray:
    if pose.shape != (1800, 3, 12, 3):
        raise ValueError("expected 1800 x 3 x 12 x 3 pose")
    xy = pose[..., :2] / 448.0
    confidence = pose[..., 2:]
    raw = np.concatenate((xy, confidence), axis=-1).reshape(1800, 108)
    finite = np.isfinite(raw)
    cleaned = np.nan_to_num(raw, nan=0.0)
    delta = np.zeros_like(cleaned)
    delta[1:] = cleaned[1:] - cleaned[:-1]
    return np.concatenate((cleaned, finite.astype(np.float32), delta), axis=1).astype(np.float32)


def load_role(root: Path, role: str):
    labels_path = root / "public" / f"{role}_labels.npz"
    with np.load(labels_path, allow_pickle=False) as labels:
        ids = sorted(labels.files)
        label_rows = {video_id: labels[video_id].copy() for video_id in ids}
    for video_id in ids:
        if label_rows[video_id].shape != (1800, 4):
            raise ValueError("unexpected label shape")
    return ids, label_rows


def fit(root: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    ids, labels = load_role(root, "train")
    xs, ys = [], []
    for video_id in ids:
        with np.load(root / "public" / "pose" / "train" / f"{video_id}.npz", allow_pickle=False) as data:
            pose = data["pose"]
            x = features(pose)
        eligible = labels[video_id].any(axis=1) & pose_valid_frames(pose)
        if eligible.any():
            xs.append(x[eligible])
            ys.append(labels[video_id][eligible].astype(np.float32))
    if not xs:
        raise ValueError("no public training foreground frames")
    x = np.concatenate(xs)
    y = np.concatenate(ys)
    mean = x.mean(axis=0, dtype=np.float64)
    scale = x.std(axis=0, dtype=np.float64)
    scale[scale < 1e-6] = 1.0
    x = ((x - mean) / scale).astype(np.float64)
    x = np.concatenate((x, np.ones((len(x), 1))), axis=1)
    weights = []
    for class_index in range(4):
        target = y[:, class_index].astype(np.float64)
        positive = int(target.sum())
        negative = len(target) - positive
        if positive == 0 or negative == 0:
            raise ValueError("a reference class has only one label in public train")
        sample_weight = np.where(target > 0, len(target) / (2 * positive), len(target) / (2 * negative))
        weighted_x = x * np.sqrt(sample_weight)[:, None]
        weighted_y = target * np.sqrt(sample_weight)
        gram = weighted_x.T @ weighted_x
        regularizer = np.eye(gram.shape[0])
        regularizer[-1, -1] = 0
        weights.append(np.linalg.solve(gram + regularizer, weighted_x.T @ weighted_y))
    return mean, scale, np.stack(weights, axis=1), {"videos": len(ids), "foreground_frames": len(y),
                                                     "positive_frames_by_class": y.sum(axis=0).astype(int).tolist()}


def validate(root: Path, mean: np.ndarray, scale: np.ndarray, weights: np.ndarray) -> dict:
    ids, labels = load_role(root, "val")
    truth, predictions, mask = {}, {}, {}
    for video_id in ids:
        with np.load(root / "public" / "pose" / "val" / f"{video_id}.npz", allow_pickle=False) as data:
            pose = data["pose"]
            x = features(pose)
        x = np.concatenate((((x - mean) / scale), np.ones((len(x), 1))), axis=1)
        p = np.clip(x @ weights, 0.0, 1.0)
        truth[video_id] = labels[video_id].astype(int).tolist()
        predictions[video_id] = p.tolist()
        mask[video_id] = (labels[video_id].any(axis=1) & pose_valid_frames(pose)).tolist()
    return score_supervised_segmentation(truth, predictions, mask)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    mean, scale, weights, train = fit(args.root)
    validation = validate(args.root, mean, scale, weights)
    report = {"schema": "bpb-mabe-supervised-reference/1", "role": "public train and validation only",
              "model": "pose-only weighted ridge baseline; 0.5 threshold on clipped scores",
              "train": train, "validation": validation,
              "eligibility": "owner-side any-positive grouped behavior intersected with label-independent source-style pose validity (union over mice); no background-only frames scored",
              "comparability": "Bench data-path check, not original MABe22 or ResiFuse paper score"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"train_videos": train["videos"], "validation_videos": validation["videos"],
                      "validation_macro_f1": validation["macro_f1"]}))


if __name__ == "__main__":
    main()
