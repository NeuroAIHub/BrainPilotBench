#!/usr/bin/env python3
"""Calculate block-first Test balanced accuracy from evaluator-only metadata.

This module reads numeric predictions. It never imports or runs a submitted
model. No evaluator binding or Test arrays ship with this candidate.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

PROTOCOL = json.loads((Path(__file__).resolve().parents[1] / "protocol.json").read_text())
TEST_BLOCKS = set(PROTOCOL["block_assignment"]["test"])
CONDITIONS = PROTOCOL["expected_conditions"]


def score(predictions: dict[str, float], binding: dict) -> dict:
    """Score a private binding with records: id, subject, block, label, types."""
    if binding.get("schema") != "bpb-ieeg-film-evaluator-binding/1":
        raise ValueError("Unrecognized private evaluator binding")
    windows = binding.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("The private binding needs window records")
    ids = [row["id"] for row in windows]
    if len(ids) != len(set(ids)) or set(predictions) != set(ids):
        raise ValueError("Predictions must contain each evaluator window ID exactly once")
    for item in predictions.values():
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("Every prediction must be a numeric probability")
        if not math.isfinite(item) or not 0 <= item <= 1:
            raise ValueError("Every prediction must be finite and in [0,1]")
    groups = defaultdict(list)
    subjects = defaultdict(set)
    for row in windows:
        if row.get("label") not in (0, 1):
            raise ValueError("Every Test label must be 0 or 1")
        subject, block = row["subject"], row["block"]
        if isinstance(block, bool) or not isinstance(block, int) or block not in TEST_BLOCKS:
            raise ValueError("The binding includes a block outside the frozen Test split")
        expected_label = PROTOCOL["condition_codes"][CONDITIONS[block - 1]]
        if row["label"] != expected_label:
            raise ValueError("A Test label differs from the frozen movie block condition")
        groups[(subject, block)].append(row)
        subjects[subject].add(block)
    subject_scores = {}
    subject_window_scores = {}
    strata = defaultdict(list)
    for subject, blocks in subjects.items():
        if blocks != TEST_BLOCKS:
            raise ValueError(f"Subject {subject} needs the four frozen Test blocks")
        hits = {0: [], 1: []}
        window_hits = {0: [], 1: []}
        types = set()
        for block in blocks:
            rows = groups[(subject, block)]
            labels = {row["label"] for row in rows}
            if len(labels) != 1:
                raise ValueError("A Test block has mixed condition labels")
            label = labels.pop()
            mean_probability = sum(predictions[row["id"]] for row in rows) / len(rows)
            hits[label].append(int((mean_probability >= 0.5) == label))
            window_hits[label].extend(
                int((predictions[row["id"]] >= 0.5) == label) for row in rows
            )
            for row in rows:
                types.update(row.get("channel_types", []))
        if len(hits[0]) != 2 or len(hits[1]) != 2:
            raise ValueError("Each subject needs two music and two speech Test blocks")
        subject_score = (sum(hits[0]) / 2 + sum(hits[1]) / 2) / 2
        subject_scores[subject] = subject_score
        subject_window_scores[subject] = (
            sum(window_hits[0]) / len(window_hits[0])
            + sum(window_hits[1]) / len(window_hits[1])
        ) / 2
        for electrode_type in ("ECOG", "SEEG"):
            if electrode_type in types:
                strata[electrode_type].append(subject_score)
    return {
        "metric": "balanced_accuracy",
        "value": sum(subject_scores.values()) / len(subject_scores),
        "participants": len(subject_scores),
        "secondary_window_balanced_accuracy": sum(subject_window_scores.values()) / len(subject_scores),
        "descriptive_electrode_strata": {
            electrode_type: {"participants": len(values), "mean": sum(values) / len(values)}
            for electrode_type, values in sorted(strata.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--binding", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(score(json.loads(args.predictions.read_text()), json.loads(args.binding.read_text())), indent=2))


if __name__ == "__main__":
    main()
