"""Offline consistency check for frozen source assets and five candidate protocols."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re

from make_manifest import SOURCES, SOURCE_SHA


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "_preparation" / "assets.manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    count = validate_manifest(manifest)
    validate_protocol_files(manifest)
    print(f"Validated {len(SOURCES)} protocols and {count} frozen asset records; no data files opened")


def validate_manifest(manifest: dict) -> int:
    """Pure metadata validation; no network, file I/O, or mutation."""
    if (manifest.get("schema") != "bpb-falcon-public-asset-manifest/1"
            or manifest.get("upstream_source_sha") != SOURCE_SHA
            or manifest.get("profile") != "bpb-falcon-public-derived-cross-session-zs-v1"):
        raise ValueError("Manifest source or schema mismatch")
    ids = set()
    dates = defaultdict(lambda: defaultdict(set))
    sizes = defaultdict(lambda: defaultdict(int))
    content_roles = {}
    for asset in manifest["assets"]:
        task = asset["task_id"]
        if task not in SOURCES or asset["asset_id"] in ids:
            raise ValueError("Unknown task or duplicate asset ID")
        ids.add(asset["asset_id"])
        source_task, dandiset, version, _, date_regex, _ = SOURCES[task]
        if (asset["source_task_id"], asset["dandiset_id"], asset["version"]) != (source_task, dandiset, version):
            raise ValueError("Source binding mismatch")
        if asset["size_bytes"] <= 0 or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
            raise ValueError("Missing immutable size or SHA-256")
        if "minival" in asset["path"] or "http" in asset["path"]:
            raise ValueError("Duplicate minival or URL in selected asset")
        parsed_date = re.search(date_regex, asset["path"])
        if parsed_date is None or parsed_date.group(1) != asset["session_date"]:
            raise ValueError("Asset path/date mismatch")
        if asset["role"] not in ("train", "valid", "test"):
            raise ValueError("Unknown asset role")
        if asset["role"] in ("train", "valid") and "held-in-calib" not in asset["path"]:
            raise ValueError("Public role sourced outside held-in calibration")
        if asset["role"] == "test" and "held-out-calib" not in asset["path"]:
            raise ValueError("Test role sourced outside held-out calibration")
        content_key = (task, asset["sha256"])
        if content_key in content_roles and content_roles[content_key] != asset["role"]:
            raise ValueError("Same source content assigned to multiple roles")
        content_roles[content_key] = asset["role"]
        dates[task][asset["role"]].add(asset["session_date"])
        sizes[task][asset["role"]] += asset["size_bytes"]
    if set(manifest["sources"]) != set(SOURCES):
        raise ValueError("Manifest source task set changed")
    for task, (source_task, dandiset, version, valid_date, _, expected) in SOURCES.items():
        source = manifest["sources"][task]
        if (source["dandiset_id"], source["version"], source["valid_date"]) != (dandiset, version, valid_date):
            raise ValueError(f"Source summary changed for {task}")
        if source["version_kind"] != ("published" if version != "draft" else "mutable_draft_asset_snapshot"):
            raise ValueError(f"Version kind changed for {task}")
        for role in ("train", "valid", "test"):
            if sorted(dates[task][role]) != source["dates"][role]:
                raise ValueError(f"Summary dates differ for {task}/{role}")
            if sizes[task][role] != source["bytes_by_role"][role]:
                raise ValueError(f"Summary bytes differ for {task}/{role}")
        if tuple(len(dates[task][role]) for role in ("train", "valid", "test")) != expected:
            raise ValueError(f"Wrong date counts for {task}")
        if any(dates[task][left] & dates[task][right]
               for left, right in (("train", "valid"), ("train", "test"), ("valid", "test"))):
            raise ValueError(f"Date overlap for {task}")
    return len(ids)


def validate_protocol_files(manifest: dict) -> None:
    """Bind source metadata to the H1 runtime or the remaining candidate protocols."""
    for task in SOURCES:
        protocol = json.loads((ROOT / task / "protocol.json").read_text())
        if (ROOT / task / "task.yaml").is_file():
            if (ROOT / task / "candidate.json").exists():
                raise ValueError(f"{task} cannot be both a candidate and a runnable task")
            contract = json.loads((ROOT / task / "contract.json").read_text())
            expected_schema = ("bpb-h1-contract/1" if task == "falcon-h1-reach-grasp" else
                               "bpb-falcon-regression-contract/1" if task in ("falcon-m1-emg", "falcon-m2-finger-velocity") else
                               "bpb-falcon-sequence-contract/1")
            expected_version = "0.1-public-validation-motif" if task == "falcon-b1-birdsong" else "0.1-public-validation-stream"
            if (contract.get("schema") != expected_schema or contract.get("task_id") != task
                    or contract.get("science_profile") != manifest["profile"]
                    or contract.get("task_version") != expected_version):
                raise ValueError(f"{task} runtime contract does not match the frozen source profile")
        else:
            candidate = json.loads((ROOT / task / "candidate.json").read_text())
            if candidate["schema"] != "bpb-invasive-candidate/1" or candidate["id"] != task:
                raise ValueError(f"Invalid candidate {task}")
            if (candidate["status"] != "preparation_ready_data_pending" or candidate["runnable"] is not False
                    or candidate["protocol"] != "protocol.json"
                    or candidate["preparation_entry"] != "tasks/intracortical/_preparation/prepare.py"):
                raise ValueError(f"Incorrect preparation binding for {task}")
        if (protocol["source"]["sha"] != SOURCE_SHA or protocol["task_id"] != task
                or protocol["profile"] != manifest["profile"]):
            raise ValueError(f"Invalid protocol source for {task}")
        for role in ("train", "valid", "test"):
            if manifest["sources"][task]["dates"][role] != protocol["split"][f"{role}_dates"]:
                raise ValueError(f"Protocol/manifest dates differ for {task}/{role}")


if __name__ == "__main__":
    main()
