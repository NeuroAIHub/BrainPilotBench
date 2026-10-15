"""Verify complete Train/Valid arrays against the tracked M1 contract.

This Agent-facing verifier never discovers or opens the evaluator/Test root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


TASK_DIR = Path(__file__).resolve().parent.parent
CONTRACT = TASK_DIR / "contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(data_dir: Path) -> dict:
    data_dir = data_dir.resolve()
    contract = json.loads(CONTRACT.read_text())
    if contract["schema"] != "bpb-falcon-regression-contract/1":
        raise ValueError("Unexpected M1 contract schema")
    counts = {}
    for role, expected in (("train", 3), ("valid", 1)):
        manifest_path = data_dir / role / "manifest.json"
        if manifest_path.parent.is_symlink() or manifest_path.is_symlink() or manifest_path.stat().st_nlink != 1:
            raise ValueError("Public manifest must be a unique file in an ordinary role directory")
        binding = contract["derived_manifests"][role]
        if manifest_path.stat().st_size != binding["bytes"] or sha256_file(manifest_path) != binding["sha256"]:
            raise ValueError(f"{role} manifest differs from tracked contract")
        manifest = json.loads(manifest_path.read_text())
        if manifest["schema"] != "bpb-falcon-regression-data/1" or manifest["role"] != role:
            raise ValueError(f"Wrong {role} manifest role")
        if len(manifest["runs"]) != expected:
            raise ValueError(f"Incomplete {role} runs")
        for run in manifest["runs"]:
            if run["role"] != role:
                raise ValueError("Cross-role run in public manifest")
            for name, metadata in run["files"].items():
                relative = Path(metadata["path"])
                original = manifest_path.parent / relative
                if (original.is_symlink() or not original.is_file() or original.stat().st_nlink != 1
                        or any(parent.is_symlink() for parent in original.parents if parent.is_relative_to(data_dir))):
                    raise ValueError("Public arrays cannot use symbolic links or hardlinks")
                path = original.resolve()
                if (relative.is_absolute() or ".." in relative.parts
                        or not path.is_relative_to(manifest_path.parent.resolve())):
                    raise ValueError("Array path escapes public role")
                if path.stat().st_size != metadata["bytes"] or sha256_file(path) != metadata["sha256"]:
                    raise ValueError(f"Array digest mismatch: {run['id']}/{name}")
                array = np.load(path, mmap_mode="r", allow_pickle=False)
                if list(array.shape) != metadata["shape"] or array.dtype.name != metadata["dtype"]:
                    raise ValueError(f"Array header mismatch: {run['id']}/{name}")
        counts[role] = len(manifest["runs"])
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path, help="Public root containing train/ and valid/")
    args = parser.parse_args()
    counts = verify(args.data_dir)
    print(json.dumps({"public_data_dir": str(args.data_dir.resolve()), "verified_runs": counts,
                      "test_accessed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
