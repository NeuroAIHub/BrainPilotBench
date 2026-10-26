"""Private preparation lifecycle tests with synthetic source bytes only."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("bpb_private_prepare", Path(__file__).with_name("prepare.py"))
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "evaluator"
        self.data.mkdir()
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.source = {"evaluator_data.zip": {"sha256": "a" * 64, "bytes": 5}}

    def test_direct_task_does_not_prepare_or_read_private_arrays(self):
        task = PREPARE.ROOT / "tasks/ieeg/ieeg-finger-flexion-bciciv4"
        with patch.object(PREPARE, "verify_materialization", return_value=self.source):
            result, status = PREPARE.prepare(task, self.data, self.cache)
        self.assertEqual((result, status), (self.data.resolve(), "direct"))
        self.assertFalse((self.data / "prepared").exists())

    def test_materialization_requires_matching_owner_completion_marker(self):
        task = PREPARE.ROOT / "tasks/ieeg/ieeg-finger-flexion-bciciv4"
        lock_path = task / "evaluator.lock"
        lock = json.loads(lock_path.read_text())
        marker = {"schema": "bpb-prepared-evaluator/1", "task_id": lock["task_id"],
                  "revision": lock["revision"],
                  "evaluator_lock_sha256": PREPARE.DISPATCH.digest(lock_path),
                  "files": len(lock["files"]), "prepared_at": "synthetic"}
        receipt = self.data / ".bpb-evaluator.json"
        receipt.write_text(json.dumps(marker))
        with patch.object(PREPARE, "locked_sources", return_value=self.source):
            self.assertEqual(PREPARE.verify_materialization(task, self.data), self.source)
            marker["evaluator_lock_sha256"] = "0" * 64
            receipt.write_text(json.dumps(marker))
            with self.assertRaisesRegex(ValueError, "marker differs"):
                PREPARE.verify_materialization(task, self.data)

    def test_brain_age_receipt_controls_reuse_and_detects_tamper(self):
        task = PREPARE.ROOT / "tasks/mri/brain-age-mri"

        def staged(command, **_):
            destination = Path(command[command.index("--destination") + 1])
            destination.mkdir()
            (destination / "subjects.csv").write_text("synthetic")
            (destination / "PREPARED.json").write_text("{}")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(PREPARE, "verify_materialization", return_value=self.source), patch.object(
                PREPARE.subprocess, "run", side_effect=staged) as run:
            result, status = PREPARE.prepare(task, self.data, self.cache)
            self.assertEqual((result, status), (self.data.resolve() / "prepared", "prepared"))
            receipt = json.loads((result / PREPARE.RECEIPT).read_text())
            self.assertEqual(receipt["schema"], PREPARE.SCHEMA)
            self.assertEqual(receipt["sources"], self.source)
            self.assertEqual((result / "subjects.csv").stat().st_mode & 0o777, 0o600)
            self.assertEqual(result.stat().st_mode & 0o777, 0o700)
            self.assertEqual(PREPARE.prepare(task, self.data, self.cache), (result, "reused"))
            self.assertEqual(run.call_count, 1)
            (result / "subjects.csv").write_text("changed")
            with self.assertRaisesRegex(ValueError, "differs"):
                PREPARE.verify_prepared(task, self.data)
            with self.assertRaisesRegex(ValueError, "differs"):
                PREPARE.prepare(task, self.data, self.cache)
            self.assertEqual(run.call_count, 1)

    def test_existing_receipt_rejects_source_and_transform_drift(self):
        task = PREPARE.ROOT / "tasks/mri/brain-age-mri"
        prepared = self.data / "prepared"
        prepared.mkdir()
        (prepared / "subjects.csv").write_text("synthetic")
        payload = PREPARE.receipt_value(PREPARE.BRAIN, self.source,
                                        PREPARE.transform_file(task, PREPARE.BRAIN), prepared)
        PREPARE.DISPATCH.write_new_json(prepared / PREPARE.RECEIPT, payload)
        with patch.object(PREPARE, "verify_materialization", return_value=self.source):
            self.assertEqual(PREPARE.verify_prepared(task, self.data)[0], prepared.resolve())
        altered = {"evaluator_data.zip": {"sha256": "b" * 64, "bytes": 5}}
        with patch.object(PREPARE, "verify_materialization", return_value=altered):
            with self.assertRaisesRegex(ValueError, "differs"):
                PREPARE.verify_prepared(task, self.data)
        payload["transform_sha256"] = "c" * 64
        (prepared / PREPARE.RECEIPT).write_text(json.dumps(payload))
        with patch.object(PREPARE, "verify_materialization", return_value=self.source):
            with self.assertRaisesRegex(ValueError, "differs"):
                PREPARE.verify_prepared(task, self.data)

    def test_worm_uses_pinned_cache_and_private_stage(self):
        task = PREPARE.ROOT / "tasks/connectomics/celegans-structure-function-divergence"

        def staged(command, *, env, **_):
            self.assertEqual(command[0], "bash")
            self.assertEqual(env["BPB_CACHE_ROOT"], str(self.cache.resolve()))
            destination = Path(env["BPB_PRIVATE_EVAL_DIR"])
            (destination / "versions").mkdir()
            (destination / "signaling.npz").write_bytes(b"synthetic")
            for name in ("cook_2019", "white_1986_whole", "witvliet_2020_8"):
                (destination / "versions" / f"{name}.npz").write_bytes(b"synthetic")
            return subprocess.CompletedProcess(command, 0, "", "")

        worm_sources = {f"cache/{sha}/data": {"sha256": sha, "bytes": 1}
                        for sha in PREPARE.WORM_CACHE_SHA}
        with patch.object(PREPARE, "verify_materialization", return_value=self.source), patch.object(
                PREPARE, "worm_cache", return_value=worm_sources), patch.object(
                PREPARE.subprocess, "run", side_effect=staged):
            result, status = PREPARE.prepare(task, self.data, self.cache)
            self.assertEqual(status, "prepared")
            self.assertTrue((result / "versions/cook_2019.npz").is_file())
            self.assertEqual(PREPARE.prepare(task, self.data, self.cache), (result, "reused"))

    def test_failed_preparation_preserves_diagnostic_and_no_prepared_tree(self):
        task = PREPARE.ROOT / "tasks/mri/brain-age-mri"
        with patch.object(PREPARE, "verify_materialization", return_value=self.source), patch.object(
                PREPARE.subprocess, "run", return_value=subprocess.CompletedProcess([], 2, "", "")):
            with self.assertRaisesRegex(RuntimeError, "exited 2"):
                PREPARE.prepare(task, self.data, self.cache)
        self.assertFalse((self.data / "prepared").exists())
        errors = list(self.data.glob(".prepare-error-*.json"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(json.loads(errors[0].read_text())["status"], "preparation_failed")

    def test_competing_empty_prepared_directory_is_not_replaced(self):
        task = PREPARE.ROOT / "tasks/mri/brain-age-mri"

        def competitor(command, **_):
            destination = Path(command[command.index("--destination") + 1])
            destination.mkdir()
            (destination / "subjects.csv").write_text("synthetic")
            (self.data / "prepared").mkdir()
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(PREPARE, "verify_materialization", return_value=self.source), patch.object(
                PREPARE.subprocess, "run", side_effect=competitor):
            with self.assertRaises(FileExistsError):
                PREPARE.prepare(task, self.data, self.cache)
        self.assertEqual(list((self.data / "prepared").iterdir()), [])
        self.assertEqual(len(list(self.data.glob(".prepare-error-*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
