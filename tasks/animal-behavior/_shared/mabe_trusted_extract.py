"""Convert the pinned Caltech object NPY to numeric-only split labels.

Run only in a disposable, no-network, read-only container. NumPy must unpickle
the source object; the host-side preparation code never loads that object.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

EXPECTED_MD5 = {
    "mouse_submission_labels.npy": "7f10c2b676e7dd8b4348423f0ee0aa8a",
    "mouse_frame_number_map.npy": "ffc1dcae90176cdac4ff4fe123e18f25",
}
GROUPS = {
    "chases": ("chases",),
    "huddles": ("huddles",),
    "oral_contact": ("oral_ear_contact", "oral_oral_contact"),
    "oral_genital_contact": ("oral_genital_contact",),
}


def md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - matching the published source checksum
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if os.environ.get("MABE_ISOLATED_EXTRACTION") != "1":
        raise RuntimeError("Run only in the documented isolated container")
    root = Path("/data")
    for name, expected in EXPECTED_MD5.items():
        if md5(root / name) != expected:
            raise ValueError(f"source checksum mismatch: {name}")

    split = json.loads((root / "mabe_finetune_split.json").read_text())["splits"]
    if {key: len(value) for key, value in split.items()} != {"train": 54, "val": 11, "test": 43}:
        raise ValueError("unexpected pinned supervised split")
    all_ids = [video_id for ids in split.values() for video_id in ids]
    if len(set(all_ids)) != 108 or any(not x.isalnum() or len(x) != 20 for x in all_ids):
        raise ValueError("duplicate or malformed video IDs")

    # This is the only deliberately unsafe source operation, inside the
    # no-network container with just the data directory mounted.
    source = np.load(root / "mouse_submission_labels.npy", allow_pickle=True).item()
    separate_map = np.load(root / "mouse_frame_number_map.npy", allow_pickle=True).item()
    if source["frame_number_map"] != separate_map:
        raise ValueError("embedded and separate frame maps differ")
    vocabulary = source["vocabulary"]
    values = source["label_array"]
    if values.shape != (13, 3294000) or not np.isfinite(values).all():
        raise ValueError("unexpected label array")
    if len(vocabulary) != 13 or len(set(vocabulary)) != 13:
        raise ValueError("invalid vocabulary")
    if any(name not in vocabulary for names in GROUPS.values() for name in names):
        raise ValueError("missing source behavior label")
    if any(video_id not in separate_map for video_id in all_ids):
        raise ValueError("split ID missing from official label map")

    outputs = {}
    for role, ids in split.items():
        rows = {}
        for video_id in ids:
            start, end = separate_map[video_id]
            if end - start != 1800 or not 0 <= start < end <= values.shape[1]:
                raise ValueError(f"unexpected frame map span for {video_id}")
            per_class = []
            for source_names in GROUPS.values():
                indices = [vocabulary.index(name) for name in source_names]
                per_class.append(np.any(values[indices, start:end] > 0.5, axis=0))
            labels = np.stack(per_class, axis=1).astype(np.uint8)
            if labels.shape != (1800, 4):
                raise ValueError("label shape mismatch")
            rows[video_id] = labels
        destination = root / ("owner" if role == "test" else "public")
        destination.mkdir(mode=0o700, exist_ok=True)
        if role == "test":
            destination.chmod(0o700)
        target = destination / f"{role}_labels.npz"
        with target.open("wb") as output:
            np.savez_compressed(output, **rows)
        if role == "test":
            target.chmod(0o600)
        outputs[role] = {"path": str(target.relative_to(root)), "videos": len(rows),
                         "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}

    report = {
        "schema": "bpb-mabe-numeric-label-extraction/1",
        "source_md5": EXPECTED_MD5,
        "split_sha256": hashlib.sha256((root / "mabe_finetune_split.json").read_bytes()).hexdigest(),
        "class_order": list(GROUPS),
        "source_groups": {key: list(value) for key, value in GROUPS.items()},
        "frame_count_per_video": 1800,
        "outputs": outputs,
        "boundary": "Test labels are in owner/ only; no Test mask or labels are in public/.",
    }
    (root / "label_extraction_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"schema": report["schema"], "videos": {k: v["videos"] for k, v in outputs.items()},
                      "frame_count_per_video": 1800}))


if __name__ == "__main__":
    main()
