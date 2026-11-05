"""Scorer regressions use synthetic unit fixtures, never benchmark inputs."""

from __future__ import annotations

import unittest

import numpy as np

from inference import validate_detections
from metrics import iou_distances, score_sequences


def track(frames=4, identity=0, box=(0.1, 0.1, 0.3, 0.3)):
    return np.asarray([[index, identity, *box] for index in range(frames)], dtype=np.float64)


class TrackingMetricTest(unittest.TestCase):
    def score(self, truth, predicted, frames=4):
        return score_sequences({"sequence-a": truth}, {"sequence-a": predicted}, {"sequence-a": frames})

    def test_perfect_prediction_and_global_id_permutation(self):
        truth = np.concatenate((track(identity=0), track(identity=1, box=(.6, .6, .8, .8))))
        predicted = truth.copy()
        predicted[:, 1] = np.where(predicted[:, 1] == 0, 41, 17)
        result = self.score(truth, predicted)
        self.assertEqual(result["mota"], 1.0)
        self.assertEqual(result["idf1"], 1.0)
        self.assertEqual(result["num_objects"], 8)

    def test_single_identity_switch_reduces_both_metrics(self):
        truth, predicted = track(), track()
        predicted[2:, 1] = 9
        result = self.score(truth, predicted)
        self.assertEqual(result["num_switches"], 1)
        self.assertEqual(result["mota"], .75)
        self.assertEqual(result["idf1"], .5)
        self.assertEqual(result["recall"], 1.0)

    def test_false_positives_allow_negative_mota(self):
        predicted = np.concatenate([track(identity=identity) for identity in range(4)])
        result = self.score(track(), predicted)
        self.assertEqual(result["mota"], -2.0)
        self.assertEqual(result["num_false_positives"], 12)

    def test_empty_output_is_valid_and_scores_zero(self):
        result = self.score(track(), np.empty((0, 6), dtype=np.float64))
        self.assertEqual(result["mota"], 0.0)
        self.assertEqual(result["idf1"], 0.0)
        self.assertEqual(result["num_misses"], 4)

    def test_iou_half_is_inclusive(self):
        distance = iou_distances(np.array([[0., 0., 1., 1.]]),
                                 np.array([[0., 0., .5, 1.], [0., 0., .499, 1.]]))
        self.assertEqual(distance[0, 0], .5)
        self.assertTrue(np.isnan(distance[0, 1]))
        self.assertEqual(self.score(track(box=(0., 0., 1., 1.)),
                                    track(box=(0., 0., .5, 1.)))["mota"], 1.0)

    def test_sequence_boundaries_reset_identity_and_overall_pools_counts(self):
        truth = {"first": track(frames=4), "second": track(frames=1)}
        output = {"first": track(frames=4, identity=17), "second": track(frames=1, identity=83)}
        result = score_sequences(truth, output, {"first": 4, "second": 1})
        self.assertEqual(result["idf1"], 1.)
        self.assertEqual(result["num_switches"], 0)
        output["second"] = np.empty((0, 6), dtype=np.float64)
        result = score_sequences(truth, output, {"first": 4, "second": 1})
        self.assertEqual(result["mota"], .8)
        self.assertAlmostEqual(result["idf1"], 8 / 9)

    def test_no_independent_sort_or_zip_drops_missing_predictions(self):
        predicted = track()[[0, 3]]
        result = self.score(track(), predicted)
        self.assertEqual(result["num_misses"], 2)
        self.assertEqual(result["mota"], .5)

    def test_rows_are_canonicalized_and_bad_outputs_rejected(self):
        np.testing.assert_array_equal(validate_detections(track()[::-1], 4), track())
        cases = [np.concatenate([track(), track()]), track().astype(np.int64),
                 np.array([[0., 0., 0., 0., 0., 1.]]),
                 np.array([[0., 0., 0., 0., np.inf, 1.]]),
                 np.array([[0.5, 0., 0., 0., 1., 1.]]),
                 np.array([[0., -1., 0., 0., 1., 1.]]),
                 np.array([[0., 2**31, 0., 0., 1., 1.]]),
                 np.array([[4., 0., 0., 0., 1., 1.]])]
        for value in cases:
            with self.subTest(value=value.shape), self.assertRaises(ValueError):
                validate_detections(value, 4)
        excess = np.array([[0, identity, 0., 0., 1., 1.] for identity in range(65)], dtype=float)
        with self.assertRaises(ValueError):
            validate_detections(excess, 4)
        distinct = np.array([[identity // 64, identity, 0., 0., 1., 1.]
                             for identity in range(1025)], dtype=float)
        with self.assertRaises(ValueError):
            validate_detections(distinct, 128)

    def test_missing_or_empty_truth_sequences_rejected(self):
        with self.assertRaises(ValueError):
            score_sequences({"one": track()}, {}, {"one": 4})
        with self.assertRaises(ValueError):
            self.score(np.empty((0, 6), dtype=np.float64), track())
        with self.assertRaises(ValueError):
            score_sequences({"OVERALL": track()}, {"OVERALL": track()}, {"OVERALL": 4})


if __name__ == "__main__":
    unittest.main()
