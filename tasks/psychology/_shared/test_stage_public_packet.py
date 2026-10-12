"""Small, stdlib-only safety tests for the frozen public packet stager.

The successful toy stage replaces only the full-cohort source audit: its
hard-coded 76-task/859 MB totals cannot be reproduced in a cheap fixture.
Copying, per-file hashes, manifest construction, and packet verification run
through the real implementation. No official Test data is used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import stage_public_packet as packet


class PublicPacketStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(
            prefix="psych-public-stage-test-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.source = self.base / "published-20261002-v1"
        self.source.mkdir(mode=0o700)
        self.parent = self.base / "private-stage"
        self.parent.mkdir(mode=0o700)
        self.destination = self.parent / "toy-packet"
        self.experiment = "toy/exp1.csv"
        self.slug = "toy-exp1"
        self.task_id = "psych101-toy-exp1"
        folder = self.source / self.slug
        folder.mkdir(mode=0o700)
        splits = {}
        for split, participant, answer in (("train", "p-train", "A"),
                                            ("valid", "p-valid", "B")):
            line = (json.dumps({"experiment": self.experiment, "participant": participant,
                                "text": f"instruction <<{answer}>>"}, sort_keys=True) + "\n").encode()
            (folder / f"{split}.jsonl").write_bytes(line)
            splits[split] = {"sha256": hashlib.sha256(line).hexdigest(), "bytes": len(line),
                             "rows": 1, "responses": 1}
        self.index = {
            "schema": "bpb-psych101-public-source-index/1",
            "source_package_version": "published-20261002-v1",
            "source_index_sha256": "e" * 64,
            "source_public_sha256": "f" * 64,
            "task_count": 1,
            "split_count": 2,
            "source_public_bytes": sum(item["bytes"] for item in splits.values()),
            "public_rows": 2,
            "public_responses": 2,
            "tasks": [{"task_id": self.task_id, "experiment_id": self.experiment,
                       "source_slug": self.slug, "splits": splits}],
        }
        (self.source / "state.json").write_text(json.dumps({
            "schema": "psych101-public-package-state/1", "version": "published-20261002-v1",
            "public_task_count": 1,
        }))
        (folder / "spec.json").write_text(json.dumps({
            "schema": "psych101-published-task/1", "task_version": "published-20261002-v1",
            "experiment_id": self.experiment, "task_id": "psych101/toy/exp1",
            "source_public_sha256": "f" * 64, "splits": splits,
        }))

    def stage_toy(self) -> dict:
        with mock.patch.object(packet, "audit_source", return_value={"tasks": 1, "files": 2}):
            return packet.stage_packet(self.source, self.destination, self.index)

    def test_actual_reduced_index_is_well_formed(self) -> None:
        frozen = packet.load_index(packet.INDEX)
        self.assertEqual(len(frozen["tasks"]), 76)
        self.assertEqual(sum(len(task["splits"]) for task in frozen["tasks"]), 152)

    def test_successful_toy_stage_and_independent_verify(self) -> None:
        result = self.stage_toy()
        self.assertEqual(result["status"], "public_packet_candidate_verified_not_published_or_scored")
        self.assertEqual(len(list(self.destination.rglob("*.jsonl"))), 2)
        self.assertEqual(len([p for p in self.destination.rglob("*") if p.is_file()]), 3)
        self.assertEqual(packet.verify_packet(self.destination, self.index)["manifest_sha256"],
                         result["manifest_sha256"])
        manifest = json.loads((self.destination / "MANIFEST.json").read_text())
        self.assertEqual(manifest["schema"], "bpb-psych101-public-packet/2")
        self.assertEqual(manifest["status"], "public_packet_candidate_not_published_or_scored")
        self.assertFalse(manifest["private_test_included"])
        self.assertEqual({item["split"] for item in manifest["files"]}, {"train", "valid"})
        source_file = self.source / self.slug / "train.jsonl"
        staged_file = self.destination / "public-tasks" / self.task_id / "train.jsonl"
        self.assertNotEqual(source_file.stat().st_ino, staged_file.stat().st_ino)
        self.assertEqual(packet.digest(source_file), packet.digest(staged_file))

    def test_existing_destination_is_refused_and_preserved(self) -> None:
        self.destination.mkdir(mode=0o700)
        witness = self.destination / "keep.txt"
        witness.write_text("unchanged")
        with self.assertRaisesRegex(ValueError, "destination exists"):
            self.stage_toy()
        self.assertEqual(witness.read_text(), "unchanged")

    def test_output_inside_source_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "separate from published source"):
            packet.checked_output_path(self.source / "new-packet", self.source)

    def test_symlink_parent_and_symlink_target_are_refused(self) -> None:
        link_parent = self.base / "linked-parent"
        link_parent.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic-link ancestor"):
            packet.checked_output_path(link_parent / "packet", self.source)
        self.destination.symlink_to(self.parent / "absent")
        with self.assertRaisesRegex(ValueError, "destination exists"):
            packet.checked_output_path(self.destination, self.source)

    def test_symlink_source_task_directory_is_refused(self) -> None:
        other = dict(self.index["tasks"][0], source_slug="linked-task")
        (self.source / "linked-task").symlink_to(self.source / self.slug, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "real directory"):
            packet.source_task_dir(self.source, other)

    def test_bad_source_hash_is_refused_before_staging(self) -> None:
        source_file = self.source / self.slug / "train.jsonl"
        original = source_file.read_bytes()
        source_file.write_bytes(original.replace(b"<<A>>", b"<<Z>>"))
        with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
            packet.audit_source(self.source, self.index)
        with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
            self.stage_toy()
        self.assertTrue(self.destination.is_dir())
        self.assertFalse((self.destination / "MANIFEST.json").exists())

    def test_extra_file_and_symlink_in_packet_are_refused(self) -> None:
        self.stage_toy()
        extra = self.destination / "unexpected.txt"
        extra.write_text("extra")
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            packet.verify_packet(self.destination, self.index)
        extra.unlink()
        extra.symlink_to(self.source / self.slug / "train.jsonl")
        with self.assertRaisesRegex(ValueError, "linked or special entry"):
            packet.verify_packet(self.destination, self.index)

    def test_empty_destination_appearing_after_precheck_is_refused(self) -> None:
        def create_racing_target(_source: Path, _index: dict) -> dict:
            self.destination.mkdir(mode=0o700)
            return {"tasks": 1, "files": 2}

        with mock.patch.object(packet, "audit_source", side_effect=create_racing_target):
            with self.assertRaisesRegex(ValueError, "appeared during staging"):
                packet.stage_packet(self.source, self.destination, self.index)
        self.assertTrue(self.destination.is_dir())
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_nonempty_destination_appearing_after_precheck_is_preserved(self) -> None:
        def create_racing_target(_source: Path, _index: dict) -> dict:
            self.destination.mkdir(mode=0o700)
            (self.destination / "keep.txt").write_text("unchanged")
            return {"tasks": 1, "files": 2}

        with mock.patch.object(packet, "audit_source", side_effect=create_racing_target):
            with self.assertRaisesRegex(ValueError, "appeared during staging"):
                packet.stage_packet(self.source, self.destination, self.index)
        self.assertEqual((self.destination / "keep.txt").read_text(), "unchanged")

    def test_failed_copy_keeps_partial_output_and_refuses_retry(self) -> None:
        with mock.patch.object(packet, "audit_source", return_value={"tasks": 1, "files": 2}), \
             mock.patch.object(packet, "copy_verified", side_effect=RuntimeError("injected copy failure")):
            with self.assertRaisesRegex(RuntimeError, "injected copy failure"):
                packet.stage_packet(self.source, self.destination, self.index)
        self.assertTrue(self.destination.is_dir())
        self.assertFalse((self.destination / "MANIFEST.json").exists())
        with self.assertRaises(FileNotFoundError):
            packet.verify_packet(self.destination, self.index)
        with self.assertRaisesRegex(ValueError, "destination exists"):
            self.stage_toy()

    def test_final_verification_failure_keeps_only_candidate_manifest(self) -> None:
        with mock.patch.object(packet, "verify_packet",
                               side_effect=RuntimeError("injected final verification failure")):
            with self.assertRaisesRegex(RuntimeError, "injected final verification failure"):
                self.stage_toy()
        manifest = json.loads((self.destination / "MANIFEST.json").read_text())
        self.assertEqual(manifest["schema"], "bpb-psych101-public-packet/2")
        self.assertEqual(manifest["status"], "public_packet_candidate_not_published_or_scored")
        self.assertNotIn("verified", manifest["status"])
        with self.assertRaisesRegex(ValueError, "destination exists"):
            self.stage_toy()

    def test_exact_legacy_v1_manifest_remains_verifiable(self) -> None:
        self.stage_toy()
        manifest_path = self.destination / "MANIFEST.json"
        legacy = json.loads(manifest_path.read_text())
        legacy["schema"] = "bpb-psych101-public-packet/1"
        legacy["status"] = "public_packet_candidate_verified_not_published_or_scored"
        manifest_path.chmod(0o600)
        manifest_path.write_text(json.dumps(legacy, sort_keys=True) + "\n")
        self.assertEqual(packet.verify_packet(self.destination, self.index)["status"],
                         "public_packet_candidate_verified_not_published_or_scored")
        legacy["source_index_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(legacy, sort_keys=True) + "\n")
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            packet.verify_packet(self.destination, self.index)
        legacy["source_index_sha256"] = self.index["source_index_sha256"]
        manifest_path.write_text(json.dumps(legacy, sort_keys=True) + "\n")
        staged_file = self.destination / "public-tasks" / self.task_id / "train.jsonl"
        staged_file.chmod(0o600)
        staged_file.write_bytes(staged_file.read_bytes().replace(b"<<A>>", b"<<Z>>"))
        with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
            packet.verify_packet(self.destination, self.index)


if __name__ == "__main__":
    unittest.main()
