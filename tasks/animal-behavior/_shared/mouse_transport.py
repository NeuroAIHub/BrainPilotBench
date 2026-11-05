"""Validate optional hosted transport without changing scientific packet identity."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import stat

REPOS = {"public": "BrainPilot-Bench/Tasks-Data-Public",
         "private": "BrainPilot-Bench/Tasks-Data-Private"}


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _read(path: Path) -> bytes:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("delivery metadata cannot contain a symlink")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("delivery metadata requires an independent regular file")
    return path.read_bytes()


def transport_metadata(task_dir: Path, contract: dict, source_data: dict,
                       source_evaluator: dict) -> tuple[dict, dict]:
    """Return exact expected locks for the source or receipt-bound HF transport."""
    sidecar = task_dir / "hf-delivery.json"
    if not sidecar.exists() and not sidecar.is_symlink():
        return source_data, source_evaluator
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate mouse delivery metadata key")
            value[key] = item
        return value
    card = json.loads(_read(sidecar), object_pairs_hook=unique)
    if not isinstance(card, dict):
        raise ValueError("mouse delivery metadata must be an object")
    if (card.get("schema") != "bpb-mouse-hf-delivery/1"
            or card.get("task_id") != contract["task_id"]
            or card.get("content_revision") != contract["revision"]
            or card.get("transport_only") is not True):
        raise ValueError("invalid mouse HF delivery identity")
    for name, value in (("data.lock", source_data), ("evaluator.lock", source_evaluator)):
        if card.get("source_bindings", {}).get(name) != hashlib.sha256(encoded(value)).hexdigest():
            raise ValueError("delivery source bindings differ from scientific contract")
    for name in ("contract.json", "task.yaml"):
        if card.get("source_bindings", {}).get(name) != hashlib.sha256(_read(task_dir / name)).hexdigest():
            raise ValueError("delivery changes the accepted task contract")
    data, evaluator = copy.deepcopy(source_data), copy.deepcopy(source_evaluator)
    used = False
    for role in ("public", "private"):
        hosted = card.get(role)
        if hosted is None:
            continue
        used = True
        if (not isinstance(hosted, dict) or set(hosted) != {"repo_id", "revision"}
                or hosted["repo_id"] != REPOS[role]
                or not re.fullmatch("[0-9a-f]{40}", hosted["revision"])):
            raise ValueError("invalid pinned mouse HF destination")
        for entry in data["datasets"]:
            if entry["scope"] != role:
                continue
            packet_role = "public" if role == "public" else "evaluator"
            prefix = f"local://tasks/animal-behavior/{contract['task_id']}/{contract['revision']}/{packet_role}/"
            if not entry["uri"].startswith(prefix):
                raise ValueError("source URI differs from scientific contract")
            native = entry["uri"][len(prefix):]
            remote = native.removeprefix("public/") if role == "public" else native
            entry["uri"] = (f"hf://datasets/{hosted['repo_id']}@{hosted['revision']}/"
                            f"tasks/animal-behavior/{contract['task_id']}/{packet_role}/{remote}")
        if role == "private":
            evaluator.update(schema="bpb-evaluator-data/1", repo_id=hosted["repo_id"],
                             revision=hosted["revision"])
    if not used:
        raise ValueError("empty mouse HF delivery")
    for name, value in (("data.lock", data), ("evaluator.lock", evaluator)):
        if card.get("hosted_bindings", {}).get(name) != hashlib.sha256(encoded(value)).hexdigest():
            raise ValueError("delivery hosted bindings differ from expected transport")
    return data, evaluator
