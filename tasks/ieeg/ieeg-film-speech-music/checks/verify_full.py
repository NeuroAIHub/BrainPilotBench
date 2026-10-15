#!/usr/bin/env python3
"""Verify source and derived role hashes, shapes, labels, and guarded windows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "env"))
from fetch_full import SOURCE, verify  # noqa: E402
from run import bound, sha256, strict_json  # noqa: E402

PROTOCOL = json.loads((ROOT / "protocol.json").read_text())


def inspect(data_root: Path):
    receipt_path = data_root / "source_receipt.json"
    receipt = strict_json(receipt_path)
    expected = {spec["path"] for record in SOURCE["records"] for spec in record["files"].values()}
    if set(receipt["files"]) != expected:
        raise ValueError("Source receipt does not cover all six files for 51 subjects")
    for record in SOURCE["records"]:
        for spec in record["files"].values():
            path = data_root / "source" / spec["path"]
            digest = verify(path, spec)
            if receipt["files"][spec["path"]] != {"bytes": spec["bytes"], "sha256": digest}:
                raise ValueError("Source receipt differs from native-verified bytes")
    derived = data_root / "derived-v2"
    owner = derived / "owner"
    if stat.S_IMODE(owner.stat().st_mode) != 0o700:
        raise ValueError("Owner directory must have mode 0700")
    common = strict_json(owner / "common_contract.json")
    if strict_json(ROOT / "contract.json") != common:
        raise ValueError("Owner common contract differs from tracked contract")
    if common["schema"] != "bpb-ieeg-film-common-contract/2" or not common["test_exported"]:
        raise ValueError("Owner contract does not bind all roles")
    if (common["source_manifest_sha256"] != sha256(ROOT / "full_source_manifest.json")
            or common["cohort_inventory_sha256"] != sha256(ROOT / "cohort_inventory.json")
            or common["source_metadata_sha256"] != sha256(ROOT / "source_manifest.json")
            or common["protocol_sha256"] != sha256(ROOT / "protocol.json")
            or common["preparation_code_sha256"] != sha256(ROOT / "env" / "prepare_full.py")
            or common["source_receipt_sha256"] != sha256(receipt_path)
            or common["lineage_sha256"] != sha256(owner / "lineage.json")
            or common["qc_sha256"] != sha256(owner / "qc.json")):
        raise ValueError("Common contract differs from source, protocol, or hidden mapping")
    lineage = strict_json(owner / "lineage.json")
    qc = strict_json(owner / "qc.json")
    if len(qc["eligible"]) != common["eligible_subjects"] or len(qc["excluded"]) != common["excluded_subjects"]:
        raise ValueError("QC counts differ from common contract")
    if len(qc["eligible"]) + len(qc["excluded"]) != 51:
        raise ValueError("QC does not account for every source subject")
    counts = {}
    subject_sets = {}
    for role in ("train", "validation", "test"):
        manifest_spec = common["roles"][role]
        manifest_path = derived / manifest_spec["path"]
        bound(manifest_path, manifest_spec, 200_000)
        manifest = strict_json(manifest_path)
        if manifest["role"] != role or manifest["protocol_version"] != PROTOCOL["protocol_version"]:
            raise ValueError("Role manifest differs from protocol")
        subjects = set()
        count = 0
        for record in manifest["subjects"]:
            subject_id = record["subject_id"]
            if subject_id in subjects or subject_id not in lineage["subjects"]:
                raise ValueError("Repeated or unknown opaque subject")
            subjects.add(subject_id)
            directory = (owner / "test" if role == "test" else derived / "public") / subject_id
            if role == "test" and stat.S_IMODE(directory.stat().st_mode) != 0o700:
                raise ValueError("Test subject directory must have mode 0700")
            array_spec = record["files"]["arrays"]
            label_spec = record["files"]["labels"]
            array_path = directory / array_spec["path"]
            label_path = directory / label_spec["path"]
            bound(array_path, array_spec, 200_000_000)
            bound(label_path, label_spec, 100_000)
            if role != "test":
                metadata_spec = record["files"]["metadata"]
                metadata_path = directory / metadata_spec["path"]
                bound(metadata_path, metadata_spec, 100_000)
                metadata = strict_json(metadata_path)
                if (metadata["subject_id"] != subject_id or metadata["sampling_hz"] != 256
                        or metadata["window_seconds"] != 2
                        or len(metadata["channel_ids"]) != record["files"]["channel_count"]):
                    raise ValueError("Public channel metadata differs from role manifest")
            if role == "test" and (stat.S_IMODE(array_path.stat().st_mode) != 0o600 or
                                   stat.S_IMODE(label_path.stat().st_mode) != 0o600):
                raise ValueError("Test arrays and labels must have mode 0600")
            with np.load(array_path, allow_pickle=False) as data:
                if set(data.files) != {"x", "ids"}:
                    raise ValueError("Unexpected array fields")
                x, ids = data["x"], data["ids"].tolist()
            labels = strict_json(label_path)
            hidden = lineage["subjects"][subject_id]["split_windows"][role]
            block_counts = lineage["subjects"][subject_id]["split_windows"][role + "_block_counts"]
            if (list(x.shape) != array_spec["shape"] or str(x.dtype) != "float32"
                    or x.shape[2] != 512 or not np.isfinite(x).all()
                    or len(ids) != len(set(ids)) or set(ids) != set(labels) or set(ids) != set(hidden)):
                raise ValueError("Array dimensions, finite values, labels, or hidden IDs differ")
            if len(ids) != sum(block_counts.values()):
                raise ValueError("Hidden block counts differ from array rows")
            if set(map(int, block_counts)) != set(PROTOCOL["block_assignment"][role]):
                raise ValueError("Hidden blocks differ from frozen split")
            if any(not 12 <= value <= 13 for value in block_counts.values()):
                raise ValueError("A block lacks the required 12 to 13 complete windows")
            for identifier in ids:
                location = hidden[identifier]
                block = location["block"]
                if (labels[identifier] != location["label"]
                        or location["label"] != PROTOCOL["condition_codes"][PROTOCOL["expected_conditions"][block - 1]]
                        or location["local_start"] not in PROTOCOL["window"]["local_start_seconds"]):
                    raise ValueError("Hidden label or window differs from protocol")
            count += len(ids)
        counts[role] = count
        subject_sets[role] = subjects
    if subject_sets["train"] != subject_sets["validation"] or subject_sets["train"] != subject_sets["test"]:
        raise ValueError("Role participant sets differ")
    return {"status": "all_source_and_derived_roles_verified", "source_files": len(expected),
            "eligible_subjects": len(subject_sets["train"]), "excluded_subjects": len(qc["excluded"]),
            "windows": counts, "test_model_inference": False, "test_labels_printed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.data_root), indent=2))


if __name__ == "__main__":
    main()
