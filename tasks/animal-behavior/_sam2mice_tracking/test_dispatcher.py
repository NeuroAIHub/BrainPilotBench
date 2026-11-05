"""Private dispatcher regressions use mock scorers, never research Test data."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

DISPATCHER = Path(__file__).resolve().parents[1] / "_shared/evaluator/score.py"
CALMS_MODULES = {name: None for name in (
    "calms_freeze", "calms_runner", "calms_task_common", "calms_prepare", "ijson")}


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("animal_dispatcher_fixture", DISPATCHER)
    if spec is None or spec.loader is None:
        raise AssertionError("dispatcher could not be loaded")
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", list(sys.path)):
        spec.loader.exec_module(module)
    return module


def arguments(task_id):
    paths = (Path("/fixture/tasks") / task_id, Path("/fixture/artifacts"),
             Path("/fixture/evaluator"), Path("/fixture/submission-freeze.json"))
    command = [str(DISPATCHER)]
    for flag, path in zip(("--task", "--artifacts", "--data", "--frozen"), paths):
        command.extend((flag, str(path)))
    return command, paths


def invoke(module, task_id):
    command, paths = arguments(task_id)
    output = io.StringIO()
    with patch.object(sys, "argv", command), patch.object(sys, "path", list(sys.path)), contextlib.redirect_stdout(output):
        module.main()
    lines = output.getvalue().splitlines()
    if len(lines) != 3 or lines[0] != ">>>>> BPB_SCORES" or lines[2] != "<<<<< BPB_SCORES":
        raise AssertionError("dispatcher emitted unexpected output")
    return json.loads(lines[1]), paths


class AnimalDispatcherTest(unittest.TestCase):
    def test_help_works_without_any_site_packages(self):
        result = subprocess.run([sys.executable, "-I", "-S", str(DISPATCHER), "--help"],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--task", result.stdout)
        self.assertIn("--frozen", result.stdout)

    def test_loading_does_not_import_calms_dependencies(self):
        with patch.dict(sys.modules, CALMS_MODULES):
            module = load_dispatcher()
        self.assertTrue(callable(module.main))
        self.assertTrue(callable(module.score))
        self.assertTrue(callable(module._node_freeze))

    def test_tracking_routes_both_metrics_and_filters_details(self):
        module = load_dispatcher()
        tracking = ModuleType("score_task")
        tracking.score_private = Mock(return_value={
            "mota": -0.25, "idf1": 0.4, "private_detail": "fixture owner-only detail"})
        fallback = Mock(side_effect=AssertionError("tracking reached the CalMS scorer"))
        with patch.dict(sys.modules, {**CALMS_MODULES, "score_task": tracking, "mabe_task_score": None}), patch.object(module, "score", fallback):
            result, paths = invoke(module, "sam2mice-multi-animal-tracking")
        tracking.score_private.assert_called_once_with(*paths)
        fallback.assert_not_called()
        self.assertEqual(result, {"mota": -0.25, "idf1": 0.4})

    def test_calms_routes_preserve_f1(self):
        for task_id in ("calms21-classic-classification", "calms21-annotation-style-transfer", "calms21-few-shot-behavior"):
            with self.subTest(task_id=task_id):
                module = load_dispatcher()
                scorer = Mock(return_value=0.375)
                with patch.dict(sys.modules, {"score_task": None, "mabe_task_score": None}), patch.object(module, "score", scorer):
                    result, paths = invoke(module, task_id)
                scorer.assert_called_once_with(*paths)
                self.assertEqual(result, {"F1": 0.375})

    def test_mabe_routes_preserve_task_specific_metric_names(self):
        cases = (("mabe22-supervised-segmentation", "macro_f1"),
                 ("mabe22-representation-classification", "F1"))
        for task_id, metric in cases:
            with self.subTest(task_id=task_id):
                module = load_dispatcher()
                mabe = ModuleType("mabe_task_score")
                mabe.score_private = Mock(return_value=0.625)
                fallback = Mock(side_effect=AssertionError("MABe reached the CalMS scorer"))
                with patch.dict(sys.modules, {**CALMS_MODULES, "mabe_task_score": mabe, "score_task": None}), patch.object(module, "score", fallback):
                    result, paths = invoke(module, task_id)
                mabe.score_private.assert_called_once_with(*paths)
                fallback.assert_not_called()
                self.assertEqual(result, {metric: 0.625})

    def test_tracking_failure_propagates_without_legacy_fallback(self):
        module = load_dispatcher()
        tracking = ModuleType("score_task")
        tracking.score_private = Mock(side_effect=ValueError("fixture scoring rejection"))
        fallback = Mock(side_effect=AssertionError("unexpected legacy fallback"))
        with patch.dict(sys.modules, {**CALMS_MODULES, "score_task": tracking}), patch.object(module, "score", fallback):
            with self.assertRaisesRegex(ValueError, "fixture scoring rejection"):
                invoke(module, "sam2mice-multi-animal-tracking")
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
