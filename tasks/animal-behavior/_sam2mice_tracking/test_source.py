"""Small software fixtures for source integrity and explicit frame pairing."""

import io
import stat
import unittest
import zipfile

from prepare_source import GT_PREFIX, RAW_PREFIX, box_bounds, continuous_runs, equal_width_blocks, parse_truth, selected_members


def archive_with(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


class SourceTests(unittest.TestCase):
    def test_selected_sources_exclude_prediction_folders(self):
        with archive_with([
            (RAW_PREFIX + "00001.jpg", b"frame"),
            (GT_PREFIX + "00001.txt", b"0 0.5 0.5 0.1 0.2\n"),
            ("SAM2_Mice/benchmark_data/openfield_five_mouse_seg/frames/00002.jpg", b"overlay"),
            ("SAM2_Mice/YOLO_data/labels/train/00002.txt", b"automatic"),
        ]) as archive:
            raw, truth = selected_members(archive)
        self.assertEqual(list(raw), [1])
        self.assertEqual(list(truth), [1])

    def test_unsafe_zip_path_is_rejected(self):
        with archive_with([("../outside", b"x")]) as archive:
            with self.assertRaisesRegex(ValueError, "unsafe member"):
                selected_members(archive)

    def test_symlink_zip_member_is_rejected(self):
        entry = zipfile.ZipInfo(RAW_PREFIX + "00001.jpg")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with archive_with([(entry, b"outside")]) as archive:
            with self.assertRaisesRegex(ValueError, "linked member"):
                selected_members(archive)

    def test_ids_are_retained_when_row_order_changes(self):
        boxes = parse_truth(b"4 0.5 0.5 0.1 0.2\n1 0.4 0.3 0.2 0.1\n")
        self.assertEqual([box[0] for box in boxes], [4, 1])

    def test_bad_truth_is_rejected(self):
        for data in (b"0 nan 0.5 0.1 0.2\n", b"0 1.2 0.5 0.1 0.2\n",
                     b"0 0.5 0.5 0.1\n", b"0 0.5 0.5 0.1 0.2\n0 0.5 0.5 0.1 0.2\n"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_truth(data)

    def test_explicit_empty_truth_is_retained(self):
        self.assertEqual(parse_truth(b""), [])

    def test_corner_screen_has_zero_tolerance_and_preserves_values(self):
        boxes = {0: [(3, 0.05, 0.5, 0.1000002, 0.1)]}
        bounds = box_bounds(boxes, [0])
        self.assertEqual(bounds["outside_objects"], 1)
        self.assertLess(bounds["minimum"], 0)
        self.assertEqual(boxes[0][0][3], 0.1000002)

    def test_missing_frames_break_sequences(self):
        self.assertEqual(continuous_runs([1, 2, 4, 7, 8]), [
            {"start": 1, "end": 2, "frames": 2},
            {"start": 4, "end": 4, "frames": 1},
            {"start": 7, "end": 8, "frames": 2},
        ])

    def test_block_preview_uses_original_indices(self):
        blocks = equal_width_blocks([1, 2, 10], 24)
        self.assertEqual(blocks[0]["paired_frames"], 1)
        self.assertEqual(blocks[1]["paired_frames"], 1)
        self.assertEqual(blocks[5]["paired_frames"], 1)
        self.assertEqual(sum(block["paired_frames"] for block in blocks), 3)


if __name__ == "__main__":
    unittest.main()
