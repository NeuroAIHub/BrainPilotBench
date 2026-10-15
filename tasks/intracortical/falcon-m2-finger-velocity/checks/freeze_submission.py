"""Owner-only artifact receipt. Does not execute a model or read evaluation data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from score import PROFILE, REQUIRED, stage_submission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Use a new owner-controlled receipt path")
    if not args.output.parent.is_dir() or any(p.is_symlink() for p in (args.output.parent, *args.output.parent.parents)):
        parser.error("Receipt parent must be an existing ordinary owner directory")
    with tempfile.TemporaryDirectory(prefix="bpb-m2-freeze-") as temporary:
        staged = Path(temporary) / "submission"
        hashes = stage_submission(args.artifacts, staged, None, test=False)
        receipt = {"schema": "bpb-m2-frozen-artifact/1", "profile": PROFILE,
                   "files": {name: {"sha256": hashes[name], "bytes": (staged / name).stat().st_size}
                             for name in REQUIRED}}
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(receipt, output, indent=2, sort_keys=True)
        output.write("\n")
    args.output.chmod(0o600)
    print(json.dumps({"receipt": str(args.output), "model_executed": False, "evaluation_data_read": False}))


if __name__ == "__main__":
    main()
