"""Trusted source-only CalMS task contract and packet handling."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat

from calms_freeze import FILES
from calms_runner import _role_packet
from mouse_transport import transport_metadata


def read_json(path: Path) -> dict:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    with path.open(encoding="utf-8") as stream:
        result = json.load(stream, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("JSON object required")
    return result


def safe_path(path: Path, *, directory: bool = False) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"symlink path component: {part}")
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("directory required")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("regular single-link file required")


def digest(path: Path) -> tuple[int, str]:
    safe_path(path)
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            size += len(block)
            h.update(block)
    return size, h.hexdigest()


def _record(item: object) -> tuple[str, int, str]:
    if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
        raise ValueError("contract file record mismatch")
    rel, size, sha = item["path"], item["bytes"], item["sha256"]
    if (not isinstance(rel, str) or not rel or PurePosixPath(rel).is_absolute()
            or any(part in ("", ".", "..") or not all(c.isalnum() or c in "._-" for c in part)
                   for part in rel.split("/")) or type(size) is not int or size <= 0
            or not isinstance(sha, str) or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)):
        raise ValueError("unsafe contract file record")
    return rel, size, sha


def load_contract(task_dir: Path) -> dict:
    safe_path(task_dir, directory=True)
    contract_path = task_dir / "contract.json"
    safe_path(contract_path)
    contract = read_json(contract_path)
    if (contract.get("schema") != "bpb-calms21-task-contract/1"
            or contract.get("task_id") != task_dir.name
            or contract.get("task_version") != "0.1-source"
            or contract.get("source_task") not in ("task1", "task2", "task3")):
        raise ValueError("CalMS task contract identity mismatch")
    for field in ("public_manifest_sha256", "owner_manifest_sha256", "source_sha256", "revision"):
        value = contract.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("contract digest mismatch")
    revision = hashlib.sha256(bytes.fromhex(contract["public_manifest_sha256"])
                              + bytes.fromhex(contract["owner_manifest_sha256"])).hexdigest()
    if revision != contract["revision"] or contract.get("metric") != "F1":
        raise ValueError("contract revision or metric mismatch")
    for field in ("public_files", "owner_files"):
        entries = contract.get(field)
        if not isinstance(entries, list) or not entries:
            raise ValueError("contract file list missing")
        names = [_record(item)[0] for item in entries]
        if names != sorted(set(names)):
            raise ValueError("contract file list duplicate or unsorted")
    if {entry["path"] for entry in contract["public_files"] if entry["path"] == "manifest.json"} != {"manifest.json"}:
        raise ValueError("public manifest missing")
    if {entry["path"] for entry in contract["owner_files"] if entry["path"] == "test-manifest.json"} != {"test-manifest.json"}:
        raise ValueError("owner manifest missing")
    return contract


def lock_entries(task_dir: Path, contract: dict, *, private: bool) -> list[dict]:
    path = task_dir / "data.lock"
    safe_path(path)
    lock = read_json(path)
    entries = lock.get("datasets")
    if not isinstance(entries, list):
        raise ValueError("data.lock datasets missing")
    selected = [entry for entry in entries if entry.get("scope") == ("private" if private else "public")]
    records = contract["owner_files" if private else "public_files"]
    if len(selected) != len(records):
        raise ValueError("data.lock file count mismatch")
    prefix = f"local://tasks/animal-behavior/{contract['task_id']}/{contract['revision']}"
    # Validate both roles together, including transport hashes, before selecting one.
    all_entries = []
    for is_private, key in ((False, "public_files"), (True, "owner_files")):
        for item in contract[key]:
            rel, size, sha = _record(item)
            packet_role = "evaluator" if is_private else "public"
            value = {"name": packet_role + "__" + rel.replace("/", "__"),
                     "uri": f"{prefix}/{packet_role}/{rel}", "sha256": sha, "bytes": size,
                     "scope": "private" if is_private else "public",
                     "format": "json" if rel.endswith(".json") else "npz"}
            if not is_private:
                value["path"] = "public/" + rel
            all_entries.append(value)
    source_evaluator = {"schema": "bpb-evaluator-source/1", "task_id": contract["task_id"],
                        "repo_id": "local-prepared", "revision": contract["revision"],
                        "files": [{"name": "evaluator__" + row["path"].replace("/", "__"), **row}
                                  for row in contract["owner_files"]]}
    expected_data, expected_evaluator = transport_metadata(task_dir, contract,
                                                          {"datasets": all_entries}, source_evaluator)
    if lock != expected_data or read_json(task_dir / "evaluator.lock") != expected_evaluator:
        raise ValueError("data.lock or evaluator.lock mapping differs from contract")
    return selected


def copy_verified(source: Path, destination: Path, item: dict) -> None:
    rel, size, sha = _record(item)
    if digest(source) != (size, sha):
        raise ValueError(f"source data size/SHA mismatch: {rel}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_path(destination.parent, directory=True)
    with source.open("rb") as reader, os.fdopen(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as writer:
        shutil.copyfileobj(reader, writer, 4 * 1024 * 1024)
    if digest(destination) != (size, sha):
        raise ValueError("copied data size/SHA mismatch")


def exact_packet(packet: Path, contract: dict, *, private: bool) -> None:
    role = "owner" if private else "public"
    rels = {item["path"] for item in contract["owner_files" if private else "public_files"]}
    safe_path(packet, directory=True)
    if {child.name for child in packet.iterdir()} != {role}:
        raise ValueError("packet includes opposite role or extra file")
    expected = {role + "/" + rel for rel in rels}
    found = {str(path.relative_to(packet)) for path in packet.rglob("*") if path.is_file()}
    if found != expected or any(path.is_symlink() for path in packet.rglob("*")):
        raise ValueError("packet file set mismatch")
    _role_packet(packet, "test" if private else "valid",
                 contract["owner_manifest_sha256" if private else "public_manifest_sha256"])


def public_cache_root() -> Path:
    raw = os.environ.get("BPB_CACHE_ROOT")
    if raw:
        return Path(raw)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "brainpilot-bench"


def stage_public_cache(task_dir: Path, contract: dict, output: Path) -> None:
    lock_entries(task_dir, contract, private=False)
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh public packet required")
    output.mkdir(mode=0o700, parents=True)
    root = public_cache_root()
    safe_path(root, directory=True)
    for item in contract["public_files"]:
        rel, _, sha = _record(item)
        copy_verified(root / sha / "data", output / "public" / rel, item)
    exact_packet(output, contract, private=False)


def stage_public_workspace(task_dir: Path, contract: dict, output: Path) -> None:
    lock_entries(task_dir, contract, private=False)
    source_root_raw = os.environ.get("BPB_PUBLIC_DATA_ROOT")
    if not source_root_raw:
        raise ValueError("BPB_PUBLIC_DATA_ROOT is required for public setup")
    source_root = Path(source_root_raw)
    safe_path(source_root, directory=True)
    if {child.name for child in source_root.iterdir()} != {"public"}:
        raise ValueError("public setup source includes another role or extra file")
    for ancestor in (source_root, *source_root.parents):
        if any((ancestor / marker).exists() for marker in (".bpb-private-cache.json", ".bpb-evaluator.json")):
            raise ValueError("public setup cannot use owner cache")
    exact_packet(source_root, contract, private=False)
    if output.exists() or output.is_symlink():
        exact_packet(output, contract, private=False)
        return
    output.mkdir(mode=0o700, parents=True)
    for item in contract["public_files"]:
        rel, _, _ = _record(item)
        copy_verified(source_root / "public" / rel, output / "public" / rel, item)
    exact_packet(output, contract, private=False)


def stage_owner(task_dir: Path, contract: dict, evaluator_root: Path, output: Path) -> None:
    lock_entries(task_dir, contract, private=True)
    safe_path(evaluator_root, directory=True)
    if evaluator_root.name != "evaluator" or not (evaluator_root / ".bpb-evaluator.json").is_file():
        raise ValueError("prepared evaluator root and receipt required")
    lock_path = task_dir / "evaluator.lock"
    safe_path(lock_path)
    lock = read_json(lock_path)
    expected_files = [{"name": "evaluator__" + item["path"].replace("/", "__"), **item}
                      for item in contract["owner_files"]]
    # lock_entries validates exact source or pinned-hosted transport against the contract.
    lock_entries(task_dir, contract, private=True)
    marker = evaluator_root / ".bpb-evaluator.json"
    safe_path(marker)
    receipt = read_json(marker)
    if (receipt.get("schema") != "bpb-prepared-evaluator/1"
            or receipt.get("task_id") != contract["task_id"]
            or receipt.get("revision") != lock["revision"]
            or receipt.get("files") != len(expected_files)
            or receipt.get("evaluator_lock_sha256") != digest(lock_path)[1]):
        raise ValueError("evaluator receipt differs from contract and lock")
    found = {str(path.relative_to(evaluator_root)) for path in evaluator_root.rglob("*") if path.is_file()}
    expected = {item["path"] for item in contract["owner_files"]} | {".bpb-evaluator.json"}
    if found != expected or any(path.is_symlink() for path in evaluator_root.rglob("*")):
        raise ValueError("evaluator root contains extra or missing files")
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh owner packet required")
    output.mkdir(mode=0o700, parents=True)
    for item in contract["owner_files"]:
        rel, _, _ = _record(item)
        copy_verified(evaluator_root / rel, output / "owner" / rel, item)
    exact_packet(output, contract, private=True)


def submission_dir(artifacts: Path) -> Path:
    safe_path(artifacts, directory=True)
    if {child.name for child in artifacts.iterdir()} != {"submission"}:
        raise ValueError("artifacts must contain only submission/")
    source = artifacts / "submission"
    safe_path(source, directory=True)
    if {child.name for child in source.iterdir()} != set(FILES):
        raise ValueError("submission must contain exactly model.py, config.json, weights.npz")
    return source
