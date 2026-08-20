#!/usr/bin/env python3
"""Regression tests for TOPS-fMRI chance-aligned score aggregation."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np


def _load_evaluator():
    path = Path(__file__).with_name("evaluate_external.py")
    spec = importlib.util.spec_from_file_location("tops_evaluate_external", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EVALUATOR = _load_evaluator()


class MetricsTest(unittest.TestCase):
    def test_constant_predictions_have_zero_headline_score(self):
        labels4 = np.asarray([0.0, 1.0, 2.0, 3.0])
        labels5 = np.asarray([0, 0, 1, 1])
        constant = np.ones(4)
        rs = {condition: EVALUATOR.pearson_r(constant, labels4) for condition in EVALUATOR.STUDY4_CONDITIONS}
        aucs = {site: EVALUATOR.auc_score(constant, labels5) for site in EVALUATOR.STUDY5_SITES}

        score, study4_score, study5_score = EVALUATOR.aggregate_scores(rs, aucs)

        self.assertEqual(study4_score, 0.0)
        self.assertEqual(study5_score, 0.0)
        self.assertEqual(score, 0.0)
        self.assertTrue(all(value == 0.5 for value in aucs.values()))

    def test_auc_transform_preserves_endpoints_and_raw_auc(self):
        self.assertEqual(EVALUATOR.chance_centered_auc(0.4), 0.0)
        self.assertEqual(EVALUATOR.chance_centered_auc(0.5), 0.0)
        self.assertEqual(EVALUATOR.chance_centered_auc(0.75), 0.5)
        self.assertEqual(EVALUATOR.chance_centered_auc(1.0), 1.0)

    def test_perfect_subscores_aggregate_to_one(self):
        rs = {condition: 1.0 for condition in EVALUATOR.STUDY4_CONDITIONS}
        aucs = {site: 1.0 for site in EVALUATOR.STUDY5_SITES}
        self.assertEqual(EVALUATOR.aggregate_scores(rs, aucs), (1.0, 1.0, 1.0))

    def test_preserved_reference_raw_metrics_define_the_v02_formula_baseline(self):
        # Raw diagnostic definitions did not change, so the preserved v0
        # reference run can be re-aggregated without touching private labels.
        rs = {
            "SBP_SP": 0.20498944132494254,
            "SBP_REST": -0.04236652622803082,
            "CBP_SP": 0.2011219156462409,
            "CBP_REST": 0.15696926637239392,
        }
        aucs = {"JP": 0.7777777777777778, "UK": 0.7370242214532872}
        score, study4_score, study5_score = EVALUATOR.aggregate_scores(rs, aucs)
        self.assertAlmostEqual(study4_score, 0.14077015583589433)
        self.assertAlmostEqual(study5_score, 0.514801999231065)
        self.assertAlmostEqual(score, 0.32778607753347966)


if __name__ == "__main__":
    unittest.main()
