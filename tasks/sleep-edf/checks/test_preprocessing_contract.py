#!/usr/bin/env python3
"""Unit tests for the sleep-edf scorer's frozen preprocessing contract."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

import numpy as np


def _load_runner_module():
    """Import contract helpers without requiring the evaluator's torch/MNE stack."""
    mne = types.ModuleType("mne")
    mne.set_log_level = lambda _level: None
    mne.io = types.SimpleNamespace()

    torch = types.ModuleType("torch")
    torch_nn = types.ModuleType("torch.nn")
    torch.nn = torch_nn

    names = ("mne", "torch", "torch.nn")
    previous = {name: sys.modules.get(name) for name in names}
    try:
        sys.modules["mne"] = mne
        sys.modules["torch"] = torch
        sys.modules["torch.nn"] = torch_nn
        path = Path(__file__).with_name("train_and_infer.py")
        spec = importlib.util.spec_from_file_location("sleep_edf_train_and_infer", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


RUNNER = _load_runner_module()


class PreprocessingContractTest(unittest.TestCase):
    def test_label_mapping_merges_stage3_and_stage4_into_n3(self):
        mapping = RUNNER.LABEL_MAPPING
        self.assertEqual(
            mapping,
            {
                "Sleep stage W": 0,
                "Sleep stage 1": 1,
                "Sleep stage 2": 2,
                "Sleep stage 3": 3,
                "Sleep stage 4": 3,
                "Sleep stage R": 4,
            },
        )
        # The five model logits map directly to labels 0..4 in W/N1/N2/N3/REM order.
        self.assertEqual(sorted(set(mapping.values())), [0, 1, 2, 3, 4])

    def test_mne_volts_are_scaled_to_float32_microvolts(self):
        volts = np.asarray([1.0e-6, -22.9e-6], dtype=np.float64)

        microvolts = RUNNER._to_microvolts(volts)

        self.assertEqual(microvolts.dtype, np.float32)
        np.testing.assert_allclose(microvolts, [1.0, -22.9], rtol=1e-6)

    def test_model_interface_is_30s_at_100hz(self):
        self.assertEqual(RUNNER.WINDOW_S, 30.0)
        self.assertEqual(RUNNER.SFREQ_TARGET, 100.0)
        self.assertEqual(RUNNER.N_TIMES, 3000)
        self.assertEqual(RUNNER.N_CLASSES, 5)
        self.assertEqual(RUNNER.EEG_CHANNEL, "EEG Fpz-Cz")
        self.assertEqual(RUNNER.CROP_WAKE_MINS, 30)

    def test_training_hyperparameters_match_prompt(self):
        self.assertEqual(RUNNER.LR, 1e-3)
        self.assertEqual(RUNNER.BATCH_SIZE, 64)
        self.assertEqual(RUNNER.MAX_EPOCHS, 20)
        self.assertEqual(RUNNER.EARLY_STOP_PATIENCE, 5)


if __name__ == "__main__":
    unittest.main()
