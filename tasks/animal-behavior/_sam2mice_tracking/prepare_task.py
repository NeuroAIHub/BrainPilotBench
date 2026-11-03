"""Stage the verified Train and Valid packets in an Agent workspace."""
import argparse
import json
import os
from pathlib import Path

from task_common import load_contract, stage_public_workspace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    contract = load_contract(args.task)
    stage_public_workspace(args.task, contract, args.output)
    print(json.dumps({"task_id": contract["task_id"], "public_prepared": True,
                      "data_roles": ["train", "valid"], "image_size": contract["image_size"]}))


if __name__ == "__main__":
    main()
