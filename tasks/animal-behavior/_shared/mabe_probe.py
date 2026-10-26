"""Owner-side six-target MABe22 Ridge probe for frozen numeric embeddings.

Input contract: one <video_id>.npz per submission sequence with a finite
float embedding of shape [1800, 1..128]. The source-pose option is a disclosed
reference embedding only. Agent code and Test labels never share a directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable

import numpy as np

from mabe_metrics import PROBE_TASKS, score_probe_suite, validate_candidate_sequence_memberships


def source_pose_embedding(root: Path, video_id: str) -> np.ndarray:
    with np.load(root / "public" / "probe_pose" / f"{video_id}.npz", allow_pickle=False) as data:
        pose = data["keypoints"]
    if pose.shape != (1800, 3, 12, 2):
        raise ValueError(f"invalid source pose: {video_id}")
    # Source-provided tracked coordinates; no labels enter this transform.
    return pose.reshape(1800, 72).astype(np.float64) / 224.0


def embedding_file(directory: Path, video_id: str) -> np.ndarray:
    with np.load(directory / f"{video_id}.npz", allow_pickle=False) as data:
        if set(data.files) != {"embedding"}:
            raise ValueError(f"embedding file must contain only 'embedding': {video_id}")
        values = data["embedding"]
    if (values.ndim != 2 or values.shape[0] != 1800 or not 1 <= values.shape[1] <= 128
            or values.dtype.kind != "f" or not np.isfinite(values).all()):
        raise ValueError(f"invalid embedding shape or value: {video_id}")
    return values.astype(np.float64)


def validate_embedding_directory(root: Path, directory: Path) -> dict:
    expected = {path.stem for path in (root / "public" / "probe_pose").glob("*.npz")}
    observed = {path.stem for path in directory.glob("*.npz")}
    if len(expected) != 1830 or observed != expected:
        raise ValueError("embedding submission must contain the exact 1,830 submission IDs")
    dimensions = set()
    for video_id in sorted(expected):
        dimensions.add(embedding_file(directory, video_id).shape[1])
        if len(dimensions) > 1:
            raise ValueError("all embedding dimensions must match")
    return {"videos": 1830, "dimensions": dimensions.pop()}


def labels(root: Path, task: str, role: str) -> dict[str, np.ndarray]:
    owner = role != "SubmissionTrain"
    path = root / ("owner" if owner else "evaluator") / "probe_labels" / f"{task}_{role}.npz"
    with np.load(path, allow_pickle=False) as data:
        result = {video_id: data[video_id].copy() for video_id in data.files}
    if any(x.shape != (1800,) or x.dtype.kind not in "uib" or not np.isin(x, (0, 1)).all()
           for x in result.values()):
        raise ValueError("invalid numeric label array")
    return result


def fit_ridge(
    train_ids: list[str], truth: dict[str, np.ndarray],
    embedding: Callable[[str], np.ndarray], alpha: float = 1.0,
) -> np.ndarray:
    """Weighted RidgeClassifier equivalent: targets -1/+1 and balanced weights.

    Normal equations are accumulated per sequence to bound peak memory.
    The intercept is not penalized. Class frequencies use only this subset.
    """
    n_positive = sum(int(truth[video_id].sum()) for video_id in train_ids)
    n_total = 1800 * len(train_ids)
    n_negative = n_total - n_positive
    if n_positive == 0 or n_negative == 0:
        raise ValueError("probe subset lacks one binary class")
    balance = np.array((n_total / (2 * n_negative), n_total / (2 * n_positive)))
    gram = rhs = None
    dimension = None
    for video_id in train_ids:
        x = embedding(video_id)
        if x.ndim != 2 or x.shape[0] != 1800 or not np.isfinite(x).all():
            raise ValueError(f"invalid embedding: {video_id}")
        if dimension is None:
            dimension = x.shape[1]
            gram = np.zeros((dimension + 1, dimension + 1), dtype=np.float64)
            rhs = np.zeros(dimension + 1, dtype=np.float64)
        elif x.shape[1] != dimension:
            raise ValueError("embedding dimensions differ between sequences")
        x = np.column_stack((x, np.ones(1800)))
        y = truth[video_id].astype(np.int8)
        weight = balance[y]
        gram += x.T @ (x * weight[:, None])
        rhs += x.T @ ((2 * y - 1) * weight)
    assert gram is not None and rhs is not None
    gram.flat[::len(gram) + 1] += alpha
    gram[-1, -1] -= alpha
    return np.linalg.solve(gram, rhs)


def predict(coef: np.ndarray, embedding: np.ndarray) -> list[int]:
    if embedding.shape != (1800, len(coef) - 1):
        raise ValueError("embedding dimension or frame count mismatch")
    return ((embedding @ coef[:-1] + coef[-1]) >= 0).astype(int).tolist()


def profile(root: Path) -> dict:
    result = json.loads((root / "public" / "probe_profile.json").read_text())
    if result["name"] != "BrainPilotBench-MABe22-six-classification-sequence-probe-v1":
        raise ValueError("unknown probe profile")
    if set(result["tasks"]) != set(PROBE_TASKS):
        raise ValueError("probe task mismatch")
    for task, entry in result["tasks"].items():
        validate_candidate_sequence_memberships(entry["train_ids"],
                                                entry["test1_ids"] + entry["test2_ids"],
                                                entry["three_probe_train_subsets"])
    return result


def score_owner_test(root: Path, embedding: Callable[[str], np.ndarray]) -> dict:
    """Owner-only entry point; the Agent runtime must never call this method."""
    frozen = profile(root)
    truth_all, predictions_all = {}, {}
    for task in PROBE_TASKS:
        entry = frozen["tasks"][task]
        train_truth = labels(root, task, "SubmissionTrain")
        test1_truth = labels(root, task, "publicTest")
        test2_truth = labels(root, task, "privateTest")
        if (set(train_truth) != set(entry["train_ids"])
                or set(test1_truth) != set(entry["test1_ids"])
                or set(test2_truth) != set(entry["test2_ids"])):
            raise ValueError(f"label/profile membership mismatch: {task}")
        models = [fit_ridge(subset, train_truth, embedding)
                  for subset in entry["three_probe_train_subsets"]]
        test_truth = {**test1_truth, **test2_truth}
        truth_all[task] = {video_id: row.astype(int).tolist()
                           for video_id, row in test_truth.items()}
        predictions_all[task] = {video_id: [predict(coef, embedding(video_id)) for coef in models]
                                 for video_id in test_truth}
    return score_probe_suite(truth_all, predictions_all)


def internal_validation(root: Path, embedding: Callable[[str], np.ndarray],
                        max_train_videos: int = 0) -> dict:
    """Public-train-only smoke test; no publicTest/privateTest label file read."""
    frozen = profile(root)
    results = {}
    for task in PROBE_TASKS:
        entry = frozen["tasks"][task]
        truth = labels(root, task, "SubmissionTrain")
        ids = entry["train_ids"]
        if set(truth) != set(ids):
            raise ValueError("internal validation membership mismatch")
        # A deterministic internal holdout distinct from the frozen Test probe.
        ranked = sorted(ids, key=lambda video_id: hashlib.sha256(
            f"bpb-mabe-internal-validation-v1/{task}/{video_id}".encode()).digest())
        if max_train_videos:
            ranked = ranked[:max_train_videos]
        holdout_count = max(1, len(ranked) // 10)
        val_ids, fit_ids = ranked[:holdout_count], ranked[holdout_count:]
        if len(fit_ids) < 5:
            raise ValueError("too few internal fit sequences")
        # Three 80% sequence subsets of only the internal fit IDs. These are
        # separate from the published Test subsets and are used only for QA.
        subsets = []
        for seed in (0, 1, 2):
            ordered = sorted(fit_ids, key=lambda video_id: hashlib.sha256(
                f"bpb-mabe-internal-probe-v1/{task}/{seed}/{video_id}".encode()).digest())
            subsets.append(ordered[:4 * len(fit_ids) // 5])
        models = [fit_ridge(subset, truth, embedding) for subset in subsets]
        per_sequence = {}
        from mabe_metrics import majority_vote, positive_f1
        for video_id in val_ids:
            voted = majority_vote([predict(model, embedding(video_id)) for model in models])
            per_sequence[video_id] = positive_f1(truth[video_id].astype(int).tolist(), voted)
        results[task] = {"f1": sum(per_sequence.values()) / len(per_sequence),
                         "fit_videos": len(fit_ids), "validation_videos": len(val_ids)}
    return {"f1": sum(row["f1"] for row in results.values()) / 6,
            "tasks": results, "scope": "public SubmissionTrain internal holdout only",
            "max_train_videos": max_train_videos}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--embeddings", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--internal-validation", action="store_true")
    mode.add_argument("--owner-test", action="store_true")
    parser.add_argument("--max-train-videos", type=int, default=0)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.embeddings:
        validate_embedding_directory(args.root, args.embeddings)
        embedding = lambda video_id: embedding_file(args.embeddings, video_id)
    else:
        embedding = lambda video_id: source_pose_embedding(args.root, video_id)
    if args.owner_test and args.max_train_videos:
        raise ValueError("max-train-videos is only for internal validation")
    result = (internal_validation(args.root, embedding, args.max_train_videos)
              if args.internal_validation else score_owner_test(args.root, embedding))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"f1": result["f1"], "scope": result.get("scope", "owner Test")}))


if __name__ == "__main__":
    main()
