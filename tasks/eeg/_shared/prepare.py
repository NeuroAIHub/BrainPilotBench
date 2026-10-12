"""Stage only a frozen EEG task's public train/validation files.

This tool never reads a private binding or Test path.  A maintainer can fetch
the task-scoped local:// entries into BrainPilotBench's content-addressed cache
before starting the Agent, or point BPB_EEG_PUBLIC_PACKAGE_DIR at an already
published, public-only package whose original task_spec.json matches the lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

FILES = ("train.npz", "val.npz", "train-groups.json", "val-groups.json")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cache_root() -> Path:
    explicit = os.environ.get("BPB_CACHE_ROOT")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "brainpilot-bench"


def read_contract(task: Path) -> dict:
    contract = json.loads((task / "contract.json").read_text(encoding="utf-8"))
    if set(contract.get("data_files", {})) != set(FILES):
        raise ValueError("contract must name exactly the four public data files")
    for name, record in contract["data_files"].items():
        if (not isinstance(record, dict) or
                not isinstance(record.get("sha256"), str) or
                len(record["sha256"]) != 64 or
                type(record.get("bytes")) is not int or record["bytes"] <= 0):
            raise ValueError(f"invalid public file record: {name}")
    return contract


def checked_source(path: Path, expected: dict, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or symlinked public {label}: {path}")
    if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
        raise ValueError(f"public {label} size/SHA-256 differs from the frozen task")
    return path


def prepare(task: Path, output: Path) -> dict:
    contract = read_contract(task)
    package = os.environ.get("BPB_EEG_PUBLIC_PACKAGE_DIR")
    if package and Path(package).is_symlink():
        raise ValueError("public package directory cannot be a symbolic link")
    package_dir = Path(package).resolve(strict=True) if package else None
    if package_dir is not None:
        if not package_dir.is_dir() or package_dir.is_symlink():
            raise ValueError("public package must be a real directory")
        source_spec = checked_source(
            package_dir / "task_spec.json",
            {"sha256": contract["source_task_spec_sha256"],
             "bytes": (package_dir / "task_spec.json").stat().st_size},
            "task_spec.json",
        )
        if digest(source_spec) != contract["source_task_spec_sha256"]:
            raise ValueError("public package belongs to a different task version")
    source_files = {}
    for name in FILES:
        record = contract["data_files"][name]
        source = (package_dir / "data" / name) if package_dir else cache_root() / record["sha256"] / "data"
        if package_dir and not source.resolve().is_relative_to(package_dir):
            raise ValueError(f"public file escapes package root: {name}")
        source_files[name] = checked_source(source, record, name)
    if output.is_symlink():
        raise ValueError("public output directory cannot be a symbolic link")
    output.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        destination = output / name
        record = contract["data_files"][name]
        if destination.exists() or destination.is_symlink():
            checked_source(destination, record, name)
            continue
        fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=output)
        os.close(fd)
        temporary_path = Path(temporary)
        try:
            shutil.copyfile(source_files[name], temporary_path)
            checked_source(temporary_path, record, name)
            temporary_path.chmod(0o444)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    spec = output / "task_spec.json"
    content = json.dumps(contract, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if spec.exists() or spec.is_symlink():
        if spec.is_symlink() or spec.read_bytes() != content:
            raise ValueError("refusing to replace a different public task_spec.json")
    else:
        spec.write_bytes(content)
        spec.chmod(0o444)
    return {"task_id": contract["task_id"], "source_task_spec_sha256": contract["source_task_spec_sha256"],
            "public_files": list(FILES), "private_test": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(Path(args.task), Path(args.output)), sort_keys=True))


if __name__ == "__main__":
    main()
