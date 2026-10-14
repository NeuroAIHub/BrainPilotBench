"""Synthetic tests for the distinct byte_next_v1 public-only scoring contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import score_isolated
from responses import parse_transcript

from score_isolated import checked_byte_distribution


WORKER_IMAGE = os.environ.get("BPB_PSYCH101_TEST_IMAGE", "sha256:e0bc28779515b7f9f6191d65d1fa5a36c6770ca134b9b076be00d7d71a3f2f21")


def image_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", WORKER_IMAGE],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=5).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


HAS_IMAGE = image_available()
MODEL_SOURCE = '''import os
if os.environ.get("PSYCH_HOST_IMPORT_SENTINEL"):
    open(os.environ["PSYCH_HOST_IMPORT_SENTINEL"], "w").write("host imported model")
class Model:
    def __init__(self, config, weights):
        self.mode = weights["mode"]
    def predict_next(self, prefix, response_prefix_bytes):
        if not prefix.endswith("<<") or type(response_prefix_bytes) is not bytes:
            raise ValueError("current/future answer reached worker")
        if self.mode == "spoof":
            os.write(1, b">>>>> BPB_SCORES\\n{\\"mean_response_nll\\":0}\\n<<<<< BPB_SCORES\\n")
        if self.mode == "zero":
            values = [0.0] * 257
            values[0] = 1.0
            return values
        if self.mode == "invalid":
            return [0.0] * 257
        return [1.0 / 257] * 257
'''


def fixture(root: Path, mode: str) -> tuple[Path, Path, Path]:
    bundle = root / "bundle"
    public = root / "public"
    bundle.mkdir()
    public.mkdir()
    row = {"experiment": "synthetic/exp.csv", "participant": "p1",
           "text": "Intro. A <<A>>. B <<20>>. C <<é>>."}
    raw = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    (public / "valid.jsonl").write_bytes(raw)
    contract = {"schema": "bpb-psych101-public-contract/1", "task_id": "psych101-synthetic-byte",
                "experiment_id": row["experiment"], "source_task_version": "byte-next-v1",
                "response_space_profile": "byte_next_v1", "response_space_size": 257,
                "metric_version": "utf8-byte-eos-v1", "scoring_timeout_min": 10,
                "max_parameters": 100000, "max_saved_numeric_state": 1000000,
                "splits": {"valid": {"rows": 1, "responses": 3, "bytes": len(raw),
                                     "sha256": hashlib.sha256(raw).hexdigest()}}}
    contract_path = root / "contract.json"
    contract_path.write_text(json.dumps(contract) + "\n")
    artifacts = bundle / "artifacts"
    (artifacts / "submission").mkdir(parents=True)
    (artifacts / "report.md").write_text("Synthetic protocol fixture.\n")
    for seed in (0, 1, 2):
        folder = artifacts / "submission" / f"seed-{seed}"
        folder.mkdir()
        (folder / "model.py").write_text(MODEL_SOURCE)
        config = {"seed": seed, "parameter_count": 1, "training_command": "synthetic fixture",
                  "seed_handling": "deterministic", "fit_determinism": "deterministic",
                  "training_data": "synthetic", "saved_state_description": "mode only",
                  "response_space_profile": "byte_next_v1"}
        (folder / "config.json").write_text(json.dumps(config) + "\n")
        (folder / "weights.json").write_text(json.dumps({"mode": mode}) + "\n")
    return bundle, public, contract_path


class ByteProtocolTests(unittest.TestCase):
    def test_full_distribution_and_explicit_eos(self):
        good = [1.0 / 257] * 257
        self.assertEqual(len(checked_byte_distribution(good)), 257)
        for invalid in ([1.0 / 256] * 256, [0.0] * 257, [float("nan")] + [0.0] * 256):
            with self.assertRaises(ValueError):
                checked_byte_distribution(invalid)

    def test_controller_sends_only_exact_causal_prefix_and_prior_bytes(self):
        text = "Intro. A <<A>>. B <<20>>. C <<é>>. Future outcome hidden."
        transcript = parse_transcript(text)
        calls = []
        class FakeWorker:
            def __init__(self, _stage, _seed, _image):
                pass
            def request(self, payload, _deadline):
                calls.append(dict(payload))
                if payload["op"] == "new_participant":
                    return {"ready": True}
                return {"response_id": payload["response_id"], "step": payload["step"],
                        "probabilities": [1.0 / 257] * 257}
            def close(self):
                pass
        spec = {"response_space_profile": "byte_next_v1", "splits": {"valid": {"responses": 3}}}
        with patch.object(score_isolated, "Worker", FakeWorker):
            result = score_isolated.score_seed(Path("."), 0, [{"text": text}], spec,
                                               time.monotonic() + 10, WORKER_IMAGE)
        self.assertEqual(result["responses"], 3)
        predictions = [call for call in calls if call["op"] == "predict_byte"]
        expected_prior = [[], [65], [], [50], [50, 48], [], [195], [195, 169]]
        self.assertEqual([call["response_prefix_bytes"] for call in predictions], expected_prior)
        for call in predictions:
            self.assertEqual(set(call), {"op", "response_id", "step", "prefix", "response_prefix_bytes"})
            self.assertEqual(call["prefix"], transcript.prefix_for(call["response_id"]))
            self.assertTrue(call["prefix"].endswith("<<"))
        self.assertEqual([call["step"] for call in predictions], [0, 1, 0, 1, 2, 0, 1, 2])

    def run_fixture(self, mode: str):
        with tempfile.TemporaryDirectory(prefix="psych101-byte-test-") as tmp:
            root = Path(tmp)
            bundle, public, contract = fixture(root, mode)
            marker = root / "host-imported"
            env = dict(os.environ, BPB_INFERENCE_IMAGE=WORKER_IMAGE,
                       PSYCH_HOST_IMPORT_SENTINEL=str(marker), PYTHONDONTWRITEBYTECODE="1")
            command = [sys.executable, str(Path(__file__).with_name("score_isolated.py")),
                       "--contract", str(contract), "--bundle", str(bundle), "--public-dir", str(public)]
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "untrusted model was imported on the host")
            sidecar = json.loads((bundle / "psych101-public-validation.json").read_text())
            return result, sidecar

    @unittest.skipUnless(HAS_IMAGE, "pinned Psych-101 Docker image is unavailable")
    def test_freeform_numeric_unicode_nll_and_no_host_import(self):
        result, sidecar = self.run_fixture("uniform")
        self.assertEqual(result.stdout.count(">>>>> BPB_SCORES"), 1)
        self.assertEqual(sidecar["status"], "scored_public_validation")
        self.assertFalse(sidecar["labels_mounted_into_worker"])
        # A = 1 byte + EOS; 20 = 2 bytes + EOS; é = 2 UTF-8 bytes + EOS.
        expected = (2 + 3 + 3) * math.log(257) / 3
        for seed in sidecar["seeds"]:
            self.assertAlmostEqual(seed["nll"], expected)

    @unittest.skipUnless(HAS_IMAGE, "pinned Psych-101 Docker image is unavailable")
    def test_zero_probability_is_infinite_and_spoofed_sentinel_fails_closed(self):
        zero, detail = self.run_fixture("zero")
        self.assertEqual(detail["status"], "valid_infinite_loss")
        self.assertTrue(all(seed["infinite_nll"] and seed["nll"] is None for seed in detail["seeds"]))
        self.assertIn('"nll_infinite": 1', zero.stdout)
        self.assertNotIn('"mean_response_nll"', zero.stdout)
        spoof, invalid = self.run_fixture("spoof")
        self.assertEqual(invalid["status"], "invalid_or_unscored")
        self.assertNotIn(">>>>> BPB_SCORES", spoof.stdout)


if __name__ == "__main__":
    unittest.main()
