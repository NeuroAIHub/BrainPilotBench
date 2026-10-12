"""Small public-only contract checks; no Agent, model, Docker or Test data."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

import numpy as np

import prepare
import score

archive_spec = importlib.util.spec_from_file_location(
    "stage_public_from_archive", Path(__file__).with_name("stage-public-from-archive.py"))
archive_stager = importlib.util.module_from_spec(archive_spec)
archive_spec.loader.exec_module(archive_stager)


class SharedEegBoundaryTests(unittest.TestCase):
    def test_frozen_public_classifier_contracts_are_bound(self):
        root = Path(__file__).resolve().parent.parent
        tasks = sorted(d for d in root.iterdir() if d.is_dir() and
                       d.name.startswith("eeg-") and d.name != "eeg-mi-bnci2014" and
                       (d / "task.yaml").is_file())
        classifiers = [d for d in tasks if json.loads((d / "contract.json").read_text()).get("kind") == "classification"]
        self.assertGreaterEqual(len(classifiers), 21)
        for task in classifiers:
            with self.subTest(task=task.name):
                contract = json.loads((task / "contract.json").read_text())
                self.assertEqual(contract["task_id"], task.name)
                self.assertEqual(contract["kind"], "classification")
                self.assertEqual(contract["primary_metric"], "balanced_accuracy")
                self.assertEqual(contract["direction"], "maximize")
                self.assertEqual(contract["source_sha"],
                                 "a8092dc10956038e445ff0e07f9c0c7e03a10d36")
                self.assertEqual(len(contract["source_task_spec_sha256"]), 64)
                self.assertEqual(set(contract["data_files"]), set(prepare.FILES))
                self.assertFalse((task / "candidate.json").exists())
                task_yaml = (task / "task.yaml").read_text()
                self.assertIn(f"data_availability: {contract['availability_status']}", task_yaml)
                self.assertIn(f"profile: {contract['metric_profile']}", task_yaml)
                lock = (task / "data.lock").read_text()
                self.assertEqual(lock.count("scope: public"), 4)
                self.assertNotIn("scope: private", lock)
                for name, entry in contract["data_files"].items():
                    self.assertEqual(len(entry["sha256"]), 64)
                    self.assertGreater(entry["bytes"], 0)
                    self.assertIn(entry["sha256"], lock)
                    self.assertIn(f"local://{task.name}/{contract['source_task_version']}/{name}", lock)

    def test_prepare_binds_each_public_file_and_no_extra(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task, package, output = root / "task", root / "package", root / "output"
            task.mkdir(); (package / "data").mkdir(parents=True)
            spec = b'{"native_case":"synthetic"}\n'
            (package / "task_spec.json").write_bytes(spec)
            files = {name: ("known-" + name).encode() for name in prepare.FILES}
            records = {}
            for name, body in files.items():
                (package / "data" / name).write_bytes(body)
                records[name] = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            (package / "data" / "private-test.npy").write_bytes(b"not-for-agent")
            (task / "contract.json").write_text(json.dumps({
                "task_id": "synthetic", "source_task_spec_sha256": hashlib.sha256(spec).hexdigest(),
                "data_files": records,
            }))
            with patch.dict(os.environ, {"BPB_EEG_PUBLIC_PACKAGE_DIR": str(package)}):
                result = prepare.prepare(task, output)
                self.assertFalse(result["private_test"])
                self.assertEqual({p.name for p in output.iterdir()}, set(prepare.FILES) | {"task_spec.json"})
                self.assertEqual((output / "val.npz").read_bytes(), files["val.npz"])
                (package / "data" / "val.npz").write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    prepare.prepare(task, root / "second")

    def test_prepare_refuses_output_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "task").mkdir(); (root / "target").mkdir()
            (root / "linked").symlink_to(root / "target", target_is_directory=True)
            records = {name: {"bytes": 1, "sha256": "a" * 64} for name in prepare.FILES}
            (root / "task" / "contract.json").write_text(json.dumps({"data_files": records}))
            with patch.dict(os.environ, {"BPB_EEG_PUBLIC_PACKAGE_DIR": str(root / "linked")}):
                with self.assertRaises(ValueError):
                    prepare.prepare(root / "task", root / "output")

    def test_mixed_archive_stages_only_hash_bound_public_members(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / "task"; task.mkdir()
            spec_body = b'{"task_id":"synthetic"}\n'
            files = {name: ("real-public-" + name).encode() for name in prepare.FILES}
            records = {name: {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                       for name, body in files.items()}
            (task / "contract.json").write_text(json.dumps({
                "task_id": "eeg-synthetic", "source_task_version": "source-v1",
                "source_task_spec_sha256": hashlib.sha256(spec_body).hexdigest(),
                "data_files": records,
            }))
            tar_path = root / "mixed.tar"
            with tarfile.open(tar_path, "w") as archive:
                for name, body in {"public/task_spec.json": spec_body,
                                   **{"public/data/" + k: v for k, v in files.items()},
                                   "private/test.npy": b"never-stage-this"}.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    archive.addfile(info, io.BytesIO(body))
            staged = root / "staged"
            plan = archive_stager.stage(task, tar_path)
            self.assertEqual(plan["status"], "plan_only")
            self.assertEqual(plan["private_members_in_source_archive"], 1)
            self.assertFalse(staged.exists())
            receipt = archive_stager.stage(task, tar_path, staged.resolve(), extract=True)
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["private_files_staged"], 0)
            output = staged / "eeg-synthetic" / "source-v1"
            self.assertEqual({p.name for p in output.iterdir()}, set(prepare.FILES) | {"complete.json"})
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads((output / "complete.json").read_text())["private_files_staged"], 0)
            self.assertFalse((output / "private").exists())
            with self.assertRaises(FileExistsError):
                archive_stager.stage(task, tar_path, staged.resolve(), extract=True)

    def test_mixed_archive_rejects_tamper_and_unsafe_members(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / "task"; task.mkdir()
            spec_body = b'{"task_id":"synthetic"}\n'
            files = {name: ("public-" + name).encode() for name in prepare.FILES}
            records = {name: {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                       for name, body in files.items()}
            (task / "contract.json").write_text(json.dumps({
                "task_id": "eeg-synthetic", "source_task_version": "source-v1",
                "source_task_spec_sha256": hashlib.sha256(spec_body).hexdigest(),
                "data_files": records,
            }))

            def make_archive(path, *, changed_train=False, extra_name=None, extra_type=None):
                with tarfile.open(path, "w") as archive:
                    for name, body in {"public/task_spec.json": spec_body,
                                       **{"public/data/" + k: v for k, v in files.items()},
                                       "private/test.npz": b"dark-data"}.items():
                        if changed_train and name == "public/data/train.npz":
                            body = b"X" + body[1:]
                        info = tarfile.TarInfo(name); info.size = len(body)
                        archive.addfile(info, io.BytesIO(body))
                    if extra_name is not None:
                        info = tarfile.TarInfo(extra_name)
                        info.type = extra_type or tarfile.REGTYPE
                        if info.type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                            info.linkname = "private/test.npz"
                        else:
                            info.size = 1
                        archive.addfile(info, None if info.type in (tarfile.SYMTYPE, tarfile.LNKTYPE)
                                        else io.BytesIO(b"x"))

            for label, options in {
                "duplicate": {"extra_name": "public/data/train.npz"},
                "traversal": {"extra_name": "public/../private/escape"},
                "noncanonical": {"extra_name": "public//data/alias"},
                "symlink": {"extra_name": "public/alias", "extra_type": tarfile.SYMTYPE},
                "hardlink": {"extra_name": "public/alias", "extra_type": tarfile.LNKTYPE},
            }.items():
                with self.subTest(label=label):
                    archive_path = root / f"{label}.tar"
                    make_archive(archive_path, **options)
                    with self.assertRaises(ValueError):
                        archive_stager.stage(task, archive_path)
            tampered = root / "tampered.tar"
            make_archive(tampered, changed_train=True)
            self.assertEqual(archive_stager.stage(task, tampered)["status"], "plan_only")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                archive_stager.stage(task, tampered, (root / "output").resolve(), extract=True)
            self.assertFalse((root / "output" / "eeg-synthetic" / "source-v1").exists())

            oversized = root / "oversized.tar"
            make_archive(oversized)
            with tarfile.open(oversized, "r") as archive:
                members = archive.getmembers()
                huge = tarfile.TarInfo("private/too-big")
                huge.size = archive_stager.MAX_PUBLIC_BYTES + 1
                with patch.object(archive, "getmembers", return_value=[*members, huge]):
                    with self.assertRaisesRegex(ValueError, "oversized"):
                        archive_stager.inspect_tar(archive, archive_stager.read_contract(task))

    def test_metric_profiles_have_distinct_absent_class_semantics(self):
        y = np.array([0, 0, 1, 1], dtype=np.int64)
        pred = np.array([0, 1, 1, 1], dtype=np.int64)
        self.assertAlmostEqual(score.balanced_accuracy(y, pred, 2,
            "native-balanced-accuracy-complete-classes"), 0.75)
        y_sparse = np.array([0, 0], dtype=np.int64)
        pred_sparse = np.array([0, 1], dtype=np.int64)
        self.assertAlmostEqual(score.balanced_accuracy(y_sparse, pred_sparse, 3,
            "native-typing-sparse-macro-torchmetrics-1.9"), 0.25)

    def test_inference_image_must_be_a_complete_digest(self):
        self.assertFalse(score.valid_image_reference("sha256:tag"))
        self.assertFalse(score.valid_image_reference("repo@sha256:abc"))
        self.assertFalse(score.valid_image_reference("repo:mutable-tag"))
        self.assertTrue(score.valid_image_reference("sha256:" + "a" * 64))
        self.assertTrue(score.valid_image_reference("registry.example/repo@sha256:" + "b" * 64))

    def test_staged_bytes_must_match_hashed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source, staged = Path(temp) / "model.py", Path(temp) / "staged.py"
            source.write_bytes(b"approved model bytes")
            with patch.object(score.shutil, "copyfile", side_effect=lambda _source, dest: Path(dest).write_bytes(b"tampered copy")):
                with self.assertRaisesRegex(ValueError, "staged submission differs"):
                    score.copy_verified_required_file(source, staged, 1000)
            staged.unlink()
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(score.copy_verified_required_file(source, staged, 1000), expected)
            self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(), expected)

    def test_validation_shape_and_prediction_header(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, extracted = root / "val.npz", root / "x.npy"
            np.savez_compressed(package, x=np.zeros((4, 2, 3), dtype=np.float32),
                                y=np.array([0, 1, 0, 1], dtype=np.int64))
            contract = {"valid_samples": 4, "input_shape": [2, 3], "output_size": 2,
                        "metric_profile": "native-balanced-accuracy-complete-classes"}
            self.assertEqual(score.stage_x_and_y(package, extracted, contract).tolist(), [0, 1, 0, 1])
            with self.assertRaises(ValueError):
                score.stage_x_and_y(package, root / "wrong.npy", {**contract, "valid_samples": 5})
            predictions = root / "predictions.npy"
            np.save(predictions, np.full((4, 2), 0.5, dtype=np.float32))
            self.assertEqual(score.inspect_prediction(predictions, 4, 2).tolist(), [0, 0, 0, 0])
            with self.assertRaises(ValueError):
                score.inspect_prediction(predictions, 5, 2)


if __name__ == "__main__":
    unittest.main()
