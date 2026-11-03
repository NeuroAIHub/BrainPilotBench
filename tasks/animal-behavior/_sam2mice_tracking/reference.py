"""Train-only background subtraction and nearest-centroid tracking reference."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from inference import _resolve, load_features, load_truth, snapshot_model

CONFIG = {"model": "train-background-centroid-v1", "stride": 4,
          "foreground_threshold": 25.0, "max_displacement": 0.15}

MODEL_SOURCE = '''"""Fixed Train background and component/centroid tracker."""
import numpy as np
from scipy import ndimage
from scipy.optimize import linear_sum_assignment


class Model:
    def __init__(self, config, weights_path):
        if config != {"model": "train-background-centroid-v1", "stride": 4,
                      "foreground_threshold": 25.0, "max_displacement": 0.15}:
            raise ValueError("configuration differs")
        self.config = config
        with np.load(weights_path, allow_pickle=False) as weights:
            self.background = weights["background"]
            self.source_shape = weights["source_shape"]
            self.median_area = float(weights["median_box_area"].item())
            self.max_objects = int(weights["max_objects"].item())

    def predict(self, frames, context):
        if (context["task_id"] != "sam2mice-multi-animal-tracking"
                or list(frames.shape[1:3]) != self.source_shape.tolist()):
            raise ValueError("task or image dimensions differ")
        stride = self.config["stride"]
        height, width = frames.shape[1:3]
        minimum_area = max(2, self.median_area * height * width / stride**2 * 0.15)
        maximum_area = self.median_area * height * width / stride**2 * 3.0
        previous_centers = np.empty((0, 2), dtype=np.float64)
        previous_ids = np.empty(0, dtype=np.int64)
        next_id = 0
        rows = []
        for index, frame in enumerate(frames):
            gray = frame[::stride, ::stride].astype(np.float32).mean(axis=2)
            foreground = np.abs(gray - self.background) > self.config["foreground_threshold"]
            foreground = ndimage.binary_opening(foreground, structure=np.ones((3, 3), dtype=bool))
            foreground = ndimage.binary_closing(foreground, structure=np.ones((3, 3), dtype=bool))
            components, count = ndimage.label(foreground)
            areas = np.bincount(components.ravel(), minlength=count + 1)
            candidates = []
            for label, region in enumerate(ndimage.find_objects(components), start=1):
                if region is None or not minimum_area <= areas[label] <= maximum_area:
                    continue
                y, x = region
                box = np.array([x.start * stride / width, y.start * stride / height,
                                min(x.stop * stride, width) / width,
                                min(y.stop * stride, height) / height])
                candidates.append((int(areas[label]), box))
            candidates.sort(key=lambda value: (-value[0], value[1][0], value[1][1]))
            boxes = np.array([value[1] for value in candidates[:self.max_objects]], dtype=np.float64).reshape(-1, 4)
            centers = (boxes[:, :2] + boxes[:, 2:]) / 2
            identities = np.full(len(boxes), -1, dtype=np.int64)
            if len(previous_centers) and len(centers):
                distances = np.linalg.norm(previous_centers[:, None, :] - centers[None, :, :], axis=2)
                old, new = linear_sum_assignment(distances)
                for before, after in zip(old, new):
                    if distances[before, after] <= self.config["max_displacement"]:
                        identities[after] = previous_ids[before]
            for item in range(len(boxes)):
                if identities[item] < 0:
                    identities[item] = next_id
                    next_id += 1
                rows.append([index, identities[item], *boxes[item]])
            previous_centers, previous_ids = centers, identities
        return np.asarray(rows, dtype=np.float64).reshape(-1, 6)


def load_model(config, weights_path):
    return Model(config, weights_path)
'''


def fit_reference(train_sequences: list[dict], output: Path, *, root: Path) -> dict:
    if (not isinstance(train_sequences, list) or not train_sequences
            or len(train_sequences) > 128):
        raise ValueError("nonempty bounded Train sequence list required")
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh reference destination required")
    if any(part.is_symlink() for part in (output.parent, *output.parent.parents)):
        raise ValueError("reference destination has a symlink ancestor")
    if (len({row.get("feature_path") for row in train_sequences}) != len(train_sequences)
            or len({row.get("label_path") for row in train_sequences}) != len(train_sequences)):
        raise ValueError("unique Train feature and truth paths required")
    images, areas, frame_object_counts, identifiers = [], [], [], set()
    shape = None
    frame_count = 0
    for row in train_sequences:
        if row.get("split") != "train" or not row.get("id") or row["id"] in identifiers:
            raise ValueError("unique Train-only reference rows required")
        identifiers.add(row["id"])
        frames = load_features(_resolve(root, row["feature_path"]),
                               expected_bytes=row["feature_bytes"],
                               expected_sha256=row["feature_sha256"], frames=row["frames"])
        truth = load_truth(_resolve(root, row["label_path"]), expected_bytes=row["label_bytes"],
                           expected_sha256=row["label_sha256"], frames=row["frames"])
        if not len(truth):
            raise ValueError("Train sequence has no annotated objects")
        if shape is not None and frames.shape[1:3] != shape:
            raise ValueError("Train image dimensions changed")
        shape = frames.shape[1:3]
        # Sample at fixed indices before model fitting. No Valid or Test data enter this estimate.
        sample_indices = np.linspace(0, len(frames) - 1, min(8, len(frames)), dtype=int)
        for index in sample_indices:
            images.append(frames[index, ::CONFIG["stride"], ::CONFIG["stride"]].astype(np.float32).mean(axis=2))
        areas.extend(np.prod(truth[:, 4:] - truth[:, 2:4], axis=1).tolist())
        frame_object_counts.extend(np.bincount(truth[:, 0].astype(np.int64), minlength=len(frames)).tolist())
        frame_count += len(frames)
    background = np.median(np.stack(images), axis=0).astype(np.float32)
    median_area = float(np.median(areas))
    max_objects = int(max(1, min(64, np.ceil(np.median(frame_object_counts)))))
    output.mkdir(parents=True, mode=0o700)
    for name, content in (("model.py", MODEL_SOURCE),
                          ("config.json", json.dumps(CONFIG, sort_keys=True) + "\n")):
        with os.fdopen(os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as writer:
            writer.write(content)
    with os.fdopen(os.open(output / "weights.npz", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
        np.savez(writer, background=background, source_shape=np.asarray(shape, dtype=np.int32),
                 median_box_area=np.array(median_area, dtype=np.float32),
                 max_objects=np.array(max_objects, dtype=np.int32))
    snapshot_model(output)
    return {"reference": CONFIG["model"], "train_sequences": len(identifiers),
            "train_frames": frame_count, "background_samples": len(images),
            "width": shape[1], "height": shape[0], "max_objects": max_objects,
            "validation_or_test_read": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--train-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.train_manifest.read_text())
    rows = manifest["sequences"] if isinstance(manifest, dict) else manifest
    print(json.dumps(fit_reference(rows, args.output, root=args.root), sort_keys=True))


if __name__ == "__main__":
    main()
