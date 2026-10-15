#!/usr/bin/env python3
"""Build the six-file clinical film source inventory from the pinned Git tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = json.loads((ROOT / "cohort_inventory.json").read_text())
COMMIT = INVENTORY["source_git_commit"]
RAW = f"https://raw.githubusercontent.com/OpenNeuroDatasets/ds003688/{COMMIT}/"
TREE = f"https://api.github.com/repos/OpenNeuroDatasets/ds003688/git/trees/{COMMIT}?recursive=1"
S3 = "https://s3.amazonaws.com/openneuro.org/ds003688/"
POINTER = re.compile(rb"MD5E-s([0-9]+)--([a-f0-9]{32})")


def get(url: str) -> bytes:
    return subprocess.check_output(["curl", "-fsSL", "--retry", "8", "--retry-all-errors",
                                    "--retry-delay", "1", "--max-time", "45", url])


def git_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tree = json.loads(get(TREE))
    if tree.get("truncated"):
        raise ValueError("Pinned Git tree response is truncated")
    blobs = {item["path"]: item for item in tree["tree"] if item["type"] == "blob"}
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        if previous.get("source_git_commit") != COMMIT:
            raise ValueError("Existing output belongs to another Git commit")
        records = previous["records"]
    else:
        records = []
    completed = {record["subject"] for record in records}
    signal_total = 0
    for record in INVENTORY["records"]:
        subject = record["subject"]
        if subject in completed:
            signal_total += next(item for item in records if item["subject"] == subject)["files"]["signal"]["bytes"]
            continue
        files = {}
        paths = {role: record[role]["path"] for role in ("events", "channels", "sidecar")}
        signal = record["signal_pointer"]["path"]
        stem = signal.removesuffix(".eeg")
        paths.update(signal=signal, header=stem + ".vhdr", markers=stem + ".vmrk")
        for role, path in paths.items():
            blob = blobs.get(path)
            if blob is None:
                raise ValueError(f"Missing pinned Git path: {path}")
            original = record.get(role) if role in ("events", "channels", "sidecar") else (
                record["signal_pointer"] if role == "signal" else None)
            if original is not None and blob["sha"] != original["git_blob_sha1"]:
                raise ValueError(f"Pinned cohort inventory differs from Git tree: {path}")
            if role in ("signal", "header", "markers"):
                body = get(RAW + path)
                if git_sha(body) != blob["sha"]:
                    raise ValueError(f"Git blob differs from pinned tree: {path}")
                match = POINTER.search(body)
                if match is None:
                    raise ValueError(f"Expected annex pointer: {path}")
                size = int(match.group(1))
                files[role] = {"path": path, "bytes": size, "md5": match.group(2).decode(),
                               "git_pointer_sha1": blob["sha"], "url": S3 + path}
            else:
                size = blob["size"]
                files[role] = {"path": path, "bytes": size, "git_blob_sha1": blob["sha"],
                               "url": RAW + path}
        signal_total += files["signal"]["bytes"]
        records.append({"subject": subject, "clinical_run": record["selected_clinical_run"], "files": files})
        partial = {"schema": "bpb-ieeg-film-full-source/1", "task_id": "ieeg-film-speech-music",
                   "dataset_version": "ds003688-v1.0.7", "source_git_commit": COMMIT,
                   "selection": "One unique clinical film run for each of 51 source subjects. Excludes HDgrid playback, movie media, and fMRI.",
                   "signal_total_bytes": signal_total,
                   "all_source_total_bytes": sum(item["bytes"] for row in records for item in row["files"].values()),
                   "records": records}
        args.output.write_text(json.dumps(partial, indent=2) + "\n")
        print(json.dumps({"metadata_complete_subject": subject}), flush=True)
    total = sum(file["bytes"] for record in records for file in record["files"].values())
    result = {"schema": "bpb-ieeg-film-full-source/1", "task_id": "ieeg-film-speech-music",
              "dataset_version": "ds003688-v1.0.7", "source_git_commit": COMMIT,
              "selection": "One unique clinical film run for each of 51 source subjects. Excludes HDgrid playback, movie media, and fMRI.",
              "signal_total_bytes": signal_total, "all_source_total_bytes": total,
              "records": records}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"subjects": len(records), "signal_bytes": signal_total, "all_source_bytes": total}))


if __name__ == "__main__":
    main()
