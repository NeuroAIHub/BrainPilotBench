"""Copy only Node-verified CalMS public files into an Agent workspace."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from calms_task_common import load_contract, stage_public_workspace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh workspace/data directory; public/ is created beneath it")
    args = parser.parse_args()
    os.umask(0o077)
    contract = load_contract(args.task)
    stage_public_workspace(args.task, contract, args.output)
    print(json.dumps({"task": contract["task_id"], "public_prepared": True,
                      "train": contract["public_counts"]["train"],
                      "valid": contract["public_counts"]["valid"],
                      "validation_unavailable_groups": contract["validation_unavailable_groups"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
