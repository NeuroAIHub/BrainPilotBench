"""Small arithmetic and grouping checks; no neural data or model runs."""

from __future__ import annotations

import unittest

import numpy as np
from sklearn.metrics import r2_score

from metrics import birdsong, handwriting, regression


class MetricContractTests(unittest.TestCase):
    def test_regression_combines_runs_before_equal_weight_date_mean(self) -> None:
        truth_a = np.array([[0., 0.], [1., 2.], [2., 4.]])
        truth_b = np.array([[3., 6.], [4., 8.], [5., 10.]])
        pred_a = truth_a + 0.5
        pred_b = truth_b - 0.5
        second = np.array([[0., 0.], [1., 1.], [2., 2.]])
        out = regression({
            "day1": [(pred_a, truth_a, np.array([1, 1, 1])),
                     (pred_b, truth_b, np.array([1, 1, 1]))],
            "day2": [(np.zeros_like(second), second, np.array([1, 1, 1]))],
        })
        day1 = r2_score(np.concatenate([truth_a, truth_b]), np.concatenate([pred_a, pred_b]),
                        multioutput="variance_weighted")
        day2 = r2_score(second, np.zeros_like(second), multioutput="variance_weighted")
        self.assertAlmostEqual(out["mean"], (day1 + day2) / 2)
        self.assertEqual(out["valid_timesteps"], {"day1": 6, "day2": 3})

    def test_handwriting_reports_wer_and_cer_per_date(self) -> None:
        out = handwriting({"day1": [("cat>sat", "cat>sat"), ("", "dog")],
                           "day2": [("red", "bed")]})
        self.assertEqual(out["trials_per_session"], {"day1": 2, "day2": 1})
        self.assertGreater(out["WER"]["mean"], 0)
        self.assertGreater(out["CER"]["mean"], 0)
        self.assertEqual(out["WER"]["n_sessions"], 2)

    def test_birdsong_normalizes_each_motif_independently(self) -> None:
        time = np.linspace(0, 1, 880)[:, None]
        frequency = np.linspace(0, 1, 158)[None, :]
        target = time + frequency
        prediction = target[::-1].copy()
        mask = np.zeros_like(target, dtype=bool)
        mask[100:800, :] = True
        a = birdsong({"day": [(prediction, target, mask)]})
        b = birdsong({"day": [(prediction * 9 + 15, target * 3 - 7, mask)]})
        self.assertAlmostEqual(a["mean"], b["mean"])
        self.assertEqual(a["motifs_per_session"], {"day": 1})

    def test_birdsong_rejects_partial_mask(self) -> None:
        x = np.ones((880, 158))
        with self.assertRaises(ValueError):
            birdsong({"day": [(x, x, np.ones_like(x, dtype=bool))]})


if __name__ == "__main__":
    unittest.main()
