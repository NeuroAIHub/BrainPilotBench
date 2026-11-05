"""Software-only fixtures for candidate metric kernels; no real MABe data."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "mabe_metrics", Path(__file__).with_name("mabe_metrics.py"))
assert SPEC and SPEC.loader
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


class ProbeMetricsTest(unittest.TestCase):
    def test_three_votes_and_per_sequence_average(self) -> None:
        # The first sequence has F1=1; the second has F1=0. A pooled
        # frame score would differ because the sequences have unequal length.
        truth = {task: {"long": [1, 1, 0, 0], "short": [1]}
                 for task in metrics.PROBE_TASKS}
        pred = {task: {"long": [[1, 1, 0, 0]] * 3,
                       "short": [[0], [1], [0]]}
                for task in metrics.PROBE_TASKS}
        result = metrics.score_probe_suite(truth, pred)
        self.assertEqual(result["f1"], 0.5)
        self.assertEqual(result["tasks"]["strain"]["sequences"], 2)

    def test_requires_three_classifiers_and_complete_suite(self) -> None:
        with self.assertRaises(ValueError):
            metrics.majority_vote([[1], [1]])
        with self.assertRaises(ValueError):
            metrics.score_probe_suite({}, {})

    def test_frozen_memberships_must_be_supplied_and_disjoint(self) -> None:
        train = [f"tr{i}" for i in range(5)]
        subsets = [train[:4], train[1:], train[0:3] + train[4:]]
        metrics.validate_candidate_sequence_memberships(train, ["te"], subsets)
        with self.assertRaises(ValueError):
            metrics.validate_candidate_sequence_memberships(train, ["tr0"], subsets)
        with self.assertRaises(ValueError):
            metrics.validate_candidate_sequence_memberships(train, ["te"], [train] * 3)


class SegmentationMetricsTest(unittest.TestCase):
    def test_owner_mask_excludes_unannotated_frames(self) -> None:
        truth = {"v": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0]]}
        pred = {"v": [[0.9, 0.1, 0.1, 0.1], [0.1, 0.9, 0.1, 0.1],
                      [0.9, 0.9, 0.9, 0.9]]}
        result = metrics.score_supervised_segmentation(truth, pred,
                                                        {"v": [True, True, False]})
        self.assertEqual(result["eligible_frames"], 2)
        self.assertEqual(result["f1_by_class"]["chases"], 1.0)
        self.assertEqual(result["f1_by_class"]["huddles"], 1.0)
        self.assertEqual(result["macro_f1"], 0.5)

    def test_missing_mask_and_no_annotations_rejected(self) -> None:
        truth = {"v": [[0, 0, 0, 0]]}
        pred = {"v": [[0.1, 0.1, 0.1, 0.1]]}
        with self.assertRaises(ValueError):
            metrics.score_supervised_segmentation(truth, pred, {})
        with self.assertRaises(ValueError):
            metrics.score_supervised_segmentation(truth, pred, {"v": [False]})
        with self.assertRaises(ValueError):
            metrics.score_supervised_segmentation(truth, pred, {"v": [True]})

    def test_invalid_truth_or_probability_rejected_even_if_masked(self) -> None:
        with self.assertRaises(ValueError):
            metrics.score_supervised_segmentation(
                {"v": [[-1, 0, 0, 0]]}, {"v": [[0.1] * 4]}, {"v": [False]})
        with self.assertRaises(ValueError):
            metrics.score_supervised_segmentation(
                {"v": [[1, 0, 0, 0]]}, {"v": [[float("nan")] * 4]}, {"v": [True]})


if __name__ == "__main__":
    unittest.main()
