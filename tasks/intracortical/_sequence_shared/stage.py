"""Copy only frozen H2/B1 Train and Valid data into an Agent workspace."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from export import ROOT, TASKS, digest
from freeze import verify_manifest


def inside_git(path: Path) -> bool:
    return any((part / ".git").exists() for part in (path, *path.parents))


def expected(task: str, source: Path) -> list[Path]:
    contract = json.loads((ROOT / "tasks/intracortical" / TASKS[task] / "contract.json").read_text())
    files = []
    for role in ("train", "valid"):
        manifest_rel = Path(role) / "manifest.json"
        manifest_path = source / manifest_rel
        manifest, summary = verify_manifest(manifest_path, task, role)
        if any(summary[key] != contract["derived_manifests"][role][key]
               for key in ("sha256", "bytes", "runs", "sessions", "trials")):
            raise ValueError("Public manifest differs from frozen contract")
        files.append(manifest_rel)
        for run in manifest["runs"]:
            for metadata in run["files"].values():
                files.append(Path(role) / metadata["path"])
    if len(files) != len(set(files)):
        raise ValueError("Duplicate public array path")
    return files


def verify_staged(task: str, stage: Path, files: list[Path] | None = None) -> dict:
    files = files or expected(task, stage)
    actual = {path.relative_to(stage) for path in stage.rglob("*") if path.is_file() or path.is_symlink()}
    if actual != set(files):
        raise ValueError("Staged public_data contains missing or extra files")
    source = json.loads((ROOT / "tasks/intracortical" / TASKS[task] / "contract.json").read_text())
    for role in ("train", "valid"):
        manifest = json.loads((stage / role / "manifest.json").read_text())
        if digest(stage / role / "manifest.json") != source["derived_manifests"][role]["sha256"]:
            raise ValueError("Staged manifest digest differs")
        for run in manifest["runs"]:
            for metadata in run["files"].values():
                path = stage / role / metadata["path"]
                if (path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or
                        path.stat().st_size != metadata["bytes"] or digest(path) != metadata["sha256"]):
                    raise ValueError("Staged public array differs")
    return {"train_runs": source["derived_manifests"]["train"]["runs"],
            "valid_runs": source["derived_manifests"]["valid"]["runs"],
            "files": len(files)}


def stage(task: str, source: Path, target: Path) -> dict:
    source = source.resolve(strict=True)
    target = target.absolute()
    if any(part.is_symlink() for part in (target, *target.parents)) or inside_git(target):
        raise ValueError("Agent stage must be an ordinary directory outside Git")
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Public source and Agent stage must be separate")
    files = expected(task, source)
    if target.exists() and any(target.iterdir()):
        report = verify_staged(task, target, files)
        return {**report, "stage": str(target), "reused_verified": True}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bpb-sequence-stage-", dir=target.parent) as scratch:
        prepared = Path(scratch)
        prepared.chmod(0o755)
        for relative in files:
            original = source / relative
            if original.is_symlink() or not original.is_file() or original.stat().st_nlink != 1:
                raise ValueError("Public source contains symbolic link or hard link")
            destination = prepared / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with original.open("rb") as inp, destination.open("xb") as out:
                shutil.copyfileobj(inp, out, length=4 * 1024 * 1024)
        report = verify_staged(task, prepared, files)
        if target.exists():
            if target.is_symlink() or any(target.iterdir()):
                raise ValueError("Target changed while public data was copied")
            target.rmdir()
        os.replace(prepared, target)
    return {**report, "stage": str(target), "reused_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=TASKS)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--stage-to", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({**stage(args.task, args.source, args.stage_to),
                      "test_staged": False, "raw_nwb_staged": False}, sort_keys=True))


if __name__ == "__main__":
    main()
