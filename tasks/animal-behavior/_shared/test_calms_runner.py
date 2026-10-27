"""Boundary tests for the frozen CalMS21 Docker prediction contract."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from calms_freeze import freeze, snapshot
from calms_runner import _predict, _role_packet
from calms_prepare import ARRAY_SPEC, SOURCE_SHA256
from calms_metrics import CLASSIC_VOCAB


GOOD = '''import numpy as np
def load_model(config, weights_path):
    class Model:
        def predict_proba(self, keypoints, scores, context):
            return np.full((len(keypoints), context["class_count"]), 1/context["class_count"])
    return Model()
'''


def _submission(path: Path, code: str = GOOD) -> None:
    path.mkdir(mode=0o700)
    (path / "model.py").write_text(code)
    (path / "config.json").write_text("{}")
    with (path / "weights.npz").open("xb") as stream:
        np.savez(stream, weight=np.array([1.0]))


class FreezeTests(unittest.TestCase):
    def test_missing_and_tamper(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
            root = Path(tmp)
            source, frozen = root / "source", root / "frozen"
            _submission(source)
            freeze(source, frozen)
            snapshot(frozen, frozen=True)
            (frozen / "model.py").write_text("changed")
            with self.assertRaises(ValueError):
                snapshot(frozen, frozen=True)
            (frozen / "model.py").unlink()
            with self.assertRaises(ValueError):
                snapshot(frozen, frozen=True)

    def test_pickle_weights_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
            source = Path(tmp) / "source"
            _submission(source)
            with (source / "weights.npz").open("wb") as stream:
                np.savez(stream, bad=np.array([{"unsafe": 1}], dtype=object))
            with self.assertRaises(ValueError):
                snapshot(source)

    def test_symlink_hardlink_and_extra_file(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
            root = Path(tmp)
            source = root / "source"
            _submission(source)
            (source / "extra").write_text("x")
            with self.assertRaises(ValueError):
                snapshot(source)
            (source / "extra").unlink()
            (source / "model.py").unlink()
            (source / "model.py").symlink_to(source / "config.json")
            with self.assertRaises(ValueError):
                snapshot(source)
            (source / "model.py").unlink()
            os.link(source / "config.json", source / "model.py")
            with self.assertRaises(ValueError):
                snapshot(source)


class RolePacketTests(unittest.TestCase):
    def test_public_and_owner_are_independent(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
            root = Path(tmp)
            public = root / "public-packet" / "public"
            owner = root / "owner-packet" / "owner"
            for folder in (public, owner, public / "train", public / "valid", owner / "test"):
                folder.mkdir(mode=0o700, parents=True)

            def row(folder: Path, sequence_id: str) -> dict:
                filename = hashlib.sha256(sequence_id.encode()).hexdigest() + ".npz"
                path = folder / filename
                with path.open("xb") as stream:
                    np.savez(stream, keypoints=np.zeros((2, 2, 2, 7), np.float32),
                             scores=np.ones((2, 2, 7), np.float32), labels=np.zeros(2, np.uint8))
                os.chmod(path, 0o600)
                return {"id": sequence_id, "file": filename, "frames": 2,
                        "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

            train = row(public / "train", "task1/train/train-a")
            valid = row(public / "valid", "task1/train/valid-b")
            test = row(owner / "test", "task1/test/test-c")
            shared = {"task": "task1", "source_sha256": SOURCE_SHA256,
                      "arrays": ARRAY_SPEC, "vocab": CLASSIC_VOCAB}
            public_manifest = {**shared, "schema": "bpb-calms21-public/1",
                               "splits": {"train": [train], "valid": [valid]},
                               "counts": {"train": {"sequences": 1, "frames": 2},
                                          "valid": {"sequences": 1, "frames": 2}}}
            owner_manifest = {**shared, "schema": "bpb-calms21-owner-test/1",
                              "sequences": [test], "counts": {"sequences": 1, "frames": 2}}
            for path, data in ((public / "manifest.json", public_manifest),
                               (owner / "test-manifest.json", owner_manifest)):
                path.write_text(json.dumps(data))
                os.chmod(path, 0o600)
            public_sha = hashlib.sha256((public / "manifest.json").read_bytes()).hexdigest()
            owner_sha = hashlib.sha256((owner / "test-manifest.json").read_bytes()).hexdigest()
            self.assertEqual(len(_role_packet(public.parent, "valid", public_sha)[1]), 1)
            self.assertEqual(len(_role_packet(owner.parent, "test", owner_sha)[1]), 1)
            with self.assertRaises(ValueError):
                _role_packet(owner.parent, "test", "0" * 64)
            (public / "valid" / valid["file"]).write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                _role_packet(public.parent, "valid", public_sha)


@unittest.skipUnless(os.environ.get("CALMS_TEST_IMAGE"), "pinned Docker image required")
class DockerTests(unittest.TestCase):
    def _run(self, code: str) -> np.ndarray:
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
            root = Path(tmp)
            source, frozen, scratch = root / "source", root / "frozen", root / "scratch"
            _submission(source, code)
            freeze(source, frozen)
            scratch.mkdir(mode=0o700)
            return _predict(os.environ["CALMS_TEST_IMAGE"], frozen,
                            np.zeros((3, 2, 2, 7), dtype=np.float32),
                            np.ones((3, 2, 7), dtype=np.float32),
                            {"task": "task1", "group": "annotator-id_0", "class_count": 4}, scratch)

    def test_numeric_output(self):
        self.assertEqual(self._run(GOOD).shape, (3, 4))

    def test_invalid_probability_rejected(self):
        code = GOOD.replace("1/context[\"class_count\"]", "2.0")
        with self.assertRaises(RuntimeError):
            self._run(code)

    def test_labels_absent(self):
        code = GOOD.replace("return np.full", "assert __import__('os').getuid() != 0\n            assert set(np.load('/input/features.npz', allow_pickle=False).files) == {'keypoints', 'scores'}\n            assert not __import__('pathlib').Path('/owner').exists()\n            return np.full")
        self.assertEqual(self._run(code).shape, (3, 4))

    def test_invalid_shape_rejected(self):
        code = GOOD.replace("(len(keypoints), context[\"class_count\"])", "(len(keypoints)-1, context[\"class_count\"])")
        with self.assertRaises(RuntimeError):
            self._run(code)

    def test_model_mount_read_only(self):
        code = GOOD.replace("return np.full", "open('/model/config.json', 'w').write('tamper')\n            return np.full")
        with self.assertRaises(RuntimeError):
            self._run(code)

    def test_network_disabled(self):
        code = GOOD.replace("return np.full", "__import__('socket').create_connection(('1.1.1.1', 80), timeout=1)\n            return np.full")
        with self.assertRaises(RuntimeError):
            self._run(code)


if __name__ == "__main__":
    unittest.main()
