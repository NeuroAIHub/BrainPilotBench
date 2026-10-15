#!/usr/bin/env python3
"""Freeze the three submitted file hashes before owner-only Test inference."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from run import REQUIRED, regular, sha256

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.submission.is_symlink() or not args.submission.is_dir():
        raise ValueError("Submission must be a directory, not a symlink")
    if args.output.exists():
        raise ValueError("Frozen receipt already exists")
    if (args.output.is_symlink() or
            args.output.resolve().is_relative_to(ROOT.parents[2].resolve())):
        raise ValueError("Frozen receipt must be outside the Git checkout")
    if set(path.name for path in args.submission.iterdir()) != set(REQUIRED):
        raise ValueError("Submission must contain exactly three required files")
    limits = {"model.py": 200_000, "config.json": 64_000, "weights.safetensors": 100_000_000}
    hashes = {}
    for name in REQUIRED:
        regular(args.submission / name, limits[name])
        hashes[name] = sha256(args.submission / name)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps({"schema": "bpb-ieeg-film-frozen-submission/1",
                                 "sha256": hashes}, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "submission_frozen", "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
