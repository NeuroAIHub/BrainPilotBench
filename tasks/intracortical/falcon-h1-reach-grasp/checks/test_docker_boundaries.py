"""Optional real-Docker isolation tests; fixture model is imported only in Docker."""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

import score

IMAGE = os.environ.get("BPB_H1_DOCKER_IMAGE")


def fixture_submission(root: Path, *, mutate=False, probe_future=False):
    root.mkdir()
    probe = """
        import select, sys
        if select.select([sys.stdin.buffer], [], [], 0)[0]:
            raise RuntimeError('future stdin was readable during forward')
        from pathlib import Path
        if Path('/input/x.npy').exists() or Path('/input/y.npy').exists() or Path('/task').exists():
            raise RuntimeError('full input or labels were mounted')
    """ if probe_future else ""
    mutation = "self.linear.weight.add_(1)" if mutate else "pass"
    (root / "model.py").write_text(
        "import torch\n"
        "class Model(torch.nn.Module):\n"
        "    def __init__(self, config):\n"
        "        super().__init__()\n"
        "        self.linear = torch.nn.Linear(176, 7, bias=False)\n"
        "    def reset(self):\n"
        "        return None\n"
        "    def forward(self, x, trial_start=False):\n"
        + probe + f"        {mutation}\n" +
        "        return self.linear(x)\n")
    (root / "config.json").write_text("{}")
    header = json.dumps({"linear.weight": {"dtype": "F32", "shape": [7, 176],
                                             "data_offsets": [0, 7 * 176 * 4]}}).encode()
    (root / "weights.safetensors").write_bytes(struct.pack("<Q", len(header)) + header +
                                                 bytes(7 * 176 * 4))
    for path in root.iterdir():
        path.chmod(0o444)


@unittest.skipUnless(IMAGE, "set BPB_H1_DOCKER_IMAGE to an immutable image ID")
class DockerBoundaryTests(unittest.TestCase):
    def test_causal_stream_has_no_future_bin_or_label_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary) / "submission"
            fixture_submission(staged, probe_future=True)
            docker = score.LockedDocker(IMAGE, staged, Path(score.__file__).with_name("worker.py"),
                                        total_seconds=120)
            try:
                docker.exchange("reset")
                self.assertEqual(docker.exchange("step", x=[0.] * 176, trial_start=False).shape, (7,))
                self.assertEqual(docker.exchange("step", x=[1.] * 176, trial_start=True).tolist(), [0.] * 7)
                docker.exchange("end")
            finally:
                docker.close()

    def test_registered_state_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary) / "submission"
            fixture_submission(staged, mutate=True)
            docker = score.LockedDocker(IMAGE, staged, Path(score.__file__).with_name("worker.py"),
                                        total_seconds=120)
            try:
                docker.exchange("reset")
                with self.assertRaises(ValueError):
                    docker.exchange("step", x=[0.] * 176, trial_start=False)
            finally:
                docker.close()


if __name__ == "__main__":
    unittest.main()
