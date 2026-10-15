"""Record a fixed H2/B1 submission before separate owner Test scoring."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from export import PROFILE, TASKS, digest, outside_git


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=TASKS)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    submission = args.artifacts / "submission"
    files = {}
    for name, limit in (("model.py", 1_000_000), ("config.json", 256_000),
                        ("weights.safetensors", 100_000_000)):
        path = submission / name
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > limit:
            raise ValueError("Submission has an unsafe or oversized file")
        files[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    output_path = outside_git(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as out:
        json.dump({"schema": f"bpb-{args.task}-frozen-artifact/1", "task_id": TASKS[args.task],
                   "profile": PROFILE, "files": files}, out, sort_keys=True, indent=2)
        out.write("\n")
    print(json.dumps({"frozen_artifact": str(output_path), "files": files}, sort_keys=True))


if __name__ == "__main__":
    main()
