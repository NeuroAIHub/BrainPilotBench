"""Trusted tracking scorer and fixed Train-only reference entry point."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import stat
import tempfile

from task_common import (MODEL_FILES, exact_packet, load_contract, read_json, safe_path,
                         stage_evaluator, stage_public_cache, submission_dir, verify_locks)


def _image() -> str:
    if os.environ.get("BPB_SUBMISSION_ISOLATION") != "docker":
        raise ValueError("tracking scoring requires Docker submission isolation")
    image = os.environ.get("BPB_INFERENCE_IMAGE")
    if not image:
        raise ValueError("an immutable inference image is required")
    return image


def node_freeze_path(path: Path) -> Path:
    """Resolve the known macOS Node temporary-root alias only."""
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("linked private freeze is forbidden")
    temporary = Path(tempfile.gettempdir()).absolute()
    if (path.name == "submission-freeze.json" and path.parent.name.startswith("bpb-owner-score-")
            and path.parent.parent == temporary):
        info = path.parent.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError("Node freeze directory must be owner-only")
        return path.parent.resolve(strict=True) / path.name
    return path


def _node_frozen_model(task_dir: Path, artifacts: Path, frozen_path: Path) -> Path:
    from inference import snapshot_model
    contract = load_contract(task_dir)
    frozen_path = node_freeze_path(frozen_path)
    safe_path(frozen_path, owner=True)
    manifest = read_json(frozen_path)
    if (manifest.get("schema") != "bpb-private-submission-freeze/1"
            or manifest.get("task_id") != contract["task_id"]
            or manifest.get("task_version") != contract["task_version"]):
        raise ValueError("Node model freeze identity differs")
    source = submission_dir(artifacts)
    hashes = snapshot_model(source)
    if manifest.get("files") != {"submission/" + name: hashes[name]["sha256"] for name in MODEL_FILES}:
        raise ValueError("Node model freeze does not bind the submitted files")
    return source


def _evaluate(packet: Path, rows: list[dict], model: Path, image: str) -> dict:
    from inference import evaluate_sequences, load_truth
    from metrics import score_sequences
    predictions = evaluate_sequences(packet, rows, model, image)
    if set(predictions) != {row["id"] for row in rows}:
        raise ValueError("prediction sequence IDs differ")
    truth, frame_counts = {}, {}
    for row in rows:
        truth[row["id"]] = load_truth(packet / row["label_path"], expected_bytes=row["label_bytes"],
                                     expected_sha256=row["label_sha256"], frames=row["frames"])
        frame_counts[row["id"]] = row["frames"]
    result = score_sequences(truth, predictions, frame_counts)
    for metric in ("mota", "idf1"):
        value = result.get(metric)
        if (type(value) not in (float, int) or not math.isfinite(value)
                or value > 1 or (metric == "idf1" and value < 0)):
            raise ValueError("invalid tracking metric")
    return result


def score_public(task_dir: Path, artifacts: Path) -> dict:
    from inference import snapshot_model
    contract = load_contract(task_dir)
    image, source = _image(), submission_dir(artifacts)
    before = snapshot_model(source)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="bpb-tracking-public-", dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        packet = Path(temporary) / "packet"
        manifest = stage_public_cache(task_dir, contract, packet)
        rows = [row for row in manifest["sequences"] if row["split"] == "valid"]
        if not rows:
            raise ValueError("complete Valid sequences required")
        result = _evaluate(packet, rows, source, image)
        exact_packet(packet, contract, evaluator=False)
        if snapshot_model(source) != before:
            raise ValueError("submission changed during scoring")
        return result


def score_private(task_dir: Path, artifacts: Path, evaluator_root: Path, frozen_path: Path) -> dict:
    """Return trusted metrics to the owner CLI, which writes scores.private.json."""
    from inference import snapshot_model
    contract = load_contract(task_dir)
    image = _image()
    source = _node_frozen_model(task_dir, artifacts, frozen_path)
    before = snapshot_model(source)
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="bpb-tracking-owner-", dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        packet = Path(temporary) / "packet"
        manifest = stage_evaluator(task_dir, contract, evaluator_root, packet)
        rows = manifest["sequences"]
        if any(row["split"] != "test" for row in rows):
            raise ValueError("owner role differs")
        result = _evaluate(packet, rows, source, image)
        exact_packet(packet, contract, evaluator=True)
        exact_packet(evaluator_root, contract, evaluator=True, receipt=True)
        if snapshot_model(source) != before:
            raise ValueError("submission changed during private scoring")
        return result


def build_reference(task_dir: Path, output: Path, *, public_dir: Path | None = None) -> dict:
    from reference import fit_reference
    contract = load_contract(task_dir)
    verify_locks(task_dir, contract)
    if public_dir is not None:
        manifest = exact_packet(public_dir, contract, evaluator=False)
        result = fit_reference([row for row in manifest["sequences"] if row["split"] == "train"], output, root=public_dir)
        exact_packet(public_dir, contract, evaluator=False)
        return result
    with tempfile.TemporaryDirectory(prefix="bpb-tracking-reference-", dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        packet = Path(temporary) / "packet"
        manifest = stage_public_cache(task_dir, contract, packet)
        result = fit_reference([row for row in manifest["sequences"] if row["split"] == "train"], output, root=packet)
        exact_packet(packet, contract, evaluator=False)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--reference", action="store_true")
    parser.add_argument("--public-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.reference:
        if args.output is None or args.public or args.artifacts or args.data or args.frozen:
            parser.error("reference requires --output and only an optional --public-dir")
        print(json.dumps(build_reference(args.task, args.output, public_dir=args.public_dir), sort_keys=True))
        return
    if args.artifacts is None or args.output or args.public_dir:
        parser.error("scoring requires --artifacts and cannot use reference arguments")
    if args.public:
        if args.data or args.frozen:
            parser.error("public scoring cannot access evaluator data")
        result = score_public(args.task, args.artifacts)
    else:
        if args.data is None or args.frozen is None:
            parser.error("private scoring requires --data and --frozen")
        result = score_private(args.task, args.artifacts, args.data, args.frozen)
    print(">>>>> BPB_SCORES")
    print(json.dumps({name: result[name] for name in ("mota", "idf1")}, separators=(",", ":")))
    print("<<<<< BPB_SCORES")


if __name__ == "__main__":
    main()
