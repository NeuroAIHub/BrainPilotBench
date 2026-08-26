#!/usr/bin/env python3
"""Live Docker mount/isolation smoke for the Sleep evaluator child."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


def _load_evaluator():
    path = Path(__file__).with_name("evaluate_external.py")
    spec = importlib.util.spec_from_file_location("sleep_docker_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EVALUATOR = _load_evaluator()


@unittest.skipUnless(
    os.environ.get("BPB_DOCKER_TEST") == "1" and os.environ.get("BPB_TEST_INFERENCE_IMAGE"),
    "set BPB_DOCKER_TEST=1 and BPB_TEST_INFERENCE_IMAGE",
)
class DockerIsolationTest(unittest.TestCase):
    def test_sleep_mounts_are_read_only_networkless_and_output_is_writable(self):
        previous = os.environ.get("BPB_INFERENCE_IMAGE")
        with tempfile.TemporaryDirectory(prefix="bpb-sleep-docker-smoke-") as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            sandbox = root / "sandbox"
            private = root / "private"
            train_dir = private / "train_edf"
            test_dir = private / "test_edf"
            manifest_dir = private / "manifests"
            out_dir = root / "out"
            for directory in (scripts, sandbox, train_dir, test_dir, manifest_dir, out_dir):
                directory.mkdir(parents=True, exist_ok=True)
            model = sandbox / "sleep_agent_model.py"
            train_file = train_dir / "train.edf"
            test_file = test_dir / "test.edf"
            manifest = manifest_dir / "subjects.json"
            host_secret = root / "host-secret.txt"
            for path, value in ((model, "model"), (train_file, "train"), (test_file, "test"), (manifest, "{}"), (host_secret, "secret")):
                path.write_text(value, encoding="utf-8")
            runner = scripts / "mount_smoke.py"
            runner.write_text(
                "import argparse, os, pathlib, socket\n"
                "p=argparse.ArgumentParser()\n"
                "p.add_argument('--model-source'); p.add_argument('--train-edf-root'); p.add_argument('--test-edf-root'); p.add_argument('--manifest-dir'); p.add_argument('--out')\n"
                "a,_=p.parse_known_args()\n"
                f"assert not pathlib.Path({str(host_secret)!r}).exists(), 'host path leaked'\n"
                "assert not any('TOKEN' in k or 'PRIVATE' in k for k in os.environ), 'secret env leaked'\n"
                "for name in (a.model_source,a.train_edf_root,a.test_edf_root,a.manifest_dir):\n"
                "    try: (pathlib.Path(name) if pathlib.Path(name).is_file() else pathlib.Path(name)/'mutation').write_text('mutated')\n"
                "    except OSError: pass\n"
                "    else: raise SystemExit('read-only input was writable')\n"
                "try: socket.create_connection(('1.1.1.1',53),timeout=0.5)\n"
                "except OSError: pass\n"
                "else: raise SystemExit('network leaked')\n"
                "pathlib.Path(a.out).write_text('ok')\n",
                encoding="utf-8",
            )
            out_csv = out_dir / "pred.csv"
            try:
                os.environ["BPB_INFERENCE_IMAGE"] = os.environ["BPB_TEST_INFERENCE_IMAGE"]
                EVALUATOR.run_child_docker(
                    runner, private, sandbox, out_csv, [0], [1], [2],
                    use_gpu=False,
                )
                self.assertEqual(out_csv.read_text(encoding="utf-8"), "ok")
            finally:
                if previous is None:
                    os.environ.pop("BPB_INFERENCE_IMAGE", None)
                else:
                    os.environ["BPB_INFERENCE_IMAGE"] = previous


if __name__ == "__main__":
    unittest.main()
