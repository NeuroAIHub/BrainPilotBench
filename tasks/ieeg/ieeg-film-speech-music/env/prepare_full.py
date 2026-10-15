#!/usr/bin/env python3
"""Prepare isolated film windows from verified clinical sources for 51 subjects."""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
from pathlib import Path
import stat

import mne
import numpy as np
from scipy.signal import resample_poly

from fetch_full import SOURCE, ROLES, verify

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((ROOT / "protocol.json").read_text())
SPLITS = ("train", "validation", "test")
SAMPLE_HZ = 256
WINDOW_SAMPLES = 512


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def token(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:24]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def events(path: Path) -> list[tuple[float, float, int]]:
    with path.open(newline="") as stream:
        rows = [row for row in csv.DictReader(stream, delimiter="\t")
                if row["trial_type"] in ("speech", "music")]
    if len(rows) != 13:
        raise ValueError(f"Expected 13 speech/music events: {path}")
    result = []
    for index, row in enumerate(rows):
        name = PROTOCOL["expected_conditions"][index]
        onset, duration = float(row["onset"]), float(row["duration"])
        if row["trial_type"] != name or not 29 <= duration <= 31 or onset < 0:
            raise ValueError(f"Event {index + 1} differs from the frozen protocol: {path}")
        if index and abs(onset - sum(result[-1][:2])) > 0.25:
            raise ValueError(f"Event {index + 1} has a timing gap: {path}")
        result.append((onset, duration, PROTOCOL["condition_codes"][name]))
    return result


def good_channels(path: Path) -> tuple[list[str], list[str]]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    selected = [row for row in rows if row["type"].upper() in ("ECOG", "SEEG")
                and row["status"].lower() == "good"]
    names = [row["name"] for row in selected]
    if not names or len(names) != len(set(names)):
        raise ValueError(f"No unique good intracranial channels: {path}")
    return names, [row["type"].upper() for row in selected]


