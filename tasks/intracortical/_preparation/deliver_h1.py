"""Record H1's complete, role-separated public-data delivery without NWB reads.

Only file bytes are streamed to verify size and SHA-256. No target, mask, neural
array, Test prediction, or model is read or computed by this script.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

import prepare


TASK = "falcon-h1-reach-grasp"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    destination = prepare.safe_destination(args.dest)
    public_root = (destination / "public").resolve()
    evaluator_root = (destination / "evaluator").resolve()
    if public_root == evaluator_root or public_root.is_relative_to(evaluator_root) or evaluator_root.is_relative_to(public_root):
        raise ValueError("Public and evaluator data roots must be separate")
    if stat.S_IMODE(evaluator_root.stat().st_mode) != 0o700:
        raise ValueError("Evaluator root must have mode 0700")
    manifest = prepare.load_manifest()
    role_counts = {role: 0 for role in ("train", "valid", "test")}
    role_bytes = {role: 0 for role in role_counts}
    role_dates = {role: set() for role in role_counts}
    verified_assets = []
    for asset in (a for a in manifest["assets"] if a["task_id"] == TASK):
        root = evaluator_root if asset["role"] == "test" else public_root
        path = prepare.file_path(root, asset)
        prepare.verify_one(path, asset)
        actual_sha = sha256_file(path)
        if actual_sha != asset["sha256"]:
            raise ValueError(f"Digest changed during receipt: {asset['asset_id']}")
        role = asset["role"]
        role_counts[role] += 1
        role_bytes[role] += path.stat().st_size
        role_dates[role].add(asset["session_date"])
        verified_assets.append({"role": role, "date": asset["session_date"], "asset_id": asset["asset_id"],
                                "path": str(path), "bytes": asset["size_bytes"], "actual_sha256": actual_sha})
    if role_counts != {"train": 11, "valid": 2, "test": 14}:
        raise ValueError(f"Incomplete H1 asset set: {role_counts}")
    if {role: len(days) for role, days in role_dates.items()} != {"train": 5, "valid": 1, "test": 7}:
        raise ValueError("H1 date role counts changed")
    if role_bytes != manifest["sources"][TASK]["bytes_by_role"]:
        raise ValueError("H1 delivered bytes differ from manifest")
    receipt = {
        "schema": "bpb-intracortical-split-delivery/1",
        "task_id": TASK,
        "profile": manifest["profile"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha": manifest["upstream_source_sha"],
        "manifest_sha256": sha256_file(prepare.MANIFEST),
        "public_root": str(public_root),
        "evaluator_root": str(evaluator_root),
        "evaluator_root_mode": "0700",
        "files_by_role": role_counts,
        "dates_by_role": {role: sorted(days) for role, days in role_dates.items()},
        "bytes_by_role": role_bytes,
        "assets": verified_assets,
        "native_nwb_retained": True,
        "source_data_public": True,
        "test_arrays_or_labels_read": False,
        "test_scores_not_computed": True,
        "official_falcon_score": False,
        "runtime_isolation_accepted": False,
        "agent_package_published": False,
    }
    receipt_dir = destination / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(receipt_dir, 0o700)
    path = receipt_dir / f"h1-split-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with path.open("x") as output:
        json.dump(receipt, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps({"receipt": str(path), "date_counts": {role: len(days) for role, days in role_dates.items()},
                      "files_by_role": role_counts, "bytes_by_role": role_bytes,
                      "test_scores_not_computed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
