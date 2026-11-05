"""Isolated numeric conversion of Caltech's disjoint 784-video user-train set."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np


def main() -> None:
    if os.environ.get("MABE_ISOLATED_EXTRACTION") != "1":
        raise RuntimeError("Run only in the documented isolated container")
    root = Path("/data")
    source = root / "mouse_user_train.npy"
    checksum = hashlib.md5()  # noqa: S324 - source-published MD5
    with source.open("rb") as data_file:
        for chunk in iter(lambda: data_file.read(1024 * 1024), b""):
            checksum.update(chunk)
    md5 = checksum.hexdigest()
    if md5 != "389bc12c9ad49b7cb50b531707b448a5":
        raise ValueError("user-train source MD5 mismatch")
    data = np.load(source, allow_pickle=True).item()
    if data["vocabulary"] != ["chases", "lights"] or len(data["sequences"]) != 784:
        raise ValueError("unexpected user-train source")
    output = root / "public" / "probe_usertrain"
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for video_id, record in sorted(data["sequences"].items()):
        if (root / "public" / "probe_pose" / f"{video_id}.npz").exists():
            raise ValueError(f"user-train overlaps submission pose: {video_id}")
        pose, labels = record["keypoints"], record["annotations"]
        if (pose.shape != (1800, 3, 12, 2) or labels.shape != (2, 1800)
                or not np.isfinite(pose).all() or not np.isfinite(labels).all()
                or not np.isin(labels, (0, 1)).all()):
            raise ValueError(f"invalid user-train sequence: {video_id}")
        path = output / f"{video_id}.npz"
        with path.open("wb") as target:
            np.savez_compressed(target, keypoints=pose.astype(np.int32))
        files[video_id] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"schema": "bpb-mabe-usertrain-preparation/2", "source_md5": md5,
                "videos": len(files), "source_vocabulary_not_exported": data["vocabulary"],
                "files": files, "role": "Agent-facing disjoint user-train keypoints only; source annotations are excluded"}
    (root / "usertrain_preparation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"videos": len(files), "vocabulary": data["vocabulary"]}))


if __name__ == "__main__":
    main()
