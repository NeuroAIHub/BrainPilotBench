"""Focused checks for family split identity and unsafe source rejection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import zipfile

import numpy as np

from calms_family_prepare import _pose_identity, _recording_id, _reject_duplicate_source_keys, _safe_id, _valid_recordings, _validate_zip
from calms_family_delivery import iter_rows


class FamilyPreparationTest(unittest.TestCase):
    def test_local_counters_are_distinct_but_equal_poses_share_identity(self) -> None:
        self.assertNotEqual(_recording_id("task2", "task2/annotator1/train/mouse007_task2_annotator1"),
                            _recording_id("task2", "task2/annotator5/train/mouse007_task2_annotator5"))
        pose = np.zeros((2, 2, 2, 7), dtype=np.float32)
        score = np.ones((2, 2, 7), dtype=np.float32)
        self.assertEqual(_pose_identity(pose, score), _pose_identity(pose.copy(), score.copy()))
        pose[0, 0, 0, 0] = 1
        self.assertNotEqual(_pose_identity(pose, score), _pose_identity(np.zeros_like(pose), score))

    def test_split_and_group_are_bound_to_sequence_id(self) -> None:
        with self.assertRaises(ValueError):
            _safe_id("task2/annotator2/train/mouse007_task2_annotator2", "task2", "annotator-id_1", "train")
        with self.assertRaises(ValueError):
            _safe_id("task3/approach/test/mouse007_task3_approach", "task3", "approach", "train")
        with self.assertRaises(ValueError):
            _safe_id("task3/approach/train/../test/mouse007", "task3", "approach", "train")

    def test_singleton_target_stays_in_train_even_if_shared(self) -> None:
        groups = {"singleton": {"shared"}, "other": {"shared", "only_other"}}
        selected = _valid_recordings(groups)
        self.assertNotIn("shared", selected)
        self.assertEqual(selected, {"only_other"})

    def test_nested_duplicate_source_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("sample.json", '{"g":{"id":{"metadata":{"vocab":1,"vocab":2}}}}')
            with zipfile.ZipFile(path) as zf:
                with self.assertRaisesRegex(ValueError, "duplicate source JSON key"):
                    _reject_duplicate_source_keys(zf, "sample.json")

    def test_unexpected_zip_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("../escape", b"x")
            with zipfile.ZipFile(path) as zf:
                with self.assertRaises(ValueError):
                    _validate_zip(zf, "task2")

    def test_delivery_rows_have_stable_order_and_group_filter(self) -> None:
        manifest = {"schema": "bpb-calms21-family-public/1", "vocab_by_group": {"a": {}, "b": {}},
                    "splits": {"train": [{"group": "b", "id": "2"}, {"group": "a", "id": "1"}], "valid": []}}
        self.assertEqual([row["group"] for row in iter_rows(manifest, "train")], ["a", "b"])
        self.assertEqual([row["group"] for row in iter_rows(manifest, "train", group="b")], ["b"])
        with self.assertRaises(ValueError):
            iter_rows(manifest, "test")


if __name__ == "__main__":
    unittest.main()
