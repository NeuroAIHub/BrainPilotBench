"""Discoverable cold-clone materialization and fail-closed lock fixtures."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from calms_task_package import build
from test_mouse_transport import hosted_task_metadata


class ColdMaterializeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bpb-calms-package-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.task = self.root / "tasks/animal-behavior/calms21-classic-classification"
        self.task.mkdir(parents=True)
        self.prepared = self.root / "prepared"
        for name, data in (("public/train/a.npz", b"train"),
                           ("public/valid/b.npz", b"valid"),
                           ("owner/test/c.npz", b"test")):
            path = self.prepared / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        source_sha = "a" * 64
        public = {"task": "task1", "source_sha256": source_sha,
                  "splits": {"train": [{"file": "a.npz"}], "valid": [{"file": "b.npz"}]},
                  "counts": {"train": {"sequences": 1, "frames": 1},
                             "valid": {"sequences": 1, "frames": 1}},
                  "vocab": {"attack": 0, "investigation": 1, "mount": 2, "other": 3}}
        owner = {"task": "task1", "source_sha256": source_sha,
                 "sequences": [{"file": "c.npz"}], "counts": {"sequences": 1, "frames": 1}}
        (self.prepared / "public/manifest.json").write_text(json.dumps(public))
        (self.prepared / "owner/test-manifest.json").write_text(json.dumps(owner))
        patcher = patch("calms_task_package.verify_task1", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.initial = build(self.task, self.prepared, self.root / "initial")
        self.metadata_bytes = {name: (self.task / name).read_bytes()
                               for name in ("data.lock", "evaluator.lock", "contract.json")}

    def test_existing_identical_metadata_materializes_and_reuses(self) -> None:
        first = build(self.task, self.prepared, self.root / "cold", materialize_only=True)
        self.assertEqual(first["metadata"], "reused_unchanged")
        self.assertEqual(first["delivery_state"], "created_verified")
        second = build(self.task, self.prepared, self.root / "cold", materialize_only=True)
        self.assertEqual(second["delivery_state"], "reused_verified")
        self.assertEqual(self.metadata_bytes, {name: (self.task / name).read_bytes()
                                               for name in self.metadata_bytes})

    def test_changed_hash_fails_without_overwriting_or_delivery(self) -> None:
        path = self.task / "data.lock"
        data = json.loads(path.read_text())
        data["datasets"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(data))
        changed = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "differs"):
            build(self.task, self.prepared, self.root / "mismatch", materialize_only=True)
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual((self.task / "contract.json").read_bytes(), self.metadata_bytes["contract.json"])
        self.assertFalse((self.root / "mismatch").exists())

    def test_partial_metadata_fails_without_repair(self) -> None:
        (self.task / "evaluator.lock").unlink()
        with self.assertRaisesRegex(ValueError, "partial"):
            build(self.task, self.prepared, self.root / "partial", materialize_only=True)
        self.assertFalse((self.task / "evaluator.lock").exists())
        self.assertFalse((self.root / "partial").exists())

    def test_hosted_locks_remain_unchanged_during_source_materialization(self) -> None:
        (self.task / "task.yaml").write_text("# fixture only\n")
        hosted_task_metadata(self.task)
        old = {name: (self.task / name).read_bytes() for name in self.metadata_bytes}
        result = build(self.task, self.prepared, self.root / "hosted-cold", materialize_only=True)
        self.assertEqual(result["delivery_state"], "created_verified")
        self.assertEqual(old, {name: (self.task / name).read_bytes() for name in old})

    def test_incomplete_destination_is_preserved_and_rejected(self) -> None:
        first = build(self.task, self.prepared, self.root / "cold", materialize_only=True)
        destination = Path(first["delivery"])
        missing = destination / "public/train/a.npz"
        missing.unlink()
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            build(self.task, self.prepared, self.root / "cold", materialize_only=True)
        self.assertFalse(missing.exists())
        self.assertEqual(self.metadata_bytes, {name: (self.task / name).read_bytes()
                                               for name in self.metadata_bytes})


if __name__ == "__main__":
    unittest.main()
