"""Trusted public Valid scorer for source-only CalMS benchmark tasks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from calms_freeze import freeze
from calms_runner import evaluate
from calms_task_common import load_contract, stage_public_cache, submission_dir


def score(task_dir: Path, artifacts: Path) -> float | None:
    contract = load_contract(task_dir)
    if contract["source_task"] == "task3" and contract["validation_unavailable_groups"]:
        print("Task3 public Valid lacks a disjoint intromission sequence; seven-target F1 is unscored. "
              "Private Test requires the separate owner workflow.", file=sys.stderr)
        return None
    if os.environ.get("BPB_SUBMISSION_ISOLATION") != "docker":
        raise ValueError("public scoring requires Docker submission isolation")
    image = os.environ.get("BPB_INFERENCE_IMAGE")
    if not image:
        raise ValueError("BPB_INFERENCE_IMAGE must pin an immutable Docker image")
    source = submission_dir(artifacts)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="bpb-calms-public-score-") as temp:
        root = Path(temp).resolve()
        packet, frozen = root / "packet", root / "frozen"
        stage_public_cache(task_dir, contract, packet)
        freeze(source, frozen)
        result = evaluate(None, frozen, image, None, "valid", "agent-submission",
                          packet, contract["public_manifest_sha256"])
        metric = result["metrics"].get("f1")
        if not isinstance(metric, (int, float)) or isinstance(metric, bool) or not 0 <= metric <= 1:
            raise ValueError("complete public F1 missing")
        return float(metric)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    value = score(args.task, args.artifacts)
    if value is None:
        raise SystemExit(3)
    print(">>>>> BPB_SCORES")
    print(json.dumps({"F1": value}, separators=(",", ":")))
    print("<<<<< BPB_SCORES")


if __name__ == "__main__":
    main()
