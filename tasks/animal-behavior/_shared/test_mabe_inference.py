"""MABe frozen artifact and isolated numeric inference boundary tests."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from mabe_inference import _container_batch, freeze_model, snapshot_model


GOOD = '''import numpy as np
def load_model(config, weights_path):
    class Model:
        def predict_proba(self, keypoints, scores, context):
            assert __import__('os').getuid() != 0
            assert set(np.load('/input/features.npz', allow_pickle=False).files) == {'keypoints_000', 'scores_000'}
            assert not __import__('pathlib').Path('/owner').exists()
            return np.full((1800, 4), 0.25, dtype=np.float32)
        def embed(self, keypoints, scores, context):
            return keypoints.reshape(1800, 72).astype(np.float32)
    return Model()
'''


def _source(path: Path, code: str) -> None:
    path.mkdir(mode=0o700)
    (path / "model.py").write_text(code)
    (path / "config.json").write_text("{}")
    with (path / "weights.npz").open("xb") as stream:
        np.savez(stream, weight=np.array([1.0]))


class FreezeTests(unittest.TestCase):
    def test_tamper_symlink_and_pickle_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
            root = Path(tmp)
            source, frozen = root / "source", root / "frozen"
            _source(source, GOOD)
            freeze_model(source, frozen)
            snapshot_model(frozen)
            (frozen / "model.py").write_text("tamper")
            with self.assertRaises(ValueError):
                snapshot_model(frozen)
            (source / "model.py").unlink()
            (source / "model.py").symlink_to(source / "config.json")
            with self.assertRaises(ValueError):
                snapshot_model(source, frozen=False)
            (source / "model.py").unlink()
            (source / "model.py").write_text(GOOD)
            with (source / "weights.npz").open("wb") as stream:
                np.savez(stream, bad=np.array([{"pickle": 1}], dtype=object))
            with self.assertRaises(ValueError):
                snapshot_model(source, frozen=False)


@unittest.skipUnless(os.environ.get("MABE_TEST_IMAGE"), "pinned Docker image required")
class DockerTests(unittest.TestCase):
    def _run(self, code: str, mode: str, count: int = 1):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
            root = Path(tmp)
            source, frozen, scratch = root / "source", root / "frozen", root / "scratch"
            _source(source, code)
            freeze_model(source, frozen)
            scratch.mkdir(mode=0o700)
            keypoints = [np.zeros((1800, 3, 12, 2), np.float32) for _ in range(count)]
            scores = ([np.zeros((1800, 3, 12), np.float32) for _ in range(count)]
                      if mode == "supervised" else [np.empty((1800, 0), np.float32) for _ in range(count)])
            return _container_batch(os.environ["MABE_TEST_IMAGE"], frozen,
                                    keypoints, scores, mode, scratch)

    def test_supervised_independent_probabilities(self):
        code = GOOD.replace("return np.full((1800, 4), 0.25, dtype=np.float32)",
                            "return np.tile(np.array([0.6, 0.6, 0.1, 0.1], dtype=np.float32), (1800, 1))")
        output = self._run(code, "supervised")[0]
        self.assertEqual(output.shape, (1800, 4))
        self.assertGreater(float(output[0].sum()), 1.0)

    def test_representation_batch(self):
        self.assertEqual(len(self._run(GOOD, "representation", 2)), 2)

    def test_invalid_output_rejected(self):
        code = GOOD.replace("np.full((1800, 4), 0.25", "np.full((1799, 4), 0.25")
        with self.assertRaises(RuntimeError):
            self._run(code, "supervised")

    def test_invalid_embedding_dimension_and_nonfinite_rejected(self):
        oversized = GOOD.replace("return keypoints.reshape(1800, 72).astype(np.float32)",
                                 "return np.zeros((1800, 129), dtype=np.float32)")
        with self.assertRaises(RuntimeError):
            self._run(oversized, "representation")
        nonfinite = GOOD.replace("return keypoints.reshape(1800, 72).astype(np.float32)",
                                 "return np.full((1800, 72), np.nan, dtype=np.float32)")
        with self.assertRaises(RuntimeError):
            self._run(nonfinite, "representation")

    def test_network_disabled(self):
        code = GOOD.replace("return np.full", "__import__('socket').create_connection(('1.1.1.1', 80), timeout=1)\n            return np.full")
        with self.assertRaises(RuntimeError):
            self._run(code, "supervised")

    def test_model_mount_read_only(self):
        code = GOOD.replace("return np.full", "open('/model/config.json','w').write('tamper')\n            return np.full")
        with self.assertRaises(RuntimeError):
            self._run(code, "supervised")


if __name__ == "__main__":
    unittest.main()
