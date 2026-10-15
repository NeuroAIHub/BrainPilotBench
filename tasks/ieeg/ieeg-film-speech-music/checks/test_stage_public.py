"""Normal-path checks for atomic public staging and exact reuse."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "env" / "stage_public.py"
SPEC = importlib.util.spec_from_file_location("film_stage_public", SCRIPT)
assert SPEC and SPEC.loader
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)


def write(path: Path, body: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"path": path.name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


class PublicStageTests(unittest.TestCase):
    def test_stage_reuse_and_missing_source(self):
        with tempfile.TemporaryDirectory(prefix="bpb-film-stage-test-") as temp:
            root = Path(temp)
            task = root / "repo" / "tasks" / "ieeg" / "film"
            task.mkdir(parents=True)
            STAGE.ROOT = task
            data = root / "data"
            public = data / "derived-v2" / "public"
            subject = public / "opaque123"
            metadata = write(subject / "metadata.json", b'{"subject_id":"opaque123"}\n')
            roles = {}
            for role in ("train", "validation"):
                arrays = write(subject / f"{role}.npz", role.encode())
                labels = write(subject / f"{role}_labels.json", b"{}\n")
                manifest = {"schema": "bpb-ieeg-film-derived-role/2", "role": role,
                            "subjects": [{"subject_id": "opaque123",
                                          "files": {"arrays": arrays, "labels": labels,
                                                    "metadata": metadata}}]}
                role_path = public / f"{role}_manifest.json"
                role_spec = write(role_path, (json.dumps(manifest) + "\n").encode())
                roles[role] = role_spec
            write(task / "contract.json", (json.dumps({"roles": roles}) + "\n").encode())
            destination = root / "agent" / "public_data"

            def run(target: Path, public_root: Path | None = None):
                old = sys.argv
                try:
                    source_args = (["--public-root", str(public_root)] if public_root is not None
                                   else ["--data-root", str(data)])
                    sys.argv = [str(SCRIPT), *source_args, "--destination", str(target)]
                    STAGE.main()
                finally:
                    sys.argv = old

            run(destination)
            self.assertTrue((destination / "opaque123" / "metadata.json").is_file())
            run(destination)
            self.assertEqual((destination / "opaque123" / "train.npz").read_bytes(), b"train")
            workspace = root / "agent" / "workspace_public_data"
            run(workspace, public_root=destination)
            self.assertEqual((workspace / "opaque123" / "validation.npz").read_bytes(), b"validation")
            (subject / "validation.npz").unlink()
            run(destination)
            missing_target = root / "agent" / "missing_public_data"
            with self.assertRaises((ValueError, FileNotFoundError)):
                run(missing_target)
            self.assertFalse(missing_target.exists())
            self.assertEqual(list(missing_target.parent.glob(missing_target.name + ".stage-*")), [])


if __name__ == "__main__":
    unittest.main()
