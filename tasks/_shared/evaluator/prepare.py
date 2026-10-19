#!/usr/bin/env python3
"""Prepare locked private evaluator inputs without changing scientific transforms.

The caller materializes evaluator.lock files under ``--data`` and keeps all
private material outside the submission workspace. Only brain-age and worm
need conversion. An existing prepared tree is accepted solely when its receipt,
locked sources, transform code, and every prepared output still match.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("bpb_private_dispatch", HERE / "score.py")
DISPATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DISPATCH)
ROOT = DISPATCH.ROOT
RECEIPT = "PRIVATE_PREPARED.json"
SCHEMA = "bpb-private-prepared/1"
WORM = "celegans-structure-function-divergence"
BRAIN = "brain-age-mri"
WORM_CACHE_SHA = (
    "f02c68c9a2d34fe7b5aa8c7d74d8aca9ea9676d647e794ba99abbbff1b6350e5",
    "613bfa8fb52f0ec85d65c5a878f6a40620e6c960337a4d1d1ac2ffa2af2d6e57",
    "f3273b529c7542cf6b1d61b438d0e87526e32166b74d464fcaefe4700d87a558",
    "d6627c50f4295291e68c071e001e1e302b03d2d472a7f251f90cb36839e9be1a",
    "768d2b16557d768b51f81548f630adb45d76c1f99586e8fd4c90279293cc9dae",
    "734202acc42c30a5cce882e695bb2efa333ade5b76345d7e35908342ee640b2c",
)


def regular(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("private source or prepared output is not an ordinary file")
    return info


def locked_sources(task: Path, task_id: str, data: Path) -> dict[str, dict]:
    lock_path = task / "evaluator.lock"
    regular(lock_path)
    lock = DISPATCH.strict_json(lock_path)
    if (not isinstance(lock, dict) or lock.get("schema") != "bpb-evaluator-data/1"
            or lock.get("task_id") != task_id or not isinstance(lock.get("files"), list)
            or lock.get("repo_id") != "BrainPilot-Bench/Tasks-Data-Private" or
            not isinstance(lock.get("revision"), str) or
            re.fullmatch(r"[0-9a-f]{40}", lock["revision"]) is None or
            not lock["files"]):
        raise ValueError("evaluator lock identity differs")
    records = {}
    for item in lock["files"]:
        if not isinstance(item, dict) or set(item) != {"name", "path", "sha256", "bytes"}:
            raise ValueError("evaluator lock file record differs")
        if not isinstance(item["path"], str):
            raise ValueError("invalid evaluator lock path")
        components = item["path"].split("/")
        relative = PurePosixPath(item["path"])
        if (relative.is_absolute() or not relative.parts or
                any(re.fullmatch(r"[A-Za-z0-9._-]+", part) is None or part in (".", "..")
                    for part in components) or
                not isinstance(item["sha256"], str) or
                DISPATCH.SHA.fullmatch(item["sha256"]) is None or
                type(item["bytes"]) is not int or item["bytes"] <= 0 or
                item["path"] in records):
            raise ValueError("invalid evaluator lock path or digest")
        path = data.joinpath(*relative.parts)
        if any(parent.is_symlink() for parent in (path.parent, *path.parent.parents)):
            raise ValueError("private source directory is a symlink")
        info = regular(path)
        if info.st_size != item["bytes"] or DISPATCH.digest(path) != item["sha256"]:
            raise ValueError("private source differs from evaluator lock")
        records[item["path"]] = {"sha256": item["sha256"], "bytes": item["bytes"]}
    return records


def verify_materialization(task: Path, data: Path) -> dict[str, dict]:
    """Check the native lock, copied source bytes, and completed owner marker."""
    task_id = DISPATCH.task_identity(task)
    task = task.resolve()
    if data.is_symlink() or data.name != "evaluator" or not data.is_dir():
        raise ValueError("private materialization must be an ordinary evaluator directory")
    data = data.resolve()
    marker_path = data / ".bpb-evaluator.json"
    regular(marker_path)
    marker = DISPATCH.strict_json(marker_path)
    lock_path = task / "evaluator.lock"
    regular(lock_path)
    lock = DISPATCH.strict_json(lock_path)
    if (not isinstance(marker, dict) or
            set(marker) != {"schema", "task_id", "revision", "evaluator_lock_sha256",
                            "files", "prepared_at"} or
            marker["schema"] != "bpb-prepared-evaluator/1" or
            marker["task_id"] != task_id or
            marker["revision"] != lock.get("revision") or
            marker["evaluator_lock_sha256"] != DISPATCH.digest(lock_path) or
            type(marker["files"]) is not int or marker["files"] != len(lock.get("files", []))):
        raise ValueError("private evaluator completion marker differs from lock")
    return locked_sources(task, task_id, data)


def worm_cache(cache_root: Path) -> dict[str, dict]:
    if cache_root.is_symlink() or not cache_root.is_dir():
        raise ValueError("private cache root must be an ordinary directory")
    cache = cache_root.resolve()
    records = {}
    for expected in WORM_CACHE_SHA:
        file = cache / expected / "data"
        if file.parent.is_symlink():
            raise ValueError("private cache entry is a symlink")
        info = regular(file)
        if DISPATCH.digest(file) != expected:
            raise ValueError("worm raw input differs from pinned source")
        records[f"cache/{expected}/data"] = {"sha256": expected, "bytes": info.st_size}
    return records


def tree_snapshot(root: Path) -> dict[str, dict]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("prepared data must be an ordinary directory")
    records = {}
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        info = regular(path)
        relative = path.relative_to(root).as_posix()
        if relative != RECEIPT:
            records[relative] = {"sha256": DISPATCH.digest(path), "bytes": info.st_size}
    if not records:
        raise ValueError("prepared data tree is empty")
    return records


def transform_file(task: Path, task_id: str) -> Path:
    if task_id == BRAIN:
        return task / "env/safe_unpack.py"
    return task / "env/setup-evaluator.sh"


def receipt_value(task_id: str, sources: dict, transform: Path, prepared: Path) -> dict:
    return {"schema": SCHEMA, "task_id": task_id,
            "sources": sources, "transform_sha256": DISPATCH.digest(transform),
            "files": tree_snapshot(prepared)}


def verify_prepared(task: Path, data: Path) -> tuple[Path, dict]:
    """Read-only acceptance of a prepared tree; no cache or conversion required."""
    task_id = DISPATCH.task_identity(task)
    if task_id not in (BRAIN, WORM):
        raise ValueError("this task has no prepared private data tree")
    if data.is_symlink() or data.name != "evaluator" or not data.is_dir():
        raise ValueError("private materialization must be an ordinary evaluator directory")
    data = data.resolve()
    prepared = data / "prepared"
    if prepared.is_symlink() or not prepared.is_dir():
        raise ValueError("prepared private data is missing or unsafe")
    receipt_path = prepared / RECEIPT
    regular(receipt_path)
    receipt = DISPATCH.strict_json(receipt_path)
    if not isinstance(receipt, dict) or set(receipt) != {
            "schema", "task_id", "sources", "transform_sha256", "files"}:
        raise ValueError("prepared private receipt is invalid")
    sources = verify_materialization(task.resolve(), data)
    if task_id == WORM:
        cache_sources = receipt["sources"]
        if not isinstance(cache_sources, dict):
            raise ValueError("prepared worm source receipt is invalid")
        for sha in WORM_CACHE_SHA:
            key = f"cache/{sha}/data"
            item = cache_sources.get(key)
            if (not isinstance(item, dict) or set(item) != {"sha256", "bytes"} or
                    item["sha256"] != sha or type(item["bytes"]) is not int or
                    item["bytes"] <= 0):
                raise ValueError("prepared worm cache identity differs")
            sources[key] = item
    expected = receipt_value(task_id, sources, transform_file(task.resolve(), task_id), prepared)
    if receipt != expected:
        raise ValueError("prepared private data differs from source-bound receipt")
    return prepared, receipt


def restrict_permissions(root: Path) -> None:
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            path.chmod(0o700)
        else:
            regular(path)
            path.chmod(0o600)
    root.chmod(0o700)


def prepare(task: Path, data: Path, cache_root: Path) -> tuple[Path, str]:
    task_id = DISPATCH.task_identity(task)
    task = task.resolve()
    if data.is_symlink() or data.name != "evaluator" or not data.is_dir():
        raise ValueError("private materialization must be an ordinary evaluator directory")
    data = data.resolve()
    sources = verify_materialization(task, data)
    if task_id not in (BRAIN, WORM):
        return data, "direct"
    transform = transform_file(task, task_id)
    if task_id == WORM:
        sources.update(worm_cache(cache_root))
    prepared = data / "prepared"
    if prepared.exists() or prepared.is_symlink():
        _path, receipt = verify_prepared(task, data)
        if receipt["sources"] != sources:
            raise ValueError("existing prepared output differs from source-bound receipt")
        return prepared, "reused"
    stage = data / f".prepare-{uuid.uuid4().hex}"
    try:
        if task_id == BRAIN:
            # The existing helper enforces archive hash, member safety, and role structure.
            command = [sys.executable, str(transform), "--archive", str(data / "evaluator_data.zip"),
                       "--destination", str(stage), "--role", "evaluator"]
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
        else:
            stage.mkdir(mode=0o700)
            command = ["bash", str(transform)]
            env = {"PATH": os.environ.get("PATH", ""), "BPB_CACHE_ROOT": str(cache_root.resolve()),
                   "BPB_PRIVATE_EVAL_DIR": str(stage), "BPB_PYTHON": DISPATCH.evaluator_python(task_id),
                   "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(command, env=env, capture_output=True, text=True,
                                timeout=3600, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"existing private preparation exited {result.returncode}")
        restrict_permissions(stage)
        payload = receipt_value(task_id, sources, transform, stage)
        # Exclusive reservation prevents rename-over an empty competing tree.
        # The completion receipt is written only after every staged file moves.
        prepared.mkdir(mode=0o700)
        for source in stage.iterdir():
            target = prepared / source.name
            if target.exists() or target.is_symlink():
                raise ValueError("prepared destination changed during publication")
            os.rename(source, target)
        DISPATCH.write_new_json(prepared / RECEIPT, payload)
        stage.rmdir()
        return prepared, "prepared"
    except Exception as error:
        # Only this invocation's unique staging tree is removed. Locked sources
        # and any earlier prepared tree remain untouched.
        if stage.exists() and not stage.is_symlink():
            shutil.rmtree(stage)
        diagnosis = data / f".prepare-error-{uuid.uuid4().hex}.json"
        DISPATCH.write_new_json(diagnosis, {"schema": "bpb-private-prepare-error/1",
                                            "task_id": task_id,
                                            "error_type": type(error).__name__,
                                            "status": "preparation_failed"})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        prepared, status = prepare(args.task, args.data, args.cache_root)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired,
            KeyError, TypeError) as error:
        print(f"private preparation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": status, "data": str(prepared)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
