#!/usr/bin/env python3
"""Structure and metric checks; fabricated numbers are not research results."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((ROOT / "protocol.json").read_text())
SPEC = importlib.util.spec_from_file_location("film_score", ROOT / "checks" / "score.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FilmContractTests(unittest.TestCase):
    def test_global_split_has_each_block_once(self):
        groups = PROTOCOL["block_assignment"]
        self.assertEqual(sorted(sum(groups.values(), [])), list(range(1, 14)))
        conditions = PROTOCOL["expected_conditions"]
        self.assertEqual(
            [conditions[index - 1] for index in groups["test"]].count("speech"), 2
        )
        self.assertEqual(
            [conditions[index - 1] for index in groups["test"]].count("music"), 2
        )

    def test_block_first_subject_balanced_accuracy(self):
        blocks = [5, 2, 9, 12]
        labels = [0, 1, 0, 1]
        probabilities = [[0.1, 0.1, 0.1, 0.9], [0.6], [0.8], [0.8]]
        windows = []
        predictions = {}
        for block, label, values in zip(blocks, labels, probabilities):
            for index, value in enumerate(values):
                identifier = f"opaque-{block}-{index}"
                windows.append({
                    "id": identifier, "subject": "opaque-subject", "block": block,
                    "label": label, "channel_types": ["ECOG"],
                })
                predictions[identifier] = value
        binding = {"schema": "bpb-ieeg-film-evaluator-binding/1", "windows": windows}
        result = MODULE.score(predictions, binding)
        self.assertEqual(result["value"], 0.75)
        self.assertEqual(result["participants"], 1)
        self.assertNotEqual(result["value"], result["secondary_window_balanced_accuracy"])
        with self.assertRaisesRegex(ValueError, "exactly once"):
            MODULE.score({**predictions, "extra": 0.5}, binding)
        with self.assertRaisesRegex(ValueError, "finite"):
            MODULE.score({**predictions, "opaque-5-0": float("nan")}, binding)
        with self.assertRaisesRegex(ValueError, "frozen Test split"):
            MODULE.score(predictions, {**binding, "windows": [{**windows[0], "block": 4}] + windows[1:]})
        with self.assertRaisesRegex(ValueError, "frozen movie block"):
            MODULE.score(predictions, {**binding, "windows": [{**windows[0], "label": 1}] + windows[1:]})


if __name__ == "__main__":
    unittest.main()
