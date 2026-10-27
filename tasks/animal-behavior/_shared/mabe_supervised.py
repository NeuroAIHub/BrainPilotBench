"""Owner-only MABe22 supervised scorer for full-sequence Agent probabilities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from mabe_metrics import score_supervised_segmentation
from mabe_pose_valid import pose_valid_frames


def score_owner_test(root: Path, prediction_dir: Path) -> dict:
    split = json.loads((root / "mabe_finetune_split.json").read_text())["splits"]
    ids = split["test"]
    with np.load(root / "owner" / "test_labels.npz", allow_pickle=False) as labels:
        if set(labels.files) != set(ids):
            raise ValueError("owner Test label membership mismatch")
        truth = {video_id: labels[video_id].copy() for video_id in ids}
    if {path.stem for path in prediction_dir.glob("*.npz")} != set(ids):
        raise ValueError("prediction files must match the 43 Test IDs exactly")
    predictions = {}
    masks = {}
    for video_id in ids:
        with np.load(prediction_dir / f"{video_id}.npz", allow_pickle=False) as data:
            if set(data.files) != {"probabilities"}:
                raise ValueError(f"unexpected prediction keys: {video_id}")
            p = data["probabilities"]
        if (p.shape != (1800, 4) or p.dtype.kind != "f"
                or not np.isfinite(p).all() or not np.logical_and(p >= 0, p <= 1).all()):
            raise ValueError(f"invalid Test probability matrix: {video_id}")
        with np.load(root / "public" / "pose" / "test" / f"{video_id}.npz", allow_pickle=False) as data:
            pose = data["pose"]
            if not np.array_equal(data["frame_index"], np.arange(1800)):
                raise ValueError(f"pose frame index mismatch: {video_id}")
        predictions[video_id] = p.tolist()
        masks[video_id] = (truth[video_id].any(axis=1) & pose_valid_frames(pose)).tolist()
    result = score_supervised_segmentation(
        {video_id: y.astype(int).tolist() for video_id, y in truth.items()},
        predictions, masks,
    )
    result["profile"] = "BrainPilotBench-MABe22-supervised-positive-pose-valid-v1"
    result["note"] = "Owner-only Test score; excludes background-only frames and cannot measure their false alarms"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-test", action="store_true", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = score_owner_test(args.root, args.predictions)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"macro_f1": result["macro_f1"], "videos": result["videos"]}))


if __name__ == "__main__":
    main()
