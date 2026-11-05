"""Author-style MOT metrics with explicit frame and identity preservation."""

from __future__ import annotations

import math

import motmetrics as mm
import numpy as np

from inference import IDENTIFIER, validate_detections

METRICS = ("mota", "idf1", "recall", "num_objects", "num_predictions", "num_matches",
           "num_misses", "num_false_positives", "num_switches", "idtp", "idfp", "idfn")


def iou_distances(truth: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """Match boxes at IoU >= 0.5, with cost 1-IoU as in the author's code."""
    if len(truth) == 0 or len(predicted) == 0:
        return np.empty((len(truth), len(predicted)), dtype=np.float64)
    left_top = np.maximum(truth[:, None, :2], predicted[None, :, :2])
    right_bottom = np.minimum(truth[:, None, 2:], predicted[None, :, 2:])
    sides = np.maximum(right_bottom - left_top, 0)
    intersection = sides[..., 0] * sides[..., 1]
    truth_area = np.prod(truth[:, 2:] - truth[:, :2], axis=1)
    predicted_area = np.prod(predicted[:, 2:] - predicted[:, :2], axis=1)
    overlap = intersection / (truth_area[:, None] + predicted_area[None, :] - intersection)
    return np.where(overlap >= 0.5, 1.0 - overlap, np.nan)


def score_sequences(truth: dict[str, np.ndarray], predicted: dict[str, np.ndarray],
                    frame_counts: dict[str, int]) -> dict:
    """Pool counts across sequences, keeping their identity histories separate."""
    if (not isinstance(truth, dict) or not truth or "OVERALL" in truth or set(truth) != set(predicted)
            or set(truth) != set(frame_counts)
            or any(not isinstance(key, str) or not IDENTIFIER.fullmatch(key) for key in truth)):
        raise ValueError("exact nonempty sequence identities required")
    mm.lap.default_solver = "scipy"
    accumulators, names = [], sorted(truth)
    for name in names:
        frames = frame_counts[name]
        target = validate_detections(truth[name], frames)
        output = validate_detections(predicted[name], frames)
        if not len(target):
            raise ValueError("each scored sequence needs ground-truth objects")
        accumulator = mm.MOTAccumulator(auto_id=True)
        for index in range(frames):
            expected = target[target[:, 0] == index]
            actual = output[output[:, 0] == index]
            accumulator.update(expected[:, 1].astype(np.int64).tolist(),
                               actual[:, 1].astype(np.int64).tolist(),
                               iou_distances(expected[:, 2:], actual[:, 2:]))
        accumulators.append(accumulator)
    summary = mm.metrics.create().compute_many(accumulators, metrics=list(METRICS),
                                                names=names, generate_overall=True)

    def values(row):
        result = {name: float(row[name]) for name in METRICS[:3]}
        if any(not math.isfinite(value) for value in result.values()):
            raise ValueError("nonfinite tracking metric")
        result.update({name: int(row[name]) for name in METRICS[3:]})
        return result

    result = values(summary.loc["OVERALL"])
    result["sequences"] = len(names)
    result["frames"] = sum(frame_counts.values())
    result["iou_threshold"] = 0.5
    result["aggregation"] = "motmetrics_overall_counts_with_sequence_identity_reset"
    result["per_sequence"] = {name: values(summary.loc[name]) for name in names}
    return result
