#!/usr/bin/env python3
"""Unit tests for the bciciv-2a scorer's frozen preprocessing contract."""

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

    sys.modules["mne"] = mne
    sys.modules["torch"] = torch
    sys.modules["torch.nn"] = torch_nn

    path = Path(__file__).with_name("train_and_infer.py")
    spec = importlib.util.spec_from_file_location("bci2a_train_and_infer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner_module()


def _session_events(*, labeled: bool, sfreq: float = 250.0):
    ann_dict = {"768": 1}
    if labeled:
        ann_dict.update({"769": 2, "770": 3, "771": 4, "772": 5})
    else:
        ann_dict["783"] = 6
    rows = []
    labels = []
    cue_offset = int(round(2.0 * sfreq))
    trial_stride = int(round(8.0 * sfreq))
    for trial in range(288):
        start = trial * trial_stride
        rows.append([start, 0, ann_dict["768"]])
        if labeled:
            label = trial % 4 + 1
            labels.append(label)
            rows.append([start + cue_offset, 0, ann_dict[str(768 + label)]])
        else:
            rows.append([start + cue_offset, 0, ann_dict["783"]])
    return np.asarray(rows, dtype=np.int64), ann_dict, np.asarray(labels)


class PreprocessingContractTest(unittest.TestCase):
    def test_training_epochs_are_anchored_at_labeled_mi_cues(self):
        events, ann_dict, expected_labels = _session_events(labeled=True)

        cue_events, labels = RUNNER._resolve_cue_events(
            events, ann_dict, 250.0, "A01T.gdf"
        )

        np.testing.assert_array_equal(cue_events[:, 0], events[1::2, 0])
        np.testing.assert_array_equal(labels, expected_labels)
        np.testing.assert_array_equal(
            np.bincount(labels, minlength=5)[1:], np.full(4, 72)
        )

    def test_evaluation_epochs_are_anchored_at_unknown_mi_cues(self):
        events, ann_dict, _ = _session_events(labeled=False)

        cue_events, labels = RUNNER._resolve_cue_events(
            events, ann_dict, 250.0, "A01E.gdf"
        )

        np.testing.assert_array_equal(cue_events[:, 0], events[1::2, 0])
        self.assertIsNone(labels)
        self.assertTrue(np.all(cue_events[:, 2] == ann_dict["783"]))

    def test_wrong_cue_offset_is_rejected(self):
        events, ann_dict, _ = _session_events(labeled=True)
        events[1, 0] -= 250

        with self.assertRaisesRegex(RuntimeError, "not 2 s after trial starts"):
            RUNNER._resolve_cue_events(events, ann_dict, 250.0, "A01T.gdf")

    def test_mne_volts_are_scaled_to_float32_microvolts(self):
        volts = np.asarray([1.0e-6, -12.5e-6], dtype=np.float64)

        microvolts = RUNNER._to_microvolts(volts)

        self.assertEqual(microvolts.dtype, np.float32)
        np.testing.assert_allclose(microvolts, [1.0, -12.5])

    def test_half_open_model_interface_has_512_samples(self):
        self.assertEqual(RUNNER.N_TIMES, 512)
        self.assertEqual(RUNNER.TMAX - RUNNER.TMIN, 4.0)
        self.assertEqual(RUNNER.SFREQ_TARGET, 128.0)


if __name__ == "__main__":
    unittest.main()
