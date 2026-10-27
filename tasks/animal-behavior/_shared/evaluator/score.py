"""Trusted CalMS private Test scorer; only a flat F1 sentinel leaves owner temp."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calms_freeze import FILES, freeze, snapshot
from calms_runner import evaluate
from calms_task_common import load_contract, read_json, stage_owner, submission_dir, digest


def _node_freeze(frozen_path: Path, contract: dict, artifacts: Path) -> Path:
    manifest = read_json(frozen_path)
    if (manifest.get("schema") != "bpb-private-submission-freeze/1"
            or manifest.get("task_id") != contract["task_id"]
            or manifest.get("task_version") != contract["task_version"]):
        raise ValueError("Node frozen submission identity mismatch")
    source = submission_dir(artifacts)
    current = snapshot(source)
    expected = {"submission/" + name: current[name]["sha256"] for name in FILES}
    if manifest.get("files") != expected:
        raise ValueError("Node frozen mapping differs from the complete artifact tree")
    return source


def score(task_dir: Path, artifacts: Path, evaluator_root: Path, frozen_path: Path) -> float:
    contract = load_contract(task_dir)
    if os.environ.get("BPB_SUBMISSION_ISOLATION") != "docker":
        raise ValueError("private scoring requires Docker submission isolation")
    image = os.environ.get("BPB_INFERENCE_IMAGE")
    if not image:
        raise ValueError("BPB_INFERENCE_IMAGE must pin an immutable Docker image")
    source = _node_freeze(frozen_path, contract, artifacts)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="bpb-calms-owner-score-") as temp:
        root = Path(temp).resolve()
        packet, submission = root / "packet", root / "submission"
        stage_owner(task_dir, contract, evaluator_root, packet)
        freeze(source, submission)
        result = evaluate(None, submission, image, None, "test", "agent-submission",
                          packet, contract["owner_manifest_sha256"])
        for item in contract["owner_files"]:
            if digest(evaluator_root / item["path"]) != (item["bytes"], item["sha256"]):
                raise ValueError("evaluator source changed during private scoring")
        if snapshot(source) != snapshot(submission, frozen=True):
            raise ValueError("submitted artifacts changed during private scoring")
        metric = result["metrics"].get("f1")
        if not isinstance(metric, (int, float)) or isinstance(metric, bool) or not math.isfinite(metric) or not 0 <= metric <= 1:
            raise ValueError("complete seven-group private F1 missing")
        report_dir = root / "owner"
        report_dir.mkdir(mode=0o700)
        with os.fdopen(os.open(report_dir / "private-result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump(result, stream, sort_keys=True)
        return float(metric)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    args = parser.parse_args()
    if args.task.name in ("mabe22-supervised-segmentation", "mabe22-representation-classification"):
        from mabe_task_score import score_private
        value = score_private(args.task, args.artifacts, args.data, args.frozen)
        metric = "macro_f1" if args.task.name == "mabe22-supervised-segmentation" else "F1"
    else:
        value = score(args.task, args.artifacts, args.data, args.frozen)
        metric = "F1"
    print(">>>>> BPB_SCORES")
    print(json.dumps({metric: value}, separators=(",", ":")))
    print("<<<<< BPB_SCORES")


if __name__ == "__main__":
    main()
