"""Synthetic software checks only; these fixtures are not benchmark scores."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import private_score as private


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def contract(task_id="eeg-synthetic") -> dict:
    return {"task_id": task_id, "source_task_id": "synthetic/source",
            "source_task_version": "synthetic-v1", "source_task_spec_sha256": "a" * 64,
            "source_sha": "b" * 40, "data_files": {"val.npz": {"sha256": "c" * 64, "bytes": 10}},
            "input_shape": [2, 3], "output_size": 3,
            "metric_profile": "native-balanced-accuracy-complete-classes"}


class PrivateScoreBoundaryTests(unittest.TestCase):
    def test_frozen_tree_checks_all_files_before_and_after(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "artifacts"
            for seed in range(3):
                directory = root / "submission" / f"seed-{seed}"
                directory.mkdir(parents=True)
                for name in private.REQUIRED:
                    (directory / name).write_bytes(f"synthetic-{seed}-{name}".encode())
            (root / "notes.txt").write_bytes(b"")
            files = {path.relative_to(root).as_posix(): sha(path)
                     for path in root.rglob("*") if path.is_file()}
            snapshot = {"schema": private.FREEZE_SCHEMA, "task_id": "eeg-synthetic",
                        "task_version": "0.1-synthetic", "files": files}
            self.assertEqual(private.verify_frozen(root, snapshot, "eeg-synthetic", "0.1-synthetic"), files)
            with self.assertRaisesRegex(ValueError, "identity"):
                private.verify_frozen(root, snapshot, "eeg-synthetic", "0.2-synthetic")
            (root / "notes.txt").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "frozen"):
                private.verify_frozen(root, snapshot, "eeg-synthetic", "0.1-synthetic")
            (root / "notes.txt").write_bytes(b"")
            (root / "submission" / "seed-0" / "extra").symlink_to(root / "notes.txt")
            with self.assertRaisesRegex(ValueError, "linked"):
                private.verify_frozen(root, snapshot, "eeg-synthetic", "0.1-synthetic")

    def test_strict_metadata_and_independent_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            metadata = root / "metadata.json"
            metadata.write_text('{"outer":{"x":1,"x":2}}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                private._json(metadata)
            metadata.write_text('{"value":NaN}')
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                private._json(metadata)
            target = root / "target.bin"
            target.write_bytes(b"synthetic")
            linked = root / "linked.bin"
            os.link(target, linked)
            with self.assertRaisesRegex(ValueError, "linked"):
                private._regular(linked)
            alias = root / "alias"
            actual = root / "actual" / "evaluator"
            actual.mkdir(parents=True)
            alias.symlink_to(actual.parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "linked"):
                private.verify_packet(root, alias / "evaluator", contract())

    def test_normalized_binding_requires_locked_bytes_and_public_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            task, data = root / "task", root / "data"
            task.mkdir(); (data / "test").mkdir(parents=True)
            c = contract()
            np.savez(data / "test" / "test.npz", x=np.zeros((3, 2, 3), dtype=np.float32))
            np.save(data / "test" / "test-labels.npy", np.arange(3, dtype=np.int64))
            files = {name: {"bytes": (data / "test" / name).stat().st_size,
                            "sha256": sha(data / "test" / name)}
                     for name in ("test.npz", "test-labels.npy")}
            binding = {"schema": "bpb-eeg-private-test-binding/1", "task_id": c["task_id"],
                       "source_task_id": c["source_task_id"],
                       "source_task_version": c["source_task_version"],
                       "source_task_spec_sha256": c["source_task_spec_sha256"],
                       "source_sha": c["source_sha"], "public_data": c["data_files"],
                       "private_data": files, "test_samples": 3, "test_npz_members": ["x.npy"]}
            write_json(data / "test" / "binding.json", binding)
            locked = {name: {"name": "evaluator__test__" + name,
                             "path": "test/" + name, "sha256": sha(data / "test" / name),
                             "bytes": (data / "test" / name).stat().st_size}
                      for name in (*files, "binding.json")}
            write_json(task / "evaluator.lock", {"schema": private.LOCK_SCHEMA,
                "task_id": c["task_id"], "repo_id": private.REPO_ID, "revision": "d" * 40,
                "files": list(locked.values())})
            write_json(data / ".bpb-evaluator.json", {
                "schema": "bpb-prepared-evaluator/1", "task_id": c["task_id"],
                "revision": "d" * 40, "files": 3,
                "evaluator_lock_sha256": sha(task / "evaluator.lock")})
            _lock, records, found = private.verify_packet(task, data, c)
            self.assertEqual(set(records), private.STANDARD_FILES)
            self.assertEqual(found["test_samples"], 3)
            full_contract = {**c, "kind": "classification", "primary_metric": "balanced_accuracy",
                             "direction": "maximize", "valid_samples": 3,
                             "max_parameters": 10_000_000,
                             "max_numeric_state_elements": 10_000_000}
            write_json(task / "contract.json", full_contract)
            (task / "task.yaml").write_text('version: "0.1-synthetic"\n', encoding="utf-8")
            artifacts = root / "artifacts"
            for seed in range(3):
                folder = artifacts / "submission" / f"seed-{seed}"
                folder.mkdir(parents=True)
                for name in private.REQUIRED:
                    (folder / name).write_bytes(f"synthetic {seed} {name}".encode())
            freeze = root / "frozen.json"
            write_json(freeze, {"schema": private.FREEZE_SCHEMA, "task_id": c["task_id"],
                "task_version": "0.1-synthetic",
                "files": {file.relative_to(artifacts).as_posix(): sha(file)
                          for file in artifacts.rglob("*") if file.is_file()}})

            def fake_infer(_seed, _x, output, _contract, _image, _rows, _hashes):
                output.mkdir()
                return np.arange(3, dtype=np.int64)

            with patch.dict(private.os.environ, {"BPB_INFERENCE_IMAGE": "sha256:" + "f" * 64}), \
                 patch.object(private, "_infer", side_effect=fake_infer):
                result = private.score_private(task, artifacts, data, freeze, root / "private-report.json")
            self.assertEqual(result, {"balanced_accuracy": 1.0, "seeds": 3, "test_samples": 3})
            report = json.loads((root / "private-report.json").read_text())
            self.assertEqual(report["evaluation_scope"],
                             "independent-evaluator-test; not official leaderboard equivalence")
            self.assertEqual(report["evaluator_revision"], "d" * 40)
            lock = json.loads((task / "evaluator.lock").read_text())
            lock["files"][0]["name"] = "opaque-privately-named-binding"
            write_json(task / "evaluator.lock", lock)
            prepared = json.loads((data / ".bpb-evaluator.json").read_text())
            prepared["evaluator_lock_sha256"] = sha(task / "evaluator.lock")
            write_json(data / ".bpb-evaluator.json", prepared)
            private.verify_packet(task, data, c)
            with self.assertRaisesRegex(ValueError, "public file hashes"):
                private.verify_packet(task, data, {**c, "data_files": {}})
            (data / "test" / "test.npz").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "lock"):
                private.verify_packet(task, data, c)
            (task / "contract.json").write_text('{"task_id":"first","task_id":"second"}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                private.score_private(task, artifacts, data, freeze, root / "unused-report.json")

    def test_sleep_shards_are_scored_in_order_with_labels_outside_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            packet = root / "data" / "test"
            packet.mkdir(parents=True)
            c = contract(private.SLEEP_TASK)
            pairs = []
            with tarfile.open(packet / "test-shards.tar", "w") as archive:
                for index, labels in enumerate(([0, 1], [2, 2])):
                    x_name = f"shard-{index}.npz"
                    y_name = f"shard-{index}-labels.npy"
                    x_file, y_file = root / x_name, root / y_name
                    np.savez(x_file, x=np.full((2, 2, 3), index, dtype=np.float32))
                    np.save(y_file, np.eye(3, dtype=np.float32)[labels])
                    pairs.append({"x": x_name, "x_sha256": sha(x_file), "y": y_name,
                                  "y_sha256": sha(y_file), "samples": 2})
                    for name, path in ((x_name, x_file), (y_name, y_file)):
                        info = tarfile.TarInfo("test/" + name)
                        info.size = path.stat().st_size
                        archive.addfile(info, io.BytesIO(path.read_bytes()))
            write_json(packet / "shards.json", {"schema": "bpb-eeg-sharded-test-manifest/1",
                "ordered_pairs": pairs, "source_complete_sha256": "e" * 64})
            binding = {"test_samples": 4, "shard_pairs": 2,
                       "source_complete_sha256": "e" * 64}
            staged = [(root / f"seed-{seed}", {}) for seed in range(3)]
            for directory, _ in staged:
                directory.mkdir()

            def fake_infer(_seed, _x, output, _contract, _image, rows, _hashes):
                self.assertEqual(rows, 4)
                output.mkdir()
                return np.array([0, 1, 2, 2], dtype=np.int64)

            with patch.object(private, "_infer", side_effect=fake_infer):
                scores = private._sleep(root / "data", root, c, binding, staged, "sha256:" + "f" * 64)
            self.assertEqual(scores, [1.0, 1.0, 1.0])

    def test_docker_mounts_only_model_features_worker_and_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged, x, output = root / "seed", root / "x.npy", root / "out"
            staged.mkdir()
            for name in private.REQUIRED:
                (staged / name).write_bytes(b"synthetic")
            np.save(x, np.zeros((2, 2, 3), dtype=np.float32))
            hashes = {name: sha(staged / name) for name in private.REQUIRED}
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                if command[:2] == ["docker", "run"]:
                    np.save(output / "predictions.npy", np.array([[1, 0, 0], [0, 1, 0]],
                                                                 dtype=np.float32))

            with patch.object(private.subprocess, "run", side_effect=fake_run):
                predicted = private._infer(staged, x, output, contract(),
                    "sha256:" + "f" * 64, 2, hashes)
            self.assertEqual(predicted.tolist(), [0, 1])
            command = commands[0]
            self.assertIn("none", command)
            mounts = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "-v"]
            self.assertEqual(len(mounts), 4)
            self.assertTrue(all("label" not in mount and "evaluator" not in mount for mount in mounts))
            self.assertFalse(any(value == "--env" for value in command))


if __name__ == "__main__":
    unittest.main()
