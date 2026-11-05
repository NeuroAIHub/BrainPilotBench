"""Copy only Node-verified MABe public files into an Agent workspace."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mabe_task_common import load_contract, stage_public


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    contract = load_contract(args.task)
    stage_public(args.task, contract, args.output)
    print(json.dumps({"task": contract["task_id"], "public_prepared": True,
                      "counts": contract["counts"], "profile": contract["profile"]}, sort_keys=True))


if __name__ == "__main__":
    main()
