#!/usr/bin/env python3
"""Calculate the Dataset 4 score from three sets of five finger trajectories."""

from __future__ import annotations

import numpy as np


SCORED_FINGERS = (0, 1, 2, 4)


def score_subject(predicted: np.ndarray, observed: np.ndarray) -> list[float]:
    predicted = np.asarray(predicted, dtype=np.float64)
    observed = np.asarray(observed, dtype=np.float64)
    if predicted.ndim != 2 or predicted.shape != observed.shape or predicted.shape[1] != 5:
        raise ValueError("Predictions and observations must have the same [samples, 5] shape")
    if predicted.shape[0] < 2:
        raise ValueError("At least two samples are required")
    if not np.isfinite(predicted).all() or not np.isfinite(observed).all():
        raise ValueError("All five trajectories must be finite, including the unscored ring finger")
    scores: list[float] = []
    for finger in SCORED_FINGERS:
        prediction = predicted[:, finger]
        truth = observed[:, finger]
        if not np.isfinite(prediction).all() or not np.isfinite(truth).all():
            raise ValueError(f"Nonfinite values for scored finger {finger}")
        if np.ptp(prediction) == 0 or np.ptp(truth) == 0:
            raise ValueError(f"Constant trajectory for scored finger {finger}")
        correlation = float(np.corrcoef(prediction, truth)[0, 1])
        if not np.isfinite(correlation):
            raise ValueError("Correlation is undefined for the supplied numerical scale")
        scores.append(correlation)
    return scores


def score_competition(predictions: dict[str, np.ndarray], observations: dict[str, np.ndarray]) -> float:
    subjects = {"sub1", "sub2", "sub3"}
    if set(predictions) != subjects or set(observations) != subjects:
        raise ValueError("Exactly sub1, sub2, and sub3 are required")
    correlations = [
        score
        for subject in sorted(subjects)
        for score in score_subject(predictions[subject], observations[subject])
    ]
    return float(np.mean(correlations))
