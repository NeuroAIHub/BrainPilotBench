#!/usr/bin/env python3
"""Small evaluator-only smoke test for the real Sleep preprocessing/train path."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import mne
import numpy as np
import torch


def _load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load("sleep_real_path_runner", "train_and_infer.py")
EVALUATOR = _load("sleep_real_path_evaluator", "evaluate_external.py")


def _recording_fixture(epochs: int = 15) -> tuple[mne.io.RawArray, mne.Annotations]:
    sfreq = RUNNER.SFREQ_TARGET
    times = np.arange(epochs * RUNNER.N_TIMES) / sfreq
    data = (12.0e-6 * np.sin(2 * np.pi * 10.0 * times))[None, :]
    info = mne.create_info([RUNNER.EEG_CHANNEL], sfreq=sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info, verbose="ERROR")
    stages = ["Sleep stage W", "Sleep stage 1", "Sleep stage 2", "Sleep stage 3", "Sleep stage R"]
    annotations = mne.Annotations(
        onset=[index * RUNNER.WINDOW_S for index in range(epochs)],
        duration=[RUNNER.WINDOW_S] * epochs,
        description=[stages[index % len(stages)] for index in range(epochs)],
    )
    return raw, annotations


class RealPathSmokeTest(unittest.TestCase):
    def test_preprocess_import_train_infer_and_metric_path(self):
        raw, annotations = _recording_fixture()
        X, y = RUNNER.preprocess_recording(raw, annotations, "synthetic-sleep.edf")
        self.assertEqual(X.shape, (15, 1, 3000))
        self.assertEqual(X.dtype, np.float32)
        np.testing.assert_array_equal(y, [0, 1, 2, 3, 4] * 3)

        with tempfile.TemporaryDirectory(prefix="bpb-sleep-real-smoke-") as tmp:
            model_path = Path(tmp) / "sleep_agent_model.py"
            model_path.write_text(
                "import torch\n"
                "import torch.nn as nn\n"
                "class SleepAgentModel(nn.Module):\n"
                "    def __init__(self):\n"
                "        super().__init__()\n"
                "        self.head = nn.Conv1d(1, 5, kernel_size=1)\n"
                "    def forward(self, x):\n"
                "        return self.head(x).mean(dim=-1)\n",
                encoding="utf-8",
            )
            model = RUNNER.fit_model_from_arrays(
                model_source=model_path,
                Xtr=X[:5], ytr=y[:5],
                Xva=X[5:10], yva=y[5:10],
                device=torch.device("cpu"),
                max_epochs=1,
                batch_size=5,
            )
            predictions = RUNNER.predict_array(model, X[10:], torch.device("cpu"), batch_size=5)

        self.assertEqual(predictions.shape, (5,))
        metrics = EVALUATOR.compute_metrics(y[10:], predictions)
        self.assertEqual(set(metrics), {
            "score", "test_kappa", "test_accuracy", "test_balanced_accuracy", "test_macro_f1",
            "wake_recall", "n1_recall", "n2_recall", "n3_recall", "rem_recall",
        })
        self.assertTrue(all(np.isfinite(value) for value in metrics.values()))

    def test_metric_fixture_has_exact_golden_values(self):
        labels = np.asarray([0, 1, 2, 3, 4])
        metrics = EVALUATOR.compute_metrics(labels, labels)
        self.assertTrue(all(value == 1.0 for value in metrics.values()))


if __name__ == "__main__":
    unittest.main()
