"""Trusted MABe22 task scorer; only a flat metric leaves private owner temp."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

from mabe_inference import MODEL_FILES, evaluate, freeze_model, snapshot_model
from mabe_task_common import (digest, exact_packet, load_contract, read_json,
                              stage_evaluator, stage_public_cache, submission_dir)


def _image() -> str:
    if os.environ.get("BPB_SUBMISSION_ISOLATION") != "docker":
        raise ValueError("MABe scoring requires Docker submission isolation")
    value = os.environ.get("BPB_INFERENCE_IMAGE")
    if not value:
        raise ValueError("BPB_INFERENCE_IMAGE must pin an immutable Docker image ID")
    return value


def _metric(result: dict, metric: str) -> float:
    field = "f1" if metric == "F1" else "macro_f1"
    value = result.get("metrics", {}).get(field)
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"complete {metric} missing from isolated scorer")
    return float(value)


def _node_freeze(frozen_path: Path, contract: dict, artifacts: Path) -> Path:
    manifest = read_json(frozen_path)
    if (manifest.get("schema") != "bpb-private-submission-freeze/1"
            or manifest.get("task_id") != contract["task_id"]
            or manifest.get("task_version") != contract["task_version"]):
        raise ValueError("Node frozen submission identity mismatch")
    model = submission_dir(artifacts)
    current = snapshot_model(model, frozen=False)
    expected = {"submission/" + name: current[name]["sha256"] for name in MODEL_FILES}
    if manifest.get("files") != expected:
        raise ValueError("Node frozen files differ from complete model tree")
    return model


def _args(contract: dict, root: Path, model: Path, image: str,
          output: Path, *, public: bool) -> SimpleNamespace:
    supervised = contract["task_id"] == "mabe22-supervised-segmentation"
    if public and not supervised:
        raise ValueError("six-target representation has no public Oracle labels")
    sources = contract["source_manifests"]
    return SimpleNamespace(
        mode="supervised" if supervised else "representation",
        split="val" if public else ("test" if supervised else None),
        root=root,
        owner_labels=None if public or not supervised else root / "owner/test_labels.npz",
        expected_pose_manifest_sha256=None if public or not supervised else sources["pose_preparation_manifest.json"],
        expected_label_manifest_sha256=None if public or not supervised else sources["label_extraction_manifest.json"],
        expected_probe_manifest_sha256=None if supervised else sources["probe_preparation_manifest.json"],
        expected_packet_manifest_sha256=contract["public_manifest_sha256" if public else "evaluator_manifest_sha256"],
        submission=model, image=image, output_dir=output,
        max_clips=0, score_probe=not public and not supervised,
        run_kind="agent-submission",
    )


def score_public(task_dir: Path, artifacts: Path) -> float | None:
    contract = load_contract(task_dir)
    if contract["task_id"] == "mabe22-representation-classification":
        print("This representation task has no public Oracle labels. Use the owner-only --private scoring route after freezing the embedding model.", file=sys.stderr)
        return None
    image = _image()
    source = submission_dir(artifacts)
    before = snapshot_model(source, frozen=False)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="bpb-mabe-public-score-",
                                     dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        root = Path(temporary)
        packet, model, output = root / "packet", root / "model", root / "output"
        stage_public_cache(task_dir, contract, packet)
        freeze_model(source, model)
        output.mkdir(mode=0o700)
        result = evaluate(_args(contract, packet, model, image, output, public=True))
        exact_packet(packet, contract, evaluator=False)
        if snapshot_model(source, frozen=False) != before:
            raise ValueError("submitted model changed during public scoring")
        return _metric(result, contract["metric"])


def score_private(task_dir: Path, artifacts: Path, evaluator_root: Path,
                  frozen_path: Path) -> float:
    contract = load_contract(task_dir)
    image = _image()
    source = _node_freeze(frozen_path, contract, artifacts)
    before = snapshot_model(source, frozen=False)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="bpb-mabe-owner-score-",
                                     dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        root = Path(temporary)
        packet, model, output = root / "packet", root / "model", root / "owner-output"
        stage_evaluator(task_dir, contract, evaluator_root, packet)
        freeze_model(source, model)
        output.mkdir(mode=0o700)
        result = evaluate(_args(contract, packet, model, image, output, public=False))
        exact_packet(packet, contract, evaluator=True)
        for row in contract["owner_files"]:
            if digest(evaluator_root / row["path"]) != (row["bytes"], row["sha256"]):
                raise ValueError("prepared evaluator source changed during scoring")
        if snapshot_model(source, frozen=False) != before:
            raise ValueError("submitted model changed during private scoring")
        with (root / "owner-result.json").open("x", encoding="utf-8") as owner_result:
            json.dump(result, owner_result, sort_keys=True)
        os.chmod(root / "owner-result.json", 0o600)
        return _metric(result, contract["metric"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--public", action="store_true")
    args = parser.parse_args()
    if args.public:
        if args.data or args.frozen:
            parser.error("public scoring cannot access evaluator data")
        score = score_public(args.task, args.artifacts)
        if score is None:
            raise SystemExit(3)
    else:
        if args.data is None or args.frozen is None:
            parser.error("private scoring needs --data and --frozen")
        score = score_private(args.task, args.artifacts, args.data, args.frozen)
    contract = load_contract(args.task)
    print(">>>>> BPB_SCORES")
    print(json.dumps({contract["metric"]: score}, separators=(",", ":")))
    print("<<<<< BPB_SCORES")


if __name__ == "__main__":
    main()