def extract(raw: mne.io.BaseRaw, picks: list[str], blocks, subject: str, key: bytes, split: str):
    source_hz = int(raw.info["sfreq"])
    if source_hz != raw.info["sfreq"] or source_hz not in (256, 512, 1024, 2048):
        raise ValueError(f"Unsupported clinical sample rate for {subject}: {raw.info['sfreq']}")
    rows = []
    counts = {}
    for block_number in PROTOCOL["block_assignment"][split]:
        onset, duration, label = blocks[block_number - 1]
        kept = 0
        for local_start in PROTOCOL["window"]["local_start_seconds"]:
            if local_start < 2 or local_start + 4 > duration:
                continue
            first = round((onset + local_start) * source_hz)
            last = first + 2 * source_hz
            if last > raw.n_times:
                raise ValueError(f"Source ends before a guarded window for {subject}")
            window = raw.get_data(picks=picks, start=first, stop=last)
            if window.shape != (len(picks), source_hz * 2) or not np.isfinite(window).all():
                raise ValueError(f"Invalid source window for {subject}")
            if source_hz != SAMPLE_HZ:
                window = resample_poly(window, 1, source_hz // SAMPLE_HZ, axis=1)
            if window.shape != (len(picks), WINDOW_SAMPLES) or not np.isfinite(window).all():
                raise ValueError(f"Invalid processed window for {subject}")
            identifier = token(key, f"window:{subject}:{block_number}:{local_start}")
            rows.append({"id": identifier, "order": token(key, "order:" + identifier),
                         "x": window.astype(np.float32), "label": label,
                         "block": block_number, "local_start": local_start})
            kept += 1
        if kept < PROTOCOL["window"]["minimum_complete_windows_per_block"]:
            raise ValueError(f"Block {block_number} has fewer than 12 guarded windows for {subject}")
        counts[str(block_number)] = kept
    return sorted(rows, key=lambda row: row["order"]), counts


def save_split(directory: Path, split: str, rows, channel_types: list[str]) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    array = directory / f"{split}.npz"
    labels = directory / f"{split}_labels.json"
    x = np.stack([row["x"] for row in rows])
    ids = np.array([row["id"] for row in rows])
    np.savez_compressed(array, x=x, ids=ids)
    write_json(labels, {row["id"]: row["label"] for row in rows})
    return {"arrays": {"path": array.name, "bytes": array.stat().st_size, "sha256": sha256(array),
                        "shape": list(x.shape), "dtype": str(x.dtype)},
            "labels": {"path": labels.name, "bytes": labels.stat().st_size, "sha256": sha256(labels)},
            "window_count": len(rows), "channel_count": len(channel_types),
            "opaque_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--shuffle-key-file", required=True, type=Path)
    parser.add_argument("--owner-test-export", action="store_true")
    args = parser.parse_args()
    if (args.shuffle_key_file.is_symlink() or
            args.shuffle_key_file.resolve().is_relative_to(ROOT.parents[2].resolve()) or
            stat.S_IMODE(args.shuffle_key_file.stat().st_mode) & 0o077):
        raise ValueError("The private shuffle key must be outside Git with owner-only permissions")
    key = args.shuffle_key_file.read_bytes()
    if len(key) < 32:
        raise ValueError("Private shuffle key must contain at least 32 bytes")
    if args.data_root.resolve().is_relative_to(ROOT.parents[2].resolve()):
        raise ValueError("The data root must be outside the Git checkout")
    source_receipt = json.loads((args.data_root / "source_receipt.json").read_text())
    expected_paths = {spec["path"] for record in SOURCE["records"] for spec in record["files"].values()}
    if set(source_receipt["files"]) != expected_paths:
        raise ValueError("Full source receipt is incomplete")
    derived = args.data_root / "derived-v2"
    if derived.exists() and any(derived.iterdir()):
        raise ValueError("Derived-v2 destination must be new or empty")
    public = derived / "public"
    owner = derived / "owner"
    owner.mkdir(parents=True, mode=0o700)
    owner.chmod(0o700)
    if args.owner_test_export:
        (owner / "test").mkdir(mode=0o700)
    roles = {split: [] for split in SPLITS if split != "test" or args.owner_test_export}
    lineage = {"schema": "bpb-ieeg-film-lineage/2", "subjects": {}}
    qc = {"eligible": [], "excluded": []}
    max_channels = 0
    for record in SOURCE["records"]:
        subject = record["subject"]
        opaque_subject = token(key, "subject:" + subject)
        files = {role: args.data_root / "source" / record["files"][role]["path"] for role in ROLES}
        for role in ROLES:
            digest = verify(files[role], record["files"][role])
            if source_receipt["files"][record["files"][role]["path"]]["sha256"] != digest:
                raise ValueError(f"Source SHA256 differs from verified receipt: {subject}, {role}")
        try:
            blocks = events(files["events"])
            names, types = good_channels(files["channels"])
            sidecar = json.loads(files["sidecar"].read_text())
            raw = mne.io.read_raw_brainvision(files["header"], preload=False, verbose="ERROR")
            if raw.info["sfreq"] != sidecar["SamplingFrequency"] or any(name not in raw.ch_names for name in names):
                raise ValueError("BrainVision header differs from BIDS channel or sample metadata")
            subject_lineage = {"source_subject": subject, "clinical_run": record["clinical_run"],
                               "split_windows": {}}
            prepared = {}
            for split in roles:
                rows, counts = extract(raw, names, blocks, subject, key, split)
                prepared[split] = (rows, counts)
            for split, (rows, counts) in prepared.items():
                destination = (owner / "test" if split == "test" else public) / opaque_subject
                file_record = save_split(destination, split, rows, types)
                if split == "test":
                    destination.chmod(0o700)
                    (destination / file_record["arrays"]["path"]).chmod(0o600)
                    (destination / file_record["labels"]["path"]).chmod(0o600)
                if split != "test":
                    metadata_path = destination / "metadata.json"
                    write_json(metadata_path, {
                        "sampling_hz": SAMPLE_HZ, "window_seconds": 2,
                        "channel_ids": [f"c{i:03d}" for i in range(len(types))],
                        "channel_types": types, "label_codes": PROTOCOL["condition_codes"],
                        "subject_id": opaque_subject})
                    file_record["metadata"] = {"path": "metadata.json", "bytes": metadata_path.stat().st_size,
                                               "sha256": sha256(metadata_path)}
                roles[split].append({"subject_id": opaque_subject, "files": file_record})
                subject_lineage["split_windows"][split] = {
                    row["id"]: {"block": row["block"], "local_start": row["local_start"],
                                "label": row["label"]} for row in rows}
                subject_lineage["split_windows"][split + "_block_counts"] = counts
            lineage["subjects"][opaque_subject] = subject_lineage
            max_channels = max(max_channels, len(types))
            qc["eligible"].append({"subject": subject, "good_channels": len(types),
                                   "source_sampling_hz": raw.info["sfreq"]})
            print(json.dumps({"eligible_subject": subject, "good_channels": len(types)}), flush=True)
        except (ValueError, RuntimeError, OSError) as error:
            if (public / opaque_subject).exists() or (owner / "test" / opaque_subject).exists():
                raise RuntimeError(f"Partial derived output requires operator review for {subject}") from error
            qc["excluded"].append({"subject": subject, "reason": str(error)})
            print(json.dumps({"excluded_subject": subject, "reason": str(error)}), flush=True)
    if not qc["eligible"]:
        raise ValueError("No eligible participants")
    write_json(owner / "lineage.json", lineage)
    write_json(owner / "qc.json", qc)
    (owner / "lineage.json").chmod(0o600)
    (owner / "qc.json").chmod(0o600)
    manifests = {}
    for split, subjects in roles.items():
        subjects.sort(key=lambda item: item["subject_id"])
        path = (owner if split == "test" else public) / f"{split}_manifest.json"
        write_json(path, {"schema": "bpb-ieeg-film-derived-role/2", "role": split,
                          "protocol_version": PROTOCOL["protocol_version"], "subjects": subjects})
        if split == "test":
            path.chmod(0o600)
        manifests[split] = {"path": str(path.relative_to(derived)), "bytes": path.stat().st_size,
                            "sha256": sha256(path), "subjects": len(subjects)}
    common = {"schema": "bpb-ieeg-film-common-contract/2", "task_id": PROTOCOL["task_id"],
              "protocol_sha256": sha256(ROOT / "protocol.json"),
              "source_manifest_sha256": sha256(ROOT / "full_source_manifest.json"),
              "cohort_inventory_sha256": sha256(ROOT / "cohort_inventory.json"),
              "source_metadata_sha256": sha256(ROOT / "source_manifest.json"),
              "preparation_code_sha256": sha256(Path(__file__).resolve()),
              "source_receipt_sha256": sha256(args.data_root / "source_receipt.json"),
              "roles": manifests, "lineage_sha256": sha256(owner / "lineage.json"),
              "qc_sha256": sha256(owner / "qc.json"), "eligible_subjects": len(qc["eligible"]),
              "excluded_subjects": len(qc["excluded"]), "maximum_good_channels": max_channels,
              "test_exported": args.owner_test_export}
    write_json(owner / "common_contract.json", common)
    (owner / "common_contract.json").chmod(0o600)
    print(json.dumps({"status": "full_source_derived_roles_bound", "eligible": len(qc["eligible"]),
                      "excluded": len(qc["excluded"]), "maximum_good_channels": max_channels,
                      "test_exported": args.owner_test_export}, indent=2))


if __name__ == "__main__":
    main()
