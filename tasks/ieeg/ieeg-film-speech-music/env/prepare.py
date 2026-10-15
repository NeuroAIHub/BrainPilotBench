#!/usr/bin/env python3
"""Prepare a real public train/validation sample from pinned ds003688 sub-02.

This stage hashes the full source file, but never requests a Test signal
interval. It makes no Test array or label export. Full-cohort preparation and
evaluator binding need later review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from fetch_representative import BASE, MANIFEST, digest_ok


TASK_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((TASK_ROOT / "protocol.json").read_text())
FILES = MANIFEST["representative"]["files"]
TEST_BLOCKS = set(PROTOCOL["block_assignment"]["test"])
PUBLIC_SPLITS = ("train", "validation")
CODE_FILES = {
    "source_manifest": TASK_ROOT / "source_manifest.json",
    "protocol": TASK_ROOT / "protocol.json",
    "prepare": Path(__file__).resolve(),
    "verify": TASK_ROOT / "checks" / "verify_prepared.py",
}


def source_files(source_root: Path) -> dict[str, Path]:
    directory = source_root / BASE
    files = {key: directory / spec["name"] for key, spec in FILES.items()}
    for key, path in files.items():
        if not digest_ok(path, FILES[key]):
            raise ValueError(f"Pinned source file missing or invalid: {key}: {path}")
    return files


def read_events(path: Path) -> list[tuple[float, float, str]]:
    with path.open(newline="") as input_file:
        rows = list(csv.DictReader(input_file, delimiter="\t"))
    blocks = [row for row in rows if row["trial_type"] in ("music", "speech")]
    expected = PROTOCOL["expected_conditions"]
    if len(blocks) != len(expected):
        raise ValueError("The source does not contain exactly 13 film blocks")
    result = []
    for index, (row, condition) in enumerate(zip(blocks, expected), start=1):
        onset, duration = float(row["onset"]), float(row["duration"])
        if row["trial_type"] != condition or not (29.0 <= duration <= 31.0):
            raise ValueError(f"Film block {index} differs from the pinned protocol")
        if index > 1 and abs(onset - (result[-1][0] + result[-1][1])) > 0.25:
            raise ValueError(f"Film block {index} has a timing gap")
        result.append((onset, duration, condition))
    return result


def read_good_channels(path: Path) -> tuple[list[str], list[str]]:
    with path.open(newline="") as input_file:
        rows = list(csv.DictReader(input_file, delimiter="\t"))
    selected = [
        row for row in rows
        if row["type"].upper() in ("ECOG", "SEEG") and row["status"].lower() == "good"
    ]
    names = [row["name"] for row in selected]
    types = [row["type"].upper() for row in selected]
    if not names or len(names) != len(set(names)):
        raise ValueError("There are no unique good intracranial channels")
    return names, types


def opaque(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:24]


def build_windows(raw, blocks, picks, key: bytes, split: str):
    sample_hz = raw.info["sfreq"]
    target_hz = PROTOCOL["window"]["processed_sampling_hz"]
    if sample_hz not in (512, 2048):
        raise ValueError(f"The clinical recording has an unreviewed sampling rate: {sample_hz}")
    if int(sample_hz) % target_hz:
        raise ValueError("The source sampling rate is not an integer multiple of 256 Hz")
    if TEST_BLOCKS & set(PROTOCOL["block_assignment"][split]):
        raise ValueError("A public split overlaps evaluator-only Test")
    output = []
    for block_number in PROTOCOL["block_assignment"][split]:
        onset, duration, condition = blocks[block_number - 1]
        kept = 0
        for window_number, local_start in enumerate(PROTOCOL["window"]["local_start_seconds"]):
            if local_start < 2 or local_start + 2 + 2 > duration:
                continue
            first = round((onset + local_start) * sample_hz)
            last = first + round(2 * sample_hz)
            if last > raw.n_times:
                raise ValueError("The source signal ends before a selected window")
            # MNE reads only this interval. No other block enters a resampling call.
            window = raw.get_data(picks=picks, start=first, stop=last)
            if window.shape != (len(picks), 2 * int(sample_hz)):
                raise ValueError("A source window has the wrong shape")
            if not np.isfinite(window).all():
                raise ValueError("A source window has non-finite values")
            if sample_hz != target_hz:
                window = resample_poly(window, up=1, down=int(sample_hz) // target_hz, axis=-1)
            if window.shape != (len(picks), 2 * target_hz):
                raise ValueError("A resampled window has the wrong shape")
            token = opaque(key, f"{split}:sub-02:{block_number}:{window_number}")
            output.append({
                "sort_key": opaque(key, "order:" + token),
                "id": token,
                "x": window.astype(np.float32),
                "label": PROTOCOL["condition_codes"][condition],
                "block": block_number,
                "window": window_number,
            })
            kept += 1
        if kept < PROTOCOL["window"]["minimum_complete_windows_per_block"]:
            raise ValueError(f"Film block {block_number} has too few complete guarded windows")
    return sorted(output, key=lambda row: row["sort_key"])


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        while chunk := input_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def code_hashes() -> dict[str, str]:
    return {name: sha256(path) for name, path in CODE_FILES.items()}


def bind_existing_receipt(out: Path) -> None:
    receipt_path = out / "private" / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    if receipt["source_commit"] != MANIFEST["dataset_git_commit"]:
        raise ValueError("The existing receipt has a different source commit")
    lineage = json.loads((out / "private" / "lineage.json").read_text())
    public = out / "public" / lineage["anonymous_subject"]
    for split in PUBLIC_SPLITS:
        if receipt["public"][split]["arrays_sha256"] != sha256(public / f"{split}.npz"):
            raise ValueError(f"The existing {split} array changed")
        if receipt["public"][split]["labels_sha256"] != sha256(public / f"{split}_labels.json"):
            raise ValueError(f"The existing {split} labels changed")
    receipt["code_sha256"] = code_hashes()
    write_json(receipt_path, receipt)
    print(json.dumps({"status": "existing_output_hashes_bound_to_current_code", "test_exported": False}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--shuffle-key-file", type=Path)
    parser.add_argument("--prepare-public", action="store_true")
    parser.add_argument("--bind-existing-receipt", action="store_true")
    args = parser.parse_args()
    if args.prepare_public and args.bind_existing_receipt:
        parser.error("Choose only one write mode")
    if args.bind_existing_receipt:
        bind_existing_receipt(args.out)
        return
    if not args.prepare_public:
        print(json.dumps({
            "status": "plan_only",
            "subject": "sub-02",
            "public_splits": list(PUBLIC_SPLITS),
            "test_export": "not_implemented",
            "source_root": str(args.source_root),
            "out": str(args.out),
        }, indent=2))
        return
    if args.shuffle_key_file is None:
        parser.error("--shuffle-key-file is required with --prepare-public")
    key = args.shuffle_key_file.read_bytes()
    if len(key) < 32:
        raise ValueError("The private shuffle key needs at least 32 bytes")
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError("The output directory must be new or empty")
    files = source_files(args.source_root)
    blocks = read_events(files["events"])
    picks, channel_types = read_good_channels(files["channels"])
    source_sidecar = json.loads(files["sidecar"].read_text())
    import mne  # Import after plan-only checks.
    raw = mne.io.read_raw_brainvision(files["header"], preload=False, verbose="ERROR")
    if raw.info["sfreq"] != source_sidecar["SamplingFrequency"]:
        raise ValueError("BrainVision and BIDS sampling rates disagree")
    if any(name not in raw.ch_names for name in picks):
        raise ValueError("A good BIDS channel is absent from the BrainVision header")
    anonymous_subject = opaque(key, "subject:sub-02")
    public = args.out / "public" / anonymous_subject
    private = args.out / "private"
    public.mkdir(parents=True)
    private.mkdir(parents=True)
    lineage = {"source_subject": "sub-02", "anonymous_subject": anonymous_subject, "splits": {}}
    receipts = {}
    for split in PUBLIC_SPLITS:
        rows = build_windows(raw, blocks, picks, key, split)
        array_path = public / f"{split}.npz"
        labels_path = public / f"{split}_labels.json"
        np.savez_compressed(
            array_path,
            x=np.stack([row["x"] for row in rows]),
            ids=np.array([row["id"] for row in rows]),
        )
        write_json(labels_path, {row["id"]: row["label"] for row in rows})
        lineage["splits"][split] = {
            row["id"]: {"block": row["block"], "window": row["window"]} for row in rows
        }
        receipts[split] = {
            "windows": len(rows),
            "arrays_sha256": sha256(array_path),
            "labels_sha256": sha256(labels_path),
        }
    write_json(public / "metadata.json", {
        "sampling_hz": PROTOCOL["window"]["processed_sampling_hz"],
        "window_seconds": 2,
        "channel_ids": [f"c{index:03d}" for index in range(len(picks))],
        "channel_types": channel_types,
        "label_codes": PROTOCOL["condition_codes"],
    })
    write_json(private / "lineage.json", lineage)
    write_json(private / "receipt.json", {
        "status": "representative_public_train_validation_only",
        "source_commit": MANIFEST["dataset_git_commit"],
        "source_subject": "sub-02",
        "source_sampling_hz": raw.info["sfreq"],
        "source_signal_sha256": sha256(files["signal"]),
        "good_intracranial_channels": len(picks),
        "public": receipts,
        "code_sha256": code_hashes(),
        "test_signal_windows_requested": 0,
        "test_exported": False,
        "task_runnable": False,
    })
    if any("test" in path.name for path in args.out.rglob("*")):
        raise RuntimeError("The public-only export unexpectedly contains a Test-named path")
    print(json.dumps({
        "status": "representative_public_train_validation_only",
        "anonymous_subject": anonymous_subject,
        "public_windows": {name: item["windows"] for name, item in receipts.items()},
        "good_intracranial_channels": len(picks),
        "test_signal_windows_requested": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
