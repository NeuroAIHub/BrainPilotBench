#!/usr/bin/env python3
"""Recompute Valid block-first macro accuracy from a frozen owner audit."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import stat

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    owner = args.data_root / "derived-v2" / "owner"
    for path in (args.audit, args.report):
        if (path.is_symlink() or not path.resolve().is_relative_to(owner.resolve())
                or stat.S_IMODE(path.stat().st_mode) != 0o600):
            raise ValueError("Valid audit and report must be owner-only files")
    contract = read(ROOT / "contract.json")
    if contract != read(owner / "common_contract.json"):
        raise ValueError("Owner and tracked contracts differ")
    audit, report = read(args.audit), read(args.report)
    manifest_spec = contract["roles"]["validation"]
    manifest_path = args.data_root / "derived-v2" / manifest_spec["path"]
    if (digest(manifest_path) != manifest_spec["sha256"] or
            digest(args.audit) != report["owner_audit_sha256"] or
            audit["contract_sha256"] != digest(ROOT / "contract.json") or
            audit["manifest_sha256"] != manifest_spec["sha256"] or
            report["manifest_sha256"] != manifest_spec["sha256"] or
            audit["submission_sha256"] != report["submission_sha256"] or
            audit["schema"] != "bpb-ieeg-film-valid-predictions/1" or
            report["role"] != "validation"):
        raise ValueError("Valid audit, report, manifest, or submission binding differs")
    manifest = read(manifest_path)
    lineage = read(owner / "lineage.json")
    predictions = audit["predictions"]
    seen = set()
    per_subject = []
    per_block = defaultdict(list)
    for subject in manifest["subjects"]:
        identifier = subject["subject_id"]
        directory = args.data_root / "derived-v2" / "public" / identifier
        array_spec = subject["files"]["arrays"]
        label_spec = subject["files"]["labels"]
        array = directory / array_spec["path"]
        labels_path = directory / label_spec["path"]
        if digest(array) != array_spec["sha256"] or digest(labels_path) != label_spec["sha256"]:
            raise ValueError("Valid arrays or labels differ from role manifest")
        with np.load(array, allow_pickle=False) as data:
            ids = data["ids"].tolist()
        labels = read(labels_path)
        mapping = lineage["subjects"][identifier]["split_windows"]["validation"]
        if set(ids) != set(labels) or set(ids) != set(mapping) or len(ids) not in (24, 25, 26):
            raise ValueError("Valid window IDs, labels, or count differ")
        blocks = defaultdict(list)
        for window_id in ids:
            if window_id in seen:
                raise ValueError("Valid window ID repeats across subjects")
            seen.add(window_id)
            probability = predictions[window_id]
            if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("Audit contains an invalid probability")
            hidden = mapping[window_id]
            if labels[window_id] != hidden["label"] or hidden["block"] not in (4, 11):
                raise ValueError("Valid label or block differs from hidden mapping")
            blocks[hidden["block"]].append((probability, hidden["label"]))
        if set(blocks) != {4, 11} or any(not 12 <= len(rows) <= 13 for rows in blocks.values()):
            raise ValueError("Valid subject lacks two complete guarded blocks")
        hits = []
        for block in (4, 11):
            rows = blocks[block]
            if len({label for _, label in rows}) != 1:
                raise ValueError("Valid block contains mixed labels")
            label = rows[0][1]
            hit = int((sum(value for value, _ in rows) / len(rows) >= 0.5) == label)
            hits.append(hit)
            per_block[block].append(hit)
        per_subject.append(sum(hits) / 2)
    if set(predictions) != seen:
        raise ValueError("Valid audit has missing or extra window IDs")
    value = sum(per_subject) / len(per_subject)
    independent_blocks = {str(block): sum(values) / len(values) for block, values in per_block.items()}
    if (not math.isclose(value, report["value"], rel_tol=0, abs_tol=1e-12) or
            report["participants"] != len(per_subject) or report["windows"] != len(seen) or
            any(not math.isclose(result, report["per_block_accuracy"][block], rel_tol=0, abs_tol=1e-12)
                for block, result in independent_blocks.items())):
        raise ValueError("Independent Valid metric differs from the runner report")
    print(json.dumps({"status": "independent_valid_block_first_macro_matches",
                      "balanced_accuracy": value, "participants": len(per_subject),
                      "windows": len(seen), "audit_sha256": digest(args.audit)}, indent=2))


if __name__ == "__main__":
    main()
