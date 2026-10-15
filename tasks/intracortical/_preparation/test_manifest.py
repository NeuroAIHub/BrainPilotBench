"""Tamper checks for metadata and public/evaluator role isolation."""

from __future__ import annotations

from copy import deepcopy
import json
import unittest

from check_manifest import MANIFEST, validate_manifest, validate_protocol_files


class ManifestChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = json.loads(MANIFEST.read_text())

    def test_frozen_manifest(self) -> None:
        self.assertEqual(validate_manifest(self.original), 79)
        validate_protocol_files(self.original)

    def test_public_asset_cannot_become_test(self) -> None:
        changed = deepcopy(self.original)
        next(a for a in changed["assets"] if a["role"] == "train")["role"] = "test"
        with self.assertRaises(ValueError):
            validate_manifest(changed)

    def test_path_date_must_match(self) -> None:
        changed = deepcopy(self.original)
        changed["assets"][0]["session_date"] = "20990101"
        with self.assertRaises(ValueError):
            validate_manifest(changed)

    def test_content_cannot_cross_roles(self) -> None:
        changed = deepcopy(self.original)
        source = next(a for a in changed["assets"] if a["task_id"] == "falcon-h1-reach-grasp" and a["role"] == "train")
        target = next(a for a in changed["assets"] if a["task_id"] == "falcon-h1-reach-grasp" and a["role"] == "test")
        target["sha256"] = source["sha256"]
        with self.assertRaises(ValueError):
            validate_manifest(changed)


if __name__ == "__main__":
    unittest.main()
