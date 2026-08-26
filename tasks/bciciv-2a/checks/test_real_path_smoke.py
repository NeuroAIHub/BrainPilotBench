#!/usr/bin/env python3
"""Small evaluator-only smoke test for the real BCI preprocessing/train path."""

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


RUNNER = _load("bci_real_path_runner", "train_and_infer.py")
EVALUATOR = _load("bci_real_path_evaluator", "evaluate_external.py")


def _raw_fixture(*, labeled: bool, trials: int = 8) -> mne.io.RawArray:
    sfreq = 250.0
    stride_s = 7.0
    total_s = trials * stride_s
    times = np.arange(int(total_s * sfreq)) / sfreq
    data = np.vstack([
        (4.0e-6 + channel * 0.05e-6) * np.sin(2 * np.pi * (8 + channel % 4) * times)
        for channel in range(RUNNER.N_CH)
    ])
    info = mne.create_info(
        [f"EEG-{channel:02d}" for channel in range(RUNNER.N_CH)],
        sfreq=sfreq,
        ch_types="eeg",
    )
    raw = mne.io.RawArray(data, info, verbose="ERROR")
    onsets: list[float] = []
    descriptions: list[str] = []
    for trial in range(trials):
        start = trial * stride_s
        onsets.extend([start, start + RUNNER.CUE_OFFSET_S])
        descriptions.extend([RUNNER.TRIAL_START_ANNOTATION, str(769 + trial % 4) if labeled else RUNNER.UNKNOWN_ANNOTATION])
    raw.set_annotations(mne.Annotations(onsets, [0.0] * len(onsets), descriptions))
    return raw


class RealPathSmokeTest(unittest.TestCase):
    def test_preprocess_import_train_infer_and_metric_path(self):
        X_train, y_train = RUNNER.preprocess_raw(_raw_fixture(labeled=True), "synthetic-T", expected_trials=8)
        X_test, hidden = RUNNER.preprocess_raw(_raw_fixture(labeled=False), "synthetic-E", expected_trials=8)
        self.assertEqual(X_train.shape, (8, 22, 512))
        self.assertEqual(X_train.dtype, np.float32)
        np.testing.assert_array_equal(y_train, [1, 2, 3, 4, 1, 2, 3, 4])
        self.assertIsNone(hidden)

        with tempfile.TemporaryDirectory(prefix="bpb-bci-real-smoke-") as tmp:
            model_path = Path(tmp) / "mi_agent_model.py"
            model_path.write_text(
                "import torch\n"
                "import torch.nn as nn\n"
                "class MIAgentModel(nn.Module):\n"
                "    def __init__(self):\n"
                "        super().__init__()\n"
                "        self.head = nn.Conv1d(22, 4, kernel_size=1)\n"
                "    def forward(self, x):\n"
                "        return self.head(x).mean(dim=-1)\n",
                encoding="utf-8",
            )
            predictions = RUNNER.train_from_arrays(
                model_source=model_path,
                X_train_all=X_train,
                y_train_all=y_train,
                X_test=X_test,
                train_idx=np.arange(4),
                val_idx=np.arange(4, 8),
                device=torch.device("cpu"),
                max_epochs=1,
                batch_size=4,
            )

        self.assertEqual(predictions.shape, (8,))
        self.assertTrue(set(predictions.tolist()).issubset({1, 2, 3, 4}))
        metrics = EVALUATOR.per_subject_metrics(y_train, predictions)
        self.assertTrue(all(np.isfinite(value) for value in metrics))

    def test_metric_fixture_has_exact_golden_values(self):
        labels = np.asarray([1, 2, 3, 4, 1, 2, 3, 4])
        self.assertEqual(EVALUATOR.per_subject_metrics(labels, labels), (1.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
