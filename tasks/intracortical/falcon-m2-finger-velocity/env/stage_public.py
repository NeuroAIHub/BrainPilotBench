"""Copy only contract-bound M2 Train/Valid arrays into an Agent workspace.

No symlinks or hardlinks are created. An existing nonempty destination is
accepted only when it contains exactly the expected public files, all with
the frozen hashes. Test data, raw NWB, owner receipts, and contract are not
staged. This script never discovers an evaluator directory.
"""

from __future__ import annotations

import argparse
import os
import json
from pathlib import Path
import shutil
import tempfile

from verify_public import CONTRACT, sha256_file, verify


def inside_git_checkout(path: Path) -> bool:
    return any((ancestor / ".git").exists() for ancestor in (path, *path.parents))


def expected_files(source: Path) -> list[Path]:
    contract = json.loads(CONTRACT.read_text())
    result = []
    for role in ("train", "valid"):
        manifest_rel = Path(role) / "manifest.json"
        manifest = json.loads((source / manifest_rel).read_text())
        if manifest["role"] != role or sha256_file(source / manifest_rel) != contract["derived_manifests"][role]["sha256"]:
            raise ValueError("Public role manifest changed before staging")
        result.append(manifest_rel)
        for run in manifest["runs"]:
            if run["role"] != role:
                raise ValueError("Non-public run in staging source")
            for file in run["files"].values():
                relative = manifest_rel.parent / file["path"]
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe public array path")
                result.append(relative)
    if len(result) != 30 or len(set(result)) != len(result):
        raise ValueError("Expected two manifests and 28 public arrays")
    return result


def check_destination(target: Path, expected: list[Path]) -> None:
    expected_set = set(expected)
    actual = {file.relative_to(target) for file in target.rglob("*") if file.is_file() or file.is_symlink()}
    if actual != expected_set:
        raise ValueError("Existing public_data does not contain exactly the expected 30 public files")
    for relative in expected:
        file = target / relative
        if file.is_symlink() or not file.is_file() or file.stat().st_nlink != 1:
            raise ValueError("public_data contains a symbolic link or hard link")
    verify(target)


def stage(source: Path, target: Path) -> dict:
    source = source.resolve(strict=True)
    target = target.absolute()
    if any(path.is_symlink() for path in (target, *target.parents)) or inside_git_checkout(target):
        raise ValueError("Stage to an ordinary Agent workspace outside every Git checkout")
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Public source and Agent stage must be separate")
    verify(source)
    expected = expected_files(source)
    if target.exists() and not target.is_dir():
        raise ValueError("Agent public_data target must be a directory")
    if target.exists() and any(target.iterdir()):
        check_destination(target, expected)
        return {"stage": str(target), "reused_verified": True, "files": len(expected)}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".public-data-", dir=target.parent) as temporary:
        staged = Path(temporary)
        for relative in expected:
            original = source / relative
            destination = staged / relative
            if (original.is_symlink() or not original.is_file() or original.stat().st_nlink != 1
                    or any(parent.is_symlink() for parent in original.parents if parent.is_relative_to(source))):
                raise ValueError("Public source has a symlink or missing array")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output, original.open("rb") as data:
                shutil.copyfileobj(data, output, length=4 * 1024 * 1024)
        check_destination(staged, expected)
        staged.chmod(0o755)
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError("Agent stage target changed during copy")
        os.replace(staged, target)
    return {"stage": str(target), "reused_verified": False, "files": len(expected)}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Verified external public root")
    parser.add_argument("--stage-to", required=True, type=Path, help="Agent workspace public_data directory")
    args = parser.parse_args()
    result = stage(args.source, args.stage_to)
    print(json.dumps({**result, "test_staged": False, "raw_nwb_staged": False}, sort_keys=True))


if __name__ == "__main__":
    main()
