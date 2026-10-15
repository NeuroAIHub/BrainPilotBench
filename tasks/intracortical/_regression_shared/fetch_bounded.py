"""Fetch the pinned M1 and M2 assets one at a time with a file deadline.

This maintainer command uses the frozen preparation manifest. It makes one
attempt per file. A partial download does not become a verified source file.
"""

from __future__ import annotations

import argparse
import importlib.util
import signal
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PREPARATION = HERE.parent / "_preparation" / "prepare.py"
sys.path.insert(0, str(PREPARATION.parent))
spec = importlib.util.spec_from_file_location("falcon_prepare", PREPARATION)
assert spec is not None and spec.loader is not None
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def expired(_signum, _frame):
    raise TimeoutError("file transfer exceeded its deadline")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--limit-bytes", type=int, default=18_000_000_000)
    parser.add_argument("--file-seconds", type=int, default=1200)
    args = parser.parse_args()
    if args.file_seconds < 1 or args.file_seconds > 3600:
        parser.error("file deadline must be between 1 and 3600 seconds")
    manifest = prepare.load_manifest()
    tasks = ("falcon-m1-emg", "falcon-m2-finger-velocity")
    selected = [asset for asset in manifest["assets"] if asset["task_id"] in tasks]
    total = sum(asset["size_bytes"] for asset in selected)
    if total > args.limit_bytes:
        parser.error(f"frozen selection {total} bytes exceeds limit {args.limit_bytes}")
    root = prepare.safe_destination(args.dest)
    signal.signal(signal.SIGALRM, expired)
    print(f"source bytes={total}; files={len(selected)}", flush=True)
    for asset in selected:
        access = "evaluator" if asset["role"] == "test" else "public"
        destination = root / access
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        if access == "evaluator":
            destination.chmod(0o700)
        print(f"start {asset['task_id']} {asset['role']} {asset['asset_id']} {asset['size_bytes']}", flush=True)
        signal.alarm(args.file_seconds)
        try:
            outcome = prepare.fetch_one(destination, asset)
        finally:
            signal.alarm(0)
        print(f"done {asset['asset_id']} {outcome}", flush=True)


if __name__ == "__main__":
    main()
