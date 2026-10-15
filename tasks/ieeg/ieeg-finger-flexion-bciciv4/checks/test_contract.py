"""Ordinary metric and boundary unit checks, not synthetic benchmark recordings."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "env"))
sys.path.insert(0, str(TASK / "checks"))
from common import confined, regular_unique
from score import score_subject, score_competition


class ContractTests(unittest.TestCase):
    def test_metric_identity_sign_and_ring_exclusion(self):
        x = np.arange(50, dtype=np.float64).reshape(10, 5)
        self.assertTrue(np.allclose(score_subject(x, x), 1))
        self.assertTrue(np.allclose(score_subject(-x, x), -1))
        prediction = x.copy()
        prediction[:, 3] = 100
        self.assertTrue(np.allclose(score_subject(prediction, x), 1))
        self.assertAlmostEqual(score_competition({s: x for s in ("sub1", "sub2", "sub3")},
                                                {s: x for s in ("sub1", "sub2", "sub3")}), 1)

    def test_invalid_prediction_and_subject_sets(self):
        x = np.arange(50, dtype=np.float64).reshape(10, 5)
        for bad in (np.ones_like(x), x[:-1], np.full_like(x, np.nan)):
            with self.assertRaises(ValueError):
                score_subject(bad, x)
        bad = x.copy()
        bad[:, 3] = np.inf
        with self.assertRaises(ValueError):
            score_subject(bad, x)
        with self.assertRaises(ValueError):
            score_competition({"sub1": x}, {"sub1": x})

    def test_path_confinement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "x").write_bytes(b"ordinary unit check")
            (root / "link").symlink_to(root / "x")
            self.assertEqual(confined(root, "x"), root / "x")
            for name in ("../x", "/x", "link"):
                with self.assertRaises(ValueError):
                    confined(root, name)
            with self.assertRaises(ValueError):
                regular_unique(root / "link")


if __name__ == "__main__":
    unittest.main()
