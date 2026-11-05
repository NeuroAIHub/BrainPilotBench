"""Trusted, prediction-only CalMS21 frame metrics.

The caller supplies ground truth from an evaluator-owned array and numeric scores
from an isolated prediction process. This module never imports candidate code.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np


CLASSIC_VOCAB = {"attack": 0, "investigation": 1, "mount": 2, "other": 3}
NEW_BEHAVIORS = (
    "approach", "disengaged", "groom", "intromission",
    "mount_attempt", "sniff_face", "whiterearing",
)


def _labels(value: object, n_classes: int) -> np.ndarray:
    labels = np.asarray(value)
    if labels.ndim != 1 or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("ground truth must be a one-dimensional integer array")
    if labels.size == 0 or np.any((labels < 0) | (labels >= n_classes)):
        raise ValueError("ground truth contains an empty or out-of-vocabulary sequence")
    return labels


def _predictions(value: object, n_frames: int, n_classes: int) -> np.ndarray:
    scores = np.asarray(value)
    if scores.shape != (n_frames, n_classes) or not np.issubdtype(scores.dtype, np.floating):
        raise ValueError(f"predictions must have shape ({n_frames}, {n_classes})")
    if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
        raise ValueError("predictions must be finite probabilities in [0, 1]")
    if not np.allclose(scores.sum(axis=1), 1.0, rtol=0, atol=1e-5):
        raise ValueError("prediction rows must sum to one")
    return np.argmax(scores, axis=1)


def _f1(truth: np.ndarray, prediction: np.ndarray, positive: int) -> float:
    true_positive = int(np.count_nonzero((truth == positive) & (prediction == positive)))
    false_positive = int(np.count_nonzero((truth != positive) & (prediction == positive)))
    false_negative = int(np.count_nonzero((truth == positive) & (prediction != positive)))
    denominator = 2 * true_positive + false_positive + false_negative
    return 0.0 if denominator == 0 else 2 * true_positive / denominator


def score_sequences(
    truth_by_id: Mapping[str, object], scores_by_id: Mapping[str, object],
    *, task: str, vocab: Mapping[str, int],
) -> dict[str, object]:
    """Score one Task1/2 group or one Task3 behavior across complete sequences.

    Exactly matching sequence IDs and the source vocabulary are required. Task1/2
    include `other` frames in each one-vs-rest denominator but do not average
    `other` as a fourth class. Task3 averages only the positive behavior F1.
    """
    if not isinstance(truth_by_id, Mapping) or not isinstance(scores_by_id, Mapping):
        raise ValueError("truth and predictions must be sequence mappings")
    if not truth_by_id or set(truth_by_id) != set(scores_by_id):
        raise ValueError("missing or unexpected sequence predictions")
    if task in ("task1", "task2"):
        if dict(vocab) != CLASSIC_VOCAB:
            raise ValueError("classic CalMS21 class mapping mismatch")
        n_classes, positives = 4, (0, 1, 2)
        names = ("attack", "investigation", "mount")
    elif task == "task3":
        positive_names = [name for name in NEW_BEHAVIORS if name in vocab]
        if len(positive_names) != 1 or dict(vocab) != {"other": 0, positive_names[0]: 1}:
            raise ValueError("Task3 behavior mapping mismatch")
        n_classes, positives, names = 2, (1,), (positive_names[0],)
    else:
        raise ValueError("unknown CalMS21 task")

    labels, predictions = [], []
    for sequence_id in sorted(truth_by_id):
        if not isinstance(sequence_id, str) or not sequence_id:
            raise ValueError("invalid sequence ID")
        truth = _labels(truth_by_id[sequence_id], n_classes)
        prediction = _predictions(scores_by_id[sequence_id], truth.size, n_classes)
        labels.append(truth)
        predictions.append(prediction)
    truth_all = np.concatenate(labels)
    pred_all = np.concatenate(predictions)
    by_class = {name: _f1(truth_all, pred_all, label)
                for name, label in zip(names, positives)}
    return {"f1": float(np.mean(list(by_class.values()))),
            "f1_by_class": by_class, "frames": int(truth_all.size),
            "sequences": len(labels)}


def score_task2(
    truth_by_group: Mapping[str, Mapping[str, object]],
    scores_by_group: Mapping[str, Mapping[str, object]],
    vocab_by_group: Mapping[str, Mapping[str, int]],
) -> dict[str, object]:
    """Average independent annotator-group Task2 scores with equal group weight."""
    expected = {f"annotator-id_{index}" for index in range(1, 6)}
    if set(truth_by_group) != expected or set(scores_by_group) != expected or set(vocab_by_group) != expected:
        raise ValueError("missing or unexpected annotator group")
    groups = {group: score_sequences(truth_by_group[group], scores_by_group[group],
                                     task="task2", vocab=vocab_by_group[group])
              for group in sorted(truth_by_group)}
    return {"f1": float(np.mean([result["f1"] for result in groups.values()])),
            "groups": groups}


def score_task3(
    truth_by_behavior: Mapping[str, Mapping[str, object]],
    scores_by_behavior: Mapping[str, Mapping[str, object]],
    vocab_by_behavior: Mapping[str, Mapping[str, int]],
) -> dict[str, object]:
    """Average seven independent binary positive-class F1 scores."""
    expected = set(NEW_BEHAVIORS)
    if set(truth_by_behavior) != expected or set(scores_by_behavior) != expected or set(vocab_by_behavior) != expected:
        raise ValueError("all seven Task3 behaviors are required")
    behaviors = {name: score_sequences(truth_by_behavior[name], scores_by_behavior[name],
                                       task="task3", vocab=vocab_by_behavior[name])
                 for name in NEW_BEHAVIORS}
    return {"f1": float(np.mean([result["f1"] for result in behaviors.values()])),
            "behaviors": behaviors}
