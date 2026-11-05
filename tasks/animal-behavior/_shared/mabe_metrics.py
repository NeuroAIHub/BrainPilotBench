"""Evaluator-owned MABe22 metric kernels; no dataset loading or model imports.

These functions score supplied arrays only. The caller must verify provenance,
exact video membership, frame alignment, and the owner-only label boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil, floor, isfinite

PROBE_TASKS = ("strain", "lights", "huddle", "chase", "face_sniff", "anogenital_sniff")
SEGMENTATION_CLASSES = ("chases", "huddles", "oral_contact", "oral_genital_contact")


def _binary(value: object, *, name: str) -> int:
    if type(value) not in (int, bool) or value not in (0, 1):
        raise ValueError(f"{name} must be an explicit binary label")
    return int(value)


def positive_f1(truth: Sequence[int], prediction: Sequence[int]) -> float:
    """Binary positive-class F1, with an explicit zero-denominator convention."""
    if len(truth) == 0 or len(truth) != len(prediction):
        raise ValueError("truth/prediction lengths must match and be nonempty")
    pairs = [(_binary(y, name="truth"), _binary(p, name="prediction"))
             for y, p in zip(truth, prediction)]
    tp = sum(y == 1 and p == 1 for y, p in pairs)
    fp = sum(y == 0 and p == 1 for y, p in pairs)
    fn = sum(y == 1 and p == 0 for y, p in pairs)
    denominator = 2 * tp + fp + fn
    return 0.0 if denominator == 0 else 2 * tp / denominator


def majority_vote(three_predictions: Sequence[Sequence[int]]) -> list[int]:
    """Frame-level majority vote from exactly three frozen linear probes."""
    if len(three_predictions) != 3:
        raise ValueError("exactly three classifier predictions are required")
    n = len(three_predictions[0])
    if n == 0 or any(len(p) != n for p in three_predictions):
        raise ValueError("classifier outputs must have equal nonzero length")
    return [int(sum(_binary(p[i], name="prediction") for p in three_predictions) >= 2)
            for i in range(n)]


def validate_candidate_sequence_memberships(
    evaluation_train_ids: Sequence[str], test_ids: Sequence[str],
    three_subsets: Sequence[Sequence[str]],
) -> None:
    """Check an optional sequence-sampled candidate profile, not original MABe.

    Appendix D leaves the 80% sample unit unresolved here. This sequence-ID
    check must not be used to assert equivalence to its original evaluator.
    """
    train, test = set(evaluation_train_ids), set(test_ids)
    if (not train or not test or len(train) != len(evaluation_train_ids)
            or len(test) != len(test_ids) or train & test
            or any(not isinstance(x, str) or not x for x in train | test)):
        raise ValueError("evaluation-train/test IDs must be unique, nonempty, and disjoint")
    if len(three_subsets) != 3:
        raise ValueError("exactly three frozen evaluation-train subsets are required")
    for subset in three_subsets:
        ids = set(subset)
        if len(ids) != len(subset) or not ids or not ids <= train:
            raise ValueError("subset contains duplicate, empty, or non-train IDs")
        # The frozen source implementation must determine integer rounding.
        # Accept either adjacent integer, not arbitrary subset sizes.
        if len(ids) not in (floor(0.8 * len(train)), ceil(0.8 * len(train))):
            raise ValueError("subset is not an 80% evaluation-train sample")


def score_probe_suite(
    truth: Mapping[str, Mapping[str, Sequence[int]]],
    predictions: Mapping[str, Mapping[str, Sequence[Sequence[int]]]],
) -> dict[str, object]:
    """Per-sequence positive F1, then sequence mean and equal task mean.

    This is a candidate binary-F1 interpretation, not proof of exact original
    leaderboard equivalence: official seeds, memberships, label masks and
    binary F1 convention still require an official evaluator binding.
    """
    if set(truth) != set(PROBE_TASKS) or set(predictions) != set(PROBE_TASKS):
        raise ValueError("all six classification targets must be present as one suite")
    by_task = {}
    for task in PROBE_TASKS:
        truth_sequences, pred_sequences = truth[task], predictions[task]
        if not truth_sequences or set(truth_sequences) != set(pred_sequences):
            raise ValueError(f"{task}: missing or extra sequences")
        by_sequence = {}
        for sequence_id in sorted(truth_sequences):
            if not isinstance(sequence_id, str) or not sequence_id:
                raise ValueError("invalid sequence ID")
            voted = majority_vote(pred_sequences[sequence_id])
            by_sequence[sequence_id] = positive_f1(truth_sequences[sequence_id], voted)
        by_task[task] = {"f1": sum(by_sequence.values()) / len(by_sequence),
                         "sequences": len(by_sequence), "by_sequence": by_sequence}
    score = sum(result["f1"] for result in by_task.values()) / len(PROBE_TASKS)
    return {"f1": score, "tasks": by_task}


def score_supervised_segmentation(
    truth_by_video: Mapping[str, Sequence[Sequence[int]]],
    predictions_by_video: Mapping[str, Sequence[Sequence[float]]],
    label_mask_by_video: Mapping[str, Sequence[bool]],
    *, threshold: float = 0.5,
) -> dict[str, object]:
    """Pooled positive F1 for four labels, macro averaged over classes.

    label_mask is supplied by the owner-side evaluator. It replicates the
    reference preprocessor's positive-frame eligibility: any of the four
    grouped behaviors is positive. Excluded all-zero frames can include
    annotated negatives as well as unknown/unannotated frames. This score
    therefore cannot measure false alarms on background-only frames. The
    mask must never be used to select Agent Test inputs or exposed to Agent.
    """
    if (not 0 < threshold < 1 or not isfinite(threshold)
            or not truth_by_video or set(truth_by_video) != set(predictions_by_video)
            or set(truth_by_video) != set(label_mask_by_video)):
        raise ValueError("invalid threshold or mismatched video IDs")
    counts = [[0, 0, 0] for _ in SEGMENTATION_CLASSES]  # TP, FP, FN
    scored_frames = 0
    for video_id in sorted(truth_by_video):
        if not isinstance(video_id, str) or not video_id:
            raise ValueError("invalid video ID")
        truth, pred, mask = (truth_by_video[video_id], predictions_by_video[video_id],
                             label_mask_by_video[video_id])
        if len(truth) == 0 or len(truth) != len(pred) or len(truth) != len(mask):
            raise ValueError(f"{video_id}: frame count mismatch")
        for y_row, p_row, eligible in zip(truth, pred, mask):
            if type(eligible) is not bool or len(y_row) != 4 or len(p_row) != 4:
                raise ValueError("mask must be boolean; each frame needs four labels/scores")
            ys = [_binary(y, name="truth") for y in y_row]
            ps = []
            for score in p_row:
                if type(score) not in (float, int) or not isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("prediction scores must be finite probabilities")
                ps.append(int(score >= threshold))
            if not eligible:
                continue
            if not any(ys):
                raise ValueError("eligible frames must have a source-positive grouped behavior")
            scored_frames += 1
            for i, (y, p) in enumerate(zip(ys, ps)):
                counts[i][0] += y == 1 and p == 1
                counts[i][1] += y == 0 and p == 1
                counts[i][2] += y == 1 and p == 0
    if scored_frames == 0:
        raise ValueError("no evaluator-eligible annotated frames")
    by_class = {}
    for name, (tp, fp, fn) in zip(SEGMENTATION_CLASSES, counts):
        denom = 2 * tp + fp + fn
        by_class[name] = 0.0 if denom == 0 else 2 * tp / denom
    return {"macro_f1": sum(by_class.values()) / 4, "f1_by_class": by_class,
            "eligible_frames": scored_frames, "videos": len(truth_by_video)}
