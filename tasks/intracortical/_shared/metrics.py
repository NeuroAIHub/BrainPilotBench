"""FALCON-compatible metric arithmetic for BPB's distinct public-data profile.

Adapted from MIT-licensed snel-repo/falcon-challenge evaluator.py at
770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f, lines 653-797.
No decoder code is executed here. Inputs must already be grouped by recording
date, with same-date H1 sets and M2 runs concatenated in recording order.
"""

from __future__ import annotations

import re
from typing import Iterable

import numpy as np
from sklearn.metrics import r2_score


def _summary(per_session: dict[str, float], *, metric: str) -> dict:
    if not per_session:
        raise ValueError("At least one complete session is required")
    scores = np.asarray(list(per_session.values()), dtype=np.float64)
    if not np.isfinite(scores).all():
        raise ValueError("Non-finite session score")
    return {"metric": metric, "mean": float(np.mean(scores)),
            "std_population": float(np.std(scores)), "per_session": per_session,
            "n_sessions": len(per_session)}


def regression(sessions: dict[str, Iterable[tuple[np.ndarray, np.ndarray, np.ndarray]]]) -> dict:
    """Per-date variance-weighted R², then equal-weight date mean/std.

    Each run is (prediction[T,D], target[T,D], valid_mask[T]). The mask is
    applied before scoring; runs from the same date are concatenated first.
    """
    scores = {}
    counts = {}
    for date, runs in sorted(sessions.items()):
        predictions, targets = [], []
        for prediction, target, mask in runs:
            prediction = np.asarray(prediction)
            target = np.asarray(target)
            mask = np.asarray(mask, dtype=bool)
            if prediction.ndim != 2 or target.shape != prediction.shape or mask.shape != (len(target),):
                raise ValueError(f"Invalid regression shapes for {date}")
            if not np.isfinite(prediction[mask]).all() or not np.isfinite(target[mask]).all():
                raise ValueError(f"Non-finite regression values for {date}")
            predictions.append(prediction[mask])
            targets.append(target[mask])
        if not predictions:
            raise ValueError(f"No runs for {date}")
        prediction = np.concatenate(predictions)
        target = np.concatenate(targets)
        if len(target) < 2:
            raise ValueError(f"Too few valid timesteps for {date}")
        score = r2_score(target, prediction, multioutput="variance_weighted")
        scores[date] = float(score)
        counts[date] = len(target)
    result = _summary(scores, metric="R2_variance_weighted")
    result["valid_timesteps"] = counts
    return result


def _distance(a: list[str], b: list[str]) -> int:
    # edit_distance.SequenceMatcher.distance in the upstream scorer computes
    # Levenshtein distance. This equivalent recurrence keeps the helper small.
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[j - 1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def _words(text: str) -> list[str]:
    text = text.replace(">", " ")
    text = re.sub(r"([~,!?])", r" \1", text)
    return text.split(" ")


def handwriting(sessions: dict[str, Iterable[tuple[str, str]]]) -> dict:
    """WER/CER: sum of trial edit distances over target lengths per date.

    Trial strings are ordered (prediction, target). The official scorer uses
    this word tokenization, then reports equal-weight session means/std.
    """
    wer, cer, n_trials = {}, {}, {}
    for date, trials in sorted(sessions.items()):
        char_errors = word_errors = char_count = word_count = 0
        n = 0
        for prediction, target in trials:
            if not isinstance(prediction, str) or not isinstance(target, str):
                raise TypeError("Handwriting predictions and targets must be strings")
            char_errors += _distance(list(prediction), list(target))
            char_count += len(target)
            word_errors += _distance(_words(prediction), _words(target))
            word_count += len(_words(target))
            n += 1
        if not n or not char_count or not word_count:
            raise ValueError(f"Empty handwriting session: {date}")
        cer[date] = char_errors / char_count
        wer[date] = word_errors / word_count
        n_trials[date] = n
    return {"WER": _summary(wer, metric="WER"), "CER": _summary(cer, metric="CER"),
            "trials_per_session": n_trials}


def _minmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    low, high = float(np.min(values)), float(np.max(values))
    if not np.isfinite([low, high]).all() or high == low:
        raise ValueError("Spectrogram is non-finite or constant after masking")
    return (values - low) / (high - low)


def birdsong(sessions: dict[str, Iterable[tuple[np.ndarray, np.ndarray, np.ndarray]]]) -> dict:
    """Per-motif min-max normalized MSE, then date mean, then date mean/std.

    Each motif is (prediction[time,158], target[time,158], mask[time,158]).
    The original scorer expects exactly 700 unmasked time bins per motif.
    """
    scores, counts = {}, {}
    for date, motifs in sorted(sessions.items()):
        trial_errors = []
        for prediction, target, mask in motifs:
            prediction = np.asarray(prediction)
            target = np.asarray(target)
            mask = np.asarray(mask, dtype=bool)
            if prediction.shape != target.shape or mask.shape != target.shape or target.ndim != 2 or target.shape[1] != 158:
                raise ValueError(f"Invalid birdsong shapes for {date}")
            if int(mask.sum()) != 700 * 158:
                raise ValueError(f"Unexpected birdsong mask for {date}: {mask.sum()} cells")
            predicted = _minmax(prediction[mask].reshape(700, 158))
            observed = _minmax(target[mask].reshape(700, 158))
            trial_errors.append(float(np.mean((predicted - observed) ** 2)))
        if not trial_errors:
            raise ValueError(f"No complete motifs for {date}")
        scores[date] = float(np.mean(trial_errors))
        counts[date] = len(trial_errors)
    result = _summary(scores, metric="normalized_spectrogram_MSE")
    result["motifs_per_session"] = counts
    return result
