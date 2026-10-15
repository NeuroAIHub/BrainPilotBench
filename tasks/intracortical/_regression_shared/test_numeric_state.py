"""Normal host validation checks for M1 and M2 persisted numeric state."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


DOMAIN = Path(__file__).resolve().parent.parent
TASKS = ("falcon-m1-emg", "falcon-m2-finger-velocity")


def load_validator(task_id: str):
    path = DOMAIN / task_id / "checks/score.py"
    spec = importlib.util.spec_from_file_location(task_id.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_staged_config_and_state


def state_file(dtype: str, shape: list[int], payload: bytes) -> bytes:
    header = {"weight": {"dtype": dtype, "shape": shape,
                         "data_offsets": [0, len(payload)]}}
    encoded = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack("<Q", len(encoded)) + encoded + payload


class NumericStateTests(unittest.TestCase):
    def call(self, task_id: str, data: bytes) -> None:
        with tempfile.TemporaryDirectory(prefix="bpb-state-check-") as temporary:
            root = Path(temporary)
            (root / "config.json").write_text("{}\n")
            (root / "weights.safetensors").write_bytes(data)
            load_validator(task_id)(root)

    def test_bfloat16_finite_and_nonfinite(self) -> None:
        for task_id in TASKS:
            with self.subTest(task=task_id, value="finite 1.0"):
                self.call(task_id, state_file("BF16", [1], struct.pack("<H", 0x3F80)))
            for bits in (0x7F80, 0xFF80, 0x7FC1):
                with self.subTest(task=task_id, bits=hex(bits)):
                    with self.assertRaisesRegex(ValueError, "nonfinite persisted numeric state"):
                        self.call(task_id, state_file("BF16", [1], struct.pack("<H", bits)))

    def test_numeric_budget_and_shape(self) -> None:
        for task_id in TASKS:
            with self.subTest(task=task_id, rule="numeric budget"):
                with self.assertRaisesRegex(ValueError, "exceeds 10M"):
                    self.call(task_id, state_file("BF16", [10_000_001], b"\0\0"))
            with self.subTest(task=task_id, rule="negative shape"):
                with self.assertRaisesRegex(ValueError, "invalid numeric state entry"):
                    self.call(task_id, state_file("BF16", [-1], b"\0\0"))
            with self.subTest(task=task_id, rule="payload shape"):
                with self.assertRaisesRegex(ValueError, "length contradicts shape"):
                    self.call(task_id, state_file("BF16", [2], b"\0\0"))


if __name__ == "__main__":
    unittest.main()
