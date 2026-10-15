#!/usr/bin/env python3
"""Check a representative export against its pinned real source and receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


TASK_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_ROOT / "env"))
from fetch_representative import BASE, MANIFEST, digest_ok  # noqa: E402
PROTOCOL = json.loads((TASK_ROOT / "protocol.json").read_text())
CODE_FILES = {
    "source_manifest": TASK_ROOT / "source_manifest.json",
    "protocol": TASK_ROOT / "protocol.json",
    "prepare": TASK_ROOT / "env" / "prepare.py",
    "verify": Path(__file__).resolve(),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        while chunk := input_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify(source_root: Path, prepared: Path) -> dict:
    files = MANIFEST["representative"]["files"]
    for key, spec in files.items():
        path = source_root / BASE / spec["name"]
        if not digest_ok(path, spec):
            raise ValueError(f"Pinned real source failed: {key}")
    receipt = json.loads((prepared / "private" / "receipt.json").read_text())
    if receipt["source_commit"] != MANIFEST["dataset_git_commit"]:
        raise ValueError("The receipt source commit differs from the pinned manifest")
    for name, path in CODE_FILES.items():
        if receipt.get("code_sha256", {}).get(name) != sha256(path):
            raise ValueError(f"The receipt does not match the current {name} file")
    signal = source_root / BASE / files["signal"]["name"]
    if receipt["source_signal_sha256"] != sha256(signal):
        raise ValueError("The receipt does not match the verified source signal")
    if receipt["test_signal_windows_requested"] != 0 or receipt["test_exported"]:
        raise ValueError("The representative must not use Test windows")
    public_root = prepared / "public"
    participants = [path for path in public_root.iterdir() if path.is_dir()]
    if len(participants) != 1:
        raise ValueError("The representative needs exactly one public participant")
    participant = participants[0]
    lineage = json.loads((prepared / "private" / "lineage.json").read_text())
    if lineage["source_subject"] != MANIFEST["representative"]["subject"]:
        raise ValueError("The private lineage names a different source subject")
    if lineage["anonymous_subject"] != participant.name:
        raise ValueError("The private lineage and public participant ID disagree")
    if set(lineage["splits"]) != {"train", "validation"}:
        raise ValueError("The private lineage has unexpected split names")
    if set(path.name for path in participant.iterdir()) != {
        "train.npz", "train_labels.json", "validation.npz", "validation_labels.json", "metadata.json"
    }:
        raise ValueError("The public bundle has unexpected or missing files")
    metadata = json.loads((participant / "metadata.json").read_text())
    if set(metadata) != {"sampling_hz", "window_seconds", "channel_ids", "channel_types", "label_codes"}:
        raise ValueError("The public metadata exposes unexpected fields")
    if metadata["sampling_hz"] != 256 or metadata["window_seconds"] != 2:
        raise ValueError("The prepared window settings differ from protocol")
    expected = {"train": {0: 52, 1: 39}, "validation": {0: 13, 1: 13}}
    observed_ids = set()
    for split, counts in expected.items():
        array_path = participant / f"{split}.npz"
        labels_path = participant / f"{split}_labels.json"
        if receipt["public"][split]["arrays_sha256"] != sha256(array_path):
            raise ValueError(f"{split} array hash differs from the receipt")
        if receipt["public"][split]["labels_sha256"] != sha256(labels_path):
            raise ValueError(f"{split} label hash differs from the receipt")
        with np.load(array_path, allow_pickle=False) as data:
            if set(data.files) != {"x", "ids"}:
                raise ValueError(f"{split} arrays expose extra fields")
            x, ids = data["x"], data["ids"].tolist()
        if x.shape != (sum(counts.values()), len(metadata["channel_ids"]), 512):
            raise ValueError(f"{split} array shape is wrong")
        if not np.isfinite(x).all():
            raise ValueError(f"{split} array has non-finite values")
        if len(ids) != len(set(ids)) or observed_ids.intersection(ids):
            raise ValueError("Window IDs duplicate within or across splits")
        observed_ids.update(ids)
        labels = json.loads(labels_path.read_text())
        if set(labels) != set(ids):
            raise ValueError(f"{split} labels and arrays disagree on IDs")
        split_lineage = lineage["splits"][split]
        if set(split_lineage) != set(ids):
            raise ValueError(f"{split} private lineage and arrays disagree on IDs")
        expected_blocks = set(PROTOCOL["block_assignment"][split])
        seen_locations = set()
        for sample_id, location in split_lineage.items():
            block, window = location["block"], location["window"]
            if block not in expected_blocks or block in PROTOCOL["block_assignment"]["test"]:
                raise ValueError(f"{split} lineage includes a block outside its split")
            if window not in range(13) or (block, window) in seen_locations:
                raise ValueError(f"{split} lineage has an invalid or duplicate window")
            expected_label = PROTOCOL["condition_codes"][PROTOCOL["expected_conditions"][block - 1]]
            if labels[sample_id] != expected_label:
                raise ValueError(f"{split} label differs from its private block lineage")
            seen_locations.add((block, window))
        if len(seen_locations) != 13 * len(expected_blocks):
            raise ValueError(f"{split} lineage does not cover all declared windows")
        if {label: list(labels.values()).count(label) for label in (0, 1)} != counts:
            raise ValueError(f"{split} condition counts differ from protocol")
    if any("test" in path.name.lower() for path in prepared.rglob("*")):
        raise ValueError("The representative contains a Test-named path")
    return {
        "status": "real_source_hashes_and_exported_structure_verified",
        "subject_count": 1,
        "train_windows": 91,
        "validation_windows": 26,
        "good_intracranial_channels": len(metadata["channel_ids"]),
        "test_windows_exported": 0,
        "full_task_accepted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--prepared", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.source_root, args.prepared), indent=2))


if __name__ == "__main__":
    main()
