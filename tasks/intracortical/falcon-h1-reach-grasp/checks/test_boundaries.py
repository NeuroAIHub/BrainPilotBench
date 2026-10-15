"""Scoring boundary checks on numeric fixtures only; no submitted Python is imported."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

import score


def binding(path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


class H1BoundaryTests(unittest.TestCase):
    def make_valid(self, root):
        task = root / "task"
        task.mkdir()
        manifest_root = root / "public" / "valid"
        manifest_root.mkdir(parents=True)
        runs = []
        for run_index in range(2):
            run_dir = manifest_root / "runs" / f"run-{run_index}"
            run_dir.mkdir(parents=True)
            values = {
                "x.npy": np.zeros((4, 176), dtype=np.uint8),
                "y.npy": np.arange(28, dtype=np.float64).reshape(4, 7) + run_index,
                "mask.npy": np.array([True, False, True, True], dtype=np.bool_),
                "trial_start.npy": np.array([False, True, False, False], dtype=np.bool_),
            }
            files = {}
            for name, array in values.items():
                path = run_dir / name
                np.save(path, array, allow_pickle=False)
                files[name] = {"path": f"runs/run-{run_index}/{name}",
                               "shape": list(array.shape), "dtype": str(array.dtype), **binding(path)}
            runs.append({"id": f"run-{run_index}", "role": "valid", "session_id": "19250120",
                         "order": run_index, "files": files})
        manifest = manifest_root / "manifest.json"
        manifest.write_text(json.dumps({"schema": score.SCHEMA, "profile": score.PROFILE,
                                        "role": "valid", "runs": runs}))
        (task / "contract.json").write_text(json.dumps({"schema": "bpb-h1-contract/1",
            "task_version": "0.1-public-validation-stream", "science_profile": score.PROFILE,
            "task_id": "falcon-h1-reach-grasp",
            "evaluation_manifests": {"valid": binding(manifest)}}))
        return task, manifest, runs

    def test_role_manifest_and_all_four_arrays_are_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            task, manifest, runs = self.make_valid(Path(temporary))
            self.assertEqual(len(score.load_manifest(task, manifest, "valid")), 2)
            source = manifest.parent / runs[0]["files"]["mask.npy"]["path"]
            with source.open("r+b") as stream:
                stream.seek(-1, os.SEEK_END)
                stream.write(b"X")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                score.load_manifest(task, manifest, "valid")

    def test_rejects_manifest_role_swap_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            task, manifest, runs = self.make_valid(Path(temporary))
            with self.assertRaises(ValueError):
                score.load_manifest(task, manifest, "test")
            runs[0]["files"]["x.npy"]["path"] = "../../outside.npy"
            manifest.write_text(json.dumps({"schema": score.SCHEMA, "profile": score.PROFILE,
                                            "role": "valid", "runs": runs}))
            contract = json.loads((task / "contract.json").read_text())
            contract["evaluation_manifests"]["valid"] = binding(manifest)
            (task / "contract.json").write_text(json.dumps(contract))
            with self.assertRaisesRegex(ValueError, "escapes root"):
                score.load_manifest(task, manifest, "valid")

    def test_submission_rejects_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            submission = root / "artifacts" / "submission"
            submission.mkdir(parents=True)
            (submission / "model.py").write_bytes(b"class Model: pass\n")
            (submission / "config.json").write_bytes(b"{}")
            (submission / "weights.safetensors").write_bytes(b"placeholder")
            (submission / "model.py").unlink()
            (submission / "model.py").symlink_to(root / "outside.py")
            with self.assertRaises(ValueError):
                score.stage_submission(root / "artifacts", root / "stage-1", None, test=False)
            (submission / "model.py").unlink()
            (submission / "model.py").write_bytes(b"class Model: pass\n")
            os.link(submission / "model.py", root / "hardlink.py")
            with self.assertRaises(ValueError):
                score.stage_submission(root / "artifacts", root / "stage-2", None, test=False)

    def test_host_rejects_nonfinite_config_and_persisted_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary)
            config = staged / "config.json"
            weights = staged / "weights.safetensors"

            def state(dtype, shape, body):
                header = json.dumps({"weight": {"dtype": dtype, "shape": shape,
                                                "data_offsets": [0, len(body)]}}).encode()
                weights.write_bytes(struct.pack("<Q", len(header)) + header + body)

            config.write_text("{}")
            state("F32", [1], struct.pack("<f", 2.0))
            score.validate_staged_config_and_state(staged)
            config.write_text('{"scale": 1e999}')
            with self.assertRaisesRegex(ValueError, "finite JSON"):
                score.validate_staged_config_and_state(staged)
            config.write_text("{}")
            state("F32", [1], struct.pack("<f", float("inf")))
            with self.assertRaisesRegex(ValueError, "nonfinite persisted"):
                score.validate_staged_config_and_state(staged)
            state("F32", [10_000_001], b"0")
            with self.assertRaisesRegex(ValueError, "10M"):
                score.validate_staged_config_and_state(staged)

    def test_negative_r2_is_preserved_after_same_date_concatenation(self):
        y1 = np.array([[0.] * 7, [1.] * 7])
        y2 = np.array([[2.] * 7, [3.] * 7])
        prediction = np.zeros((4, 7))
        self.assertAlmostEqual(score.date_score(np.concatenate((y1, y2)), prediction), -1.8)
        target = np.column_stack((np.arange(4.), np.zeros((4, 6))))
        predicted = target.copy()
        predicted[:, 1:] = 1000.
        self.assertEqual(score.date_score(target, predicted), 1.0)
        self.assertFalse(score.IMAGE_RE.fullmatch("python:3.12"))


if __name__ == "__main__":
    unittest.main()
