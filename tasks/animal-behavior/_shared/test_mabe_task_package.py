"""Cold-clone materialization checks for frozen MABe source metadata."""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from mabe_task_package import TASKS, _manifest, deliver, record
from test_mouse_transport import hosted_task_metadata


class MaterializeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="bpb-mabe-package-test-", dir=pathlib.Path(tempfile.gettempdir()).resolve())
        self.root = pathlib.Path(self.temporary.name)
        self.task = self.root / TASKS[0]
        self.task.mkdir()
        public_source = self.root / "source-public.npz"
        evaluator_source = self.root / "source-evaluator.npz"
        public_source.write_bytes(b"numeric public fixture")
        evaluator_source.write_bytes(b"numeric private fixture")
        public = [record(public_source, "public/pose/train/ABC.npz")]
        evaluator = [record(evaluator_source, "owner/test_labels.npz")]
        context = {"profile": "fixture", "metric": "macro_f1", "counts": {"train": 1},
                   "source_manifests": {"fixture": "0" * 64}}
        public_manifest = _manifest(TASKS[0], "agent", public, context)
        evaluator_manifest = _manifest(TASKS[0], "evaluator", evaluator, context)
        public_sha = hashlib.sha256(public_manifest).hexdigest()
        evaluator_sha = hashlib.sha256(evaluator_manifest).hexdigest()
        revision = hashlib.sha256(bytes.fromhex(public_sha) + bytes.fromhex(evaluator_sha)).hexdigest()
        self.result = {"task_id": TASKS[0], "public": public, "evaluator": evaluator,
                       "public_manifest": public_manifest, "evaluator_manifest": evaluator_manifest,
                       "public_manifest_sha256": public_sha,
                       "evaluator_manifest_sha256": evaluator_sha,
                       "revision": revision, **context}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_frozen_metadata_materializes_fresh_root_and_reuses_exact_root(self) -> None:
        first = deliver(self.task, self.root / "first", self.result)
        self.assertEqual(first["metadata"], "created")
        old = {name: (self.task / name).read_bytes()
               for name in ("contract.json", "data.lock", "evaluator.lock")}
        second = deliver(self.task, self.root / "cold", self.result, materialize_only=True)
        self.assertEqual(second["metadata"], "verified-existing")
        self.assertEqual(second["delivery_state"], "materialized")
        again = deliver(self.task, self.root / "cold", self.result, materialize_only=True)
        self.assertEqual(again["delivery_state"], "verified-existing")
        self.assertEqual(old, {name: (self.task / name).read_bytes() for name in old})

    def test_partial_or_changed_metadata_fails_without_materializing(self) -> None:
        deliver(self.task, self.root / "initial", self.result)
        (self.task / "contract.json").write_bytes((self.task / "contract.json").read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "metadata differs"):
            deliver(self.task, self.root / "rejected", self.result, materialize_only=True)
        self.assertFalse((self.root / "rejected").exists())
        partial = self.root / "partial" / TASKS[0]
        partial.mkdir(parents=True)
        (partial / "data.lock").write_bytes((self.task / "data.lock").read_bytes())
        with self.assertRaisesRegex(ValueError, "partial task metadata"):
            deliver(partial, self.root / "also-rejected", self.result, materialize_only=True)

    def test_corrupt_existing_delivery_is_preserved_and_rejected(self) -> None:
        deliver(self.task, self.root / "initial", self.result)
        cold = self.root / "cold"
        delivered = deliver(self.task, cold, self.result, materialize_only=True)
        file = pathlib.Path(delivered["delivery"]) / "public/public/pose/train/ABC.npz"
        file.write_bytes(file.read_bytes() + b"x")
        with self.assertRaisesRegex(ValueError, "differs from frozen binding"):
            deliver(self.task, cold, self.result, materialize_only=True)
        self.assertTrue(file.read_bytes().endswith(b"x"))

    def test_hosted_locks_keep_source_fallback_materialization(self) -> None:
        deliver(self.task, self.root / "initial", self.result)
        (self.task / "task.yaml").write_text("# fixture only\n")
        hosted_task_metadata(self.task)
        old = {name: (self.task / name).read_bytes() for name in ("contract.json", "data.lock", "evaluator.lock")}
        result = deliver(self.task, self.root / "hosted-cold", self.result, materialize_only=True)
        self.assertEqual(result["delivery_state"], "materialized")
        self.assertEqual(old, {name: (self.task / name).read_bytes() for name in old})


if __name__ == "__main__":
    unittest.main()
