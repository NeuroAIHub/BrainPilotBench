#!/usr/bin/env python3
"""Copy only verified Train and Valid arrays into an Agent workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, spec: dict) -> None:
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != spec["bytes"]
            or sha256(path) != spec["sha256"]):
        raise ValueError(f"Public file differs from its frozen manifest: {path}")


def verify_tree(directory: Path, files: dict[Path, tuple[Path, dict]]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("The staged public root is not a regular directory")
    expected_directories = {relative.parent for relative in files if relative.parent != Path(".")}
    actual_files = set()
    for item in directory.rglob("*"):
        if item.is_symlink():
            raise ValueError("A staged path is a symlink")
        relative = item.relative_to(directory)
        if item.is_dir():
            if relative not in expected_directories:
                raise ValueError("The stage contains an unexpected directory")
        elif item.is_file():
            actual_files.add(relative)
        else:
            raise ValueError("The stage contains an unexpected file type")
    if actual_files != set(files):
        raise ValueError("The stage has missing or extra files")
    for relative, (_, spec) in files.items():
        verify_file(directory / relative, spec)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--data-root", type=Path)
    source_group.add_argument("--public-root", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    public = args.public_root if args.public_root is not None else args.data_root / "derived-v2" / "public"
    if args.destination.resolve().is_relative_to(ROOT.parents[2].resolve()):
        raise ValueError("The Agent data destination must be outside the Git checkout")
    if (args.destination.resolve().is_relative_to(public.resolve()) or
            (args.data_root is not None and
             args.destination.resolve().is_relative_to(args.data_root.resolve()))):
        raise ValueError("The Agent destination must not be inside its source data")
    if args.public_root is not None and (public.parent / "owner").exists():
        raise ValueError("Agent public root must be separate from owner data")
    if args.destination.is_symlink():
        raise ValueError("The Agent destination cannot be a symlink")
    contract = json.loads((ROOT / "contract.json").read_text())
    manifests = {}
    subjects = set()
    files: dict[Path, tuple[Path, dict]] = {}
    for role in ("train", "validation"):
        manifest_path = public / f"{role}_manifest.json"
        expected = contract["roles"][role]
        verify_file(manifest_path, expected)
        manifest = json.loads(manifest_path.read_text())
        if manifest["schema"] != "bpb-ieeg-film-derived-role/2" or manifest["role"] != role:
            raise ValueError("Unexpected public role manifest")
        manifests[role] = (manifest_path, manifest)
        files[Path(manifest_path.name)] = (manifest_path, expected)
        subjects.update(record["subject_id"] for record in manifest["subjects"])
    if not subjects:
        raise ValueError("No public subjects")
    if any({record["subject_id"] for record in manifest["subjects"]} != subjects
           for _, manifest in manifests.values()):
        raise ValueError("Train and validation participant sets differ")
    for _, manifest in manifests.values():
        for record in manifest["subjects"]:
            subject_id = record["subject_id"]
            if not isinstance(subject_id, str) or not subject_id.isalnum():
                raise ValueError("Invalid opaque subject ID")
            src_dir = public / subject_id
            if src_dir.is_symlink():
                raise ValueError("Public subject directory cannot be a symlink")
            for kind in ("arrays", "labels", "metadata"):
                spec = record["files"][kind]
                name = spec["path"]
                if Path(name).name != name or src_dir.joinpath(name).is_symlink():
                    raise ValueError("Unsafe public file path")
                source = src_dir / name
                relative = Path(subject_id) / name
                if relative in files and files[relative][1] != spec:
                    raise ValueError("Train and Valid metadata bindings disagree")
                files[relative] = (source, spec)
    if args.destination.exists() and any(args.destination.iterdir()):
        verify_tree(args.destination, files)
        status = "already_staged_and_verified"
    else:
        for source, spec in files.values():
            verify_file(source, spec)
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=args.destination.name + ".stage-",
                                      dir=args.destination.parent))
        try:
            for relative, (source, spec) in files.items():
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                verify_file(target, spec)
            stage.chmod(0o755)
            verify_tree(stage, files)
            if args.destination.exists() and any(args.destination.iterdir()):
                verify_tree(args.destination, files)
                status = "already_staged_and_verified"
            else:
                os.replace(stage, args.destination)
                status = "public_train_validation_only"
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    print(json.dumps({"status": status, "subjects": len(subjects),
                      "destination": str(args.destination)}, indent=2))


if __name__ == "__main__":
    main()
