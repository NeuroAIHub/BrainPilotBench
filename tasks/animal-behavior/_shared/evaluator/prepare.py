"""Owner-only CalMS evaluator receipt and numeric packet verification."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calms_task_common import load_contract, stage_owner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, help="accepted for CLI compatibility; not read")
    args = parser.parse_args()
    os.umask(0o077)
    contract = load_contract(args.task)
    with tempfile.TemporaryDirectory(prefix="bpb-calms-owner-verify-") as temp:
        stage_owner(args.task, contract, args.data, Path(temp).resolve() / "packet")
    print(json.dumps({"task": contract["task_id"], "owner_verified": True,
                      "owner_files": len(contract["owner_files"]), "test_scored": False}, sort_keys=True))


if __name__ == "__main__":
    main()
