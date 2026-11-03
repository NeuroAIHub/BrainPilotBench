"""Exact hosted transport for accepted SAM2Mice scientific packets."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import stat

TASK_ID = "sam2mice-multi-animal-tracking"
REPOS = {"public": "BrainPilot-Bench/Tasks-Data-Public",
         "private": "BrainPilot-Bench/Tasks-Data-Private"}
SOURCE_AVAILABILITY = b"data_availability: source-verified-local-only\n"
HOSTED_AVAILABILITY = b"data_availability: published-public-and-private-snapshots\n"


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _read(path: Path) -> bytes:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("tracking delivery path contains a symlink")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4_000_000:
        raise ValueError("bounded independent tracking metadata required")
    return path.read_bytes()


def transport_metadata(task_dir: Path, contract: dict, source_data: dict,
                       source_evaluator: dict) -> tuple[dict, dict]:
    """Select source locks or byte-identical files at verified pinned destinations."""
    sidecar = task_dir / "hf-delivery.json"
    if not sidecar.exists() and not sidecar.is_symlink():
        return source_data, source_evaluator

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate tracking delivery key")
            result[key] = value
        return result

    card = json.loads(_read(sidecar), object_pairs_hook=unique)
    if (not isinstance(card, dict) or card.get("schema") != "bpb-mouse-hf-delivery/1"
            or card.get("task_id") != TASK_ID or contract.get("task_id") != TASK_ID
            or card.get("content_revision") != contract["revision"]
            or card.get("transport_only") is not True):
        raise ValueError("invalid tracking delivery identity")
    source_bindings = card.get("source_bindings", {})
    if set(source_bindings) != {"contract.json", "task.yaml", "data.lock", "evaluator.lock"}:
        raise ValueError("exact tracking source bindings required")
    for name, value in (("data.lock", source_data), ("evaluator.lock", source_evaluator)):
        if source_bindings[name] != hashlib.sha256(encoded(value)).hexdigest():
            raise ValueError("tracking source lock differs from scientific content")
    if source_bindings["contract.json"] != hashlib.sha256(_read(task_dir / "contract.json")).hexdigest():
        raise ValueError("tracking scientific contract changed")
    task_bytes = _read(task_dir / "task.yaml")
    if task_bytes.count(HOSTED_AVAILABILITY) != 1 or SOURCE_AVAILABILITY in task_bytes:
        raise ValueError("tracking hosted availability metadata differs")
    original = task_bytes.replace(HOSTED_AVAILABILITY, SOURCE_AVAILABILITY)
    if hashlib.sha256(original).hexdigest() != source_bindings["task.yaml"]:
        raise ValueError("tracking task changed beyond the availability field")
    hosted_bindings = card.get("hosted_bindings", {})
    if set(hosted_bindings) != {"data.lock", "evaluator.lock", "task.yaml"}:
        raise ValueError("exact tracking hosted bindings required")
    if hashlib.sha256(task_bytes).hexdigest() != hosted_bindings["task.yaml"]:
        raise ValueError("tracking hosted task binding differs")
    data, evaluator = copy.deepcopy(source_data), copy.deepcopy(source_evaluator)
    for role in ("public", "private"):
        hosted = card.get(role)
        if (not isinstance(hosted, dict) or set(hosted) != {"repo_id", "revision"}
                or hosted["repo_id"] != REPOS[role]
                or not isinstance(hosted["revision"], str)
                or not re.fullmatch("[0-9a-f]{40}", hosted["revision"])):
            raise ValueError("both exact pinned tracking HF destinations are required")
        packet_role = "public" if role == "public" else "evaluator"
        prefix = f"local://tasks/animal-behavior/{TASK_ID}/{contract['revision']}/{packet_role}/"
        for entry in data["datasets"]:
            if entry["scope"] != role:
                continue
            if not entry["uri"].startswith(prefix):
                raise ValueError("tracking source URI differs from scientific content")
            native = entry["uri"][len(prefix):]
            entry["uri"] = (f"hf://datasets/{hosted['repo_id']}@{hosted['revision']}/"
                            f"tasks/animal-behavior/{TASK_ID}/{packet_role}/{native}")
        if role == "private":
            evaluator.update(schema="bpb-evaluator-data/1", repo_id=hosted["repo_id"], revision=hosted["revision"])
    for name, value in (("data.lock", data), ("evaluator.lock", evaluator)):
        if hosted_bindings[name] != hashlib.sha256(encoded(value)).hexdigest():
            raise ValueError("tracking hosted bindings differ from exact expected transport")
    return data, evaluator
