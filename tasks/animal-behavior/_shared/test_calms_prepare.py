import hashlib
import json
import math
import os
import stat
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import numpy as np

from calms_prepare import (ARRAY_SPEC, CLASSIC_VOCAB, PREFIX, SOURCE_SHA256,
                           _arrays, _assert_no_symlink_ancestors, _file_digest,
                           _load_split, _reject_duplicate_source_keys,
                           _safe_sequence_id, _write_json, prepare, validate_zip,
                           verify_prepared)


def fixture(root):
    root.mkdir(mode=0o700)
    for relative in ("public", "public/train", "public/valid", "owner", "owner/test"):
        (root / relative).mkdir(mode=0o700)
    ids = [f"task1/train/mouse{i:03d}_task1_annotator1" for i in range(1, 6)]
    ranked = sorted(ids, key=lambda value: hashlib.sha256(("bpb-calms21-valid-v1:" + value).encode()).hexdigest())
    valid = set(ranked[:math.ceil(0.2 * len(ranked))])

    def row(sequence_id, folder):
        filename = hashlib.sha256(sequence_id.encode()).hexdigest() + ".npz"
        path = folder / filename
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            np.savez(stream, keypoints=np.zeros((2, 2, 2, 7), dtype=np.float32),
                     scores=np.ones((2, 2, 7), dtype=np.float32),
                     labels=np.array([0, 3], dtype=np.uint8))
        size, digest = _file_digest(path)
        return {"id": sequence_id, "file": filename, "frames": 2, "bytes": size, "sha256": digest}

    splits = {"train": [], "valid": []}
    for sequence_id in ids:
        role = "valid" if sequence_id in valid else "train"
        splits[role].append(row(sequence_id, root / "public" / role))
    test = [row("task1/test/mouse006_task1_annotator1", root / "owner/test")]
    public = {"schema": "bpb-calms21-public/1", "task": "task1", "source_sha256": SOURCE_SHA256,
              "vocab": CLASSIC_VOCAB, "arrays": ARRAY_SPEC, "splits": splits,
              "counts": {role: {"sequences": len(rows), "frames": 2 * len(rows)} for role, rows in splits.items()}}
    owner = {"schema": "bpb-calms21-owner-test/1", "task": "task1", "source_sha256": SOURCE_SHA256,
             "vocab": CLASSIC_VOCAB, "arrays": ARRAY_SPEC, "sequences": test,
             "counts": {"sequences": 1, "frames": 2}}
    _write_json(root / "public/manifest.json", public)
    _write_json(root / "owner/test-manifest.json", owner)
    _write_json(root / "preparation-evidence.json", {"schema": "fixture"})
    _write_json(root / "complete.json", {"schema": "bpb-calms21-complete/1", "source_sha256": SOURCE_SHA256,
                                         "public_manifest_sha256": _file_digest(root / "public/manifest.json")[1],
                                         "owner_manifest_sha256": _file_digest(root / "owner/test-manifest.json")[1]})
    return public, owner


class NativeSchemaTests(unittest.TestCase):
    def test_shape_and_vocabulary(self):
        row = {"annotations": [0, 3], "keypoints": np.zeros((2, 2, 2, 7)).tolist(),
               "scores": np.ones((2, 2, 7)).tolist(),
               "metadata": {"annotator-id": 0, "vocab": {"attack": 0, "investigation": 1, "mount": 2, "other": 3}}}
        x, scores, labels = _arrays(row)
        self.assertEqual((x.shape, scores.shape, labels.dtype), ((2, 2, 2, 7), (2, 2, 7), np.dtype("uint8")))
        row["annotations"] = [0]
        with self.assertRaisesRegex(ValueError, "shape"):
            _arrays(row)
        row["annotations"] = [0, 3]
        row["metadata"]["vocab"]["other"] = 4
        with self.assertRaisesRegex(ValueError, "vocabulary"):
            _arrays(row)
        row["metadata"]["vocab"]["other"] = 3
        row["keypoints"][0][0][0][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            _arrays(row)

    def test_sequence_paths_and_zip_links_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "sequence ID"):
            _safe_sequence_id("task1/test/../train/mouse001", "train")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.zip"
            with ZipFile(path, "w") as zf:
                info = ZipInfo(PREFIX + "calms21_task1_train.json")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, "elsewhere")
            with ZipFile(path) as zf, self.assertRaisesRegex(ValueError, "links"):
                validate_zip(zf)

    def test_duplicate_source_keys_and_empty_group_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.zip"
            member = PREFIX + "calms21_task1_train.json"
            with ZipFile(path, "w") as zf:
                zf.writestr(member, '{"annotator-id_0":{"a":{"metadata":{"vocab":{"other":3,"other":4}}}}}')
            with ZipFile(path) as zf, self.assertRaisesRegex(ValueError, "duplicate"):
                _reject_duplicate_source_keys(zf, member)
            with ZipFile(path, "w") as zf:
                zf.writestr(member, '{"annotator-id_0":{}}')
            with ZipFile(path) as zf, self.assertRaisesRegex(ValueError, "empty"):
                _load_split(zf, "train", Path(folder))

    def test_bound_manifest_and_tampered_npz(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "prepared"
            public, _ = fixture(root)
            self.assertEqual(verify_prepared(root, include_owner=True)["owner_test_sequences"], 1)
            row = public["splits"]["train"][0]
            with (root / "public/train" / row["file"]).open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_prepared(root)

    def test_extra_public_file_and_missing_completion_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "prepared"
            fixture(root)
            (root / "public/train/extra.txt").write_text("extra")
            with self.assertRaisesRegex(ValueError, "file set"):
                verify_prepared(root)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "prepared"
            fixture(root)
            (root / "complete.json").unlink()
            with self.assertRaisesRegex(ValueError, "file set"):
                verify_prepared(root)

    def test_symlink_ancestor_and_manifest_tamper_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root = base / "prepared"
            fixture(root)
            (base / "linked").symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                _assert_no_symlink_ancestors(base / "linked/public/manifest.json")
            manifest = root / "public/manifest.json"
            with manifest.open("a") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "completion binding"):
                verify_prepared(root)

    def test_symlink_output_parent_and_file_mode_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            target = base / "target"
            target.mkdir()
            (base / "linked").symlink_to(target, target_is_directory=True)
            source = base / "source.zip"
            source.write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "symlink"):
                prepare(source, base / "linked/prepared")
            root = base / "prepared"
            public, _ = fixture(root)
            row = public["splits"]["train"][0]
            os.chmod(root / "public/train" / row["file"], 0o644)
            with self.assertRaisesRegex(ValueError, "0600"):
                verify_prepared(root)


if __name__ == "__main__":
    unittest.main()
