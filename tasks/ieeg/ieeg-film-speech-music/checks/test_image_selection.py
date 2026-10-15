"""Normal CLI image selection and immutable-image gate checks."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("film_run_image_test", SCRIPT)
assert SPEC and SPEC.loader
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)

IMAGE_ID = "sha256:" + "a" * 64
REGISTRY_DIGEST = "registry.example.org/film/worker@sha256:" + "b" * 64


class ImageSelectionTests(unittest.TestCase):
    def test_env_and_explicit_image(self):
        with patch.dict(os.environ, {"BPB_INFERENCE_IMAGE": IMAGE_ID}):
            self.assertEqual(RUN.resolve_image(None), IMAGE_ID)
            self.assertEqual(RUN.resolve_image(REGISTRY_DIGEST), REGISTRY_DIGEST)

    def test_missing_or_mutable_image_fails(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "immutable image"):
                RUN.resolve_image(None)
            with self.assertRaisesRegex(ValueError, "immutable image"):
                RUN.resolve_image("film-worker:latest")
        self.assertEqual(RUN.resolve_image(REGISTRY_DIGEST), REGISTRY_DIGEST)


if __name__ == "__main__":
    unittest.main()
