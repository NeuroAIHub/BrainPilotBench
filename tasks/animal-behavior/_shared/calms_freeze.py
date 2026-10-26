"""Freeze the exact three-file CalMS submission contract with byte digests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import zipfile

FILES = ("model.py", "config.json", "weights.npz")
MAX_BYTES = {"model.py": 1_000_000, "config.json": 100_000, "weights.npz": 100_000_000}


def _safe_file(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("symlink path component")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("regular single-link file required")


def digest(path: Path) -> dict[str, object]:
    _safe_file(path)
    if path.stat().st_size > MAX_BYTES.get(path.name, 100_000_000):
        raise ValueError("submission file too large")
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            sha.update(block)
    return {"bytes": size, "sha256": sha.hexdigest()}


def snapshot(source: Path, *, frozen: bool = False) -> dict[str, dict[str, object]]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("submission directory required")
    expected = set(FILES) | ({"freeze.json"} if frozen else set())
    if {entry.name for entry in source.iterdir()} != expected:
        raise ValueError("submission must contain exact contract files")
    result = {name: digest(source / name) for name in FILES}
    with (source / "config.json").open(encoding="utf-8") as stream:
        if not isinstance(json.load(stream), dict):
            raise ValueError("config object required")
    # Inspect NPZ without loading object arrays; candidate code never runs here.
    import numpy as np
    with zipfile.ZipFile(source / "weights.npz") as archive:
        members = archive.infolist()
        if (not members or len(members) > 128
                or len({item.filename for item in members}) != len(members)
                or any(not item.filename.endswith(".npy") or "/" in item.filename or "\\" in item.filename
                       or item.file_size > 100_000_000 for item in members)
                or sum(item.file_size for item in members) > 100_000_000):
            raise ValueError("weights archive member or expansion bound")
    with np.load(source / "weights.npz", allow_pickle=False) as arrays:
        if not arrays.files:
            raise ValueError("empty weights")
        for name in arrays.files:
            array = arrays[name]
            if array.dtype.hasobject or not np.issubdtype(array.dtype, np.number):
                raise ValueError("weights must be numeric")
    if frozen:
        _safe_file(source / "freeze.json")
        manifest = json.loads((source / "freeze.json").read_text(encoding="utf-8"))
        if manifest != {"schema": "bpb-calms21-frozen/1", "files": result}:
            raise ValueError("frozen artifact digest mismatch")
    return result


def freeze(source: Path, output: Path) -> dict[str, object]:
    before = snapshot(source)
    if output.exists():
        raise FileExistsError("fresh freeze destination required")
    output.mkdir(mode=0o700, parents=True)
    for name in FILES:
        destination = output / name
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        with (source / name).open("rb") as reader, os.fdopen(os.open(destination, flags, 0o600), "wb") as writer:
            shutil.copyfileobj(reader, writer)
    after = snapshot(source)
    if before != after or {name: digest(output / name) for name in FILES} != before:
        raise ValueError("submission mutated during freeze")
    result = {"schema": "bpb-calms21-frozen/1", "files": before}
    with os.fdopen(os.open(output / "freeze.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    snapshot(output, frozen=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.source, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
