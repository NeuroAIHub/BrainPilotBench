"""Audit author tracking annotations and original frames from a verified source ZIP."""

import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

import numpy as np
from PIL import Image, ImageDraw

from fetch_sources import FILE_NAME, verified_receipt


RAW_PREFIX = "SAM2_Mice/benchmark_data/openfield_five_mouse/"
GT_PREFIX = "SAM2_Mice/benchmark_data/ground_truth_bb_labels/"
FRAME_PATTERN = re.compile(r"[0-9]{5}")
QC_TARGET_INDICES = (0, 100, 200, 300, 400, 500)
UPSTREAM = "80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def selected_members(archive):
    raw = {}
    truth = {}
    names = set()
    for entry in archive.infolist():
        name = entry.filename
        path = PurePosixPath(name)
        if name in names or path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("archive has a duplicate or unsafe member name")
        names.add(name)
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError("archive contains a linked member")
        for prefix, extension, selected, limit in (
            (RAW_PREFIX, ".jpg", raw, 16 * 1024 * 1024),
            (GT_PREFIX, ".txt", truth, 65536),
        ):
            if not name.startswith(prefix) or entry.is_dir():
                continue
            relative = name[len(prefix):]
            if not relative.endswith(extension) or not FRAME_PATTERN.fullmatch(relative[:-4]):
                raise ValueError("unexpected file in the selected raw-frame or ground-truth directory")
            if entry.file_size > limit or entry.flag_bits & 1:
                raise ValueError("selected member is oversized or encrypted")
            selected[int(relative[:-4])] = entry
    if not raw or not truth:
        raise ValueError("source archive lacks the selected original frames or author annotations")
    return raw, truth


def read_member(archive, entry):
    with archive.open(entry) as source:
        data = source.read(entry.file_size + 1)
    if len(data) != entry.file_size:
        raise ValueError("ZIP member differs from its declared size")
    return data


def parse_truth(data):
    boxes = []
    ids = set()
    for line in data.decode("utf-8").splitlines():
        fields = line.split()
        if len(fields) != 5:
            raise ValueError("author truth must contain ID, center x/y and width/height")
        object_id = int(fields[0])
        if str(object_id) != fields[0] or object_id < 0 or object_id in ids:
            raise ValueError("author object IDs must be unique nonnegative integers per frame")
        coordinates = tuple(float(value) for value in fields[1:])
        cx, cy, width, height = coordinates
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("annotation contains a nonfinite coordinate")
        if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < width <= 1 and 0 < height <= 1):
            raise ValueError("annotation is outside the normalized box contract")
        ids.add(object_id)
        boxes.append((object_id, cx, cy, width, height))
    return boxes


def continuous_runs(indices):
    runs = []
    for index in sorted(indices):
        if not runs or index != runs[-1]["end"] + 1:
            runs.append({"start": index, "end": index, "frames": 1})
        else:
            runs[-1]["end"] = index
            runs[-1]["frames"] += 1
    return runs


def equal_width_blocks(indices, frame_count):
    blocks = []
    for block_index in range(12):
        start = block_index * frame_count // 12
        end = (block_index + 1) * frame_count // 12
        runs = continuous_runs(index for index in indices if start <= index < end)
        blocks.append({"block_index": block_index, "start": start, "end_exclusive": end,
                       "paired_frames": sum(run["frames"] for run in runs), "runs": runs})
    return blocks


def difference_hash(image):
    gray = np.asarray(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS))
    bits = np.packbits(gray[:, 1:] > gray[:, :-1]).tobytes()
    return int.from_bytes(bits, "big")


def identity_continuity(boxes_by_frame, indices):
    displacements = defaultdict(list)
    large_steps = []
    identity_set_changes = []
    for first, second in zip(indices, indices[1:]):
        if second != first + 1:
            continue
        before = {box[0]: box[1:3] for box in boxes_by_frame[first]}
        after = {box[0]: box[1:3] for box in boxes_by_frame[second]}
        if set(before) != set(after):
            identity_set_changes.append({"first": first, "second": second})
        for object_id in set(before) & set(after):
            distance = math.dist(before[object_id], after[object_id])
            displacements[object_id].append(distance)
            if distance > 0.25:
                large_steps.append({"first": first, "second": second, "object_id": object_id})
    return {
        "scope": "Consecutive paired source frames only. Missing frames break continuity.",
        "normalized_center_displacement": [
            {"object_id": object_id, "transitions": len(values), "median": float(np.median(values)),
             "p95": float(np.percentile(values, 95)), "maximum": max(values)}
            for object_id, values in sorted(displacements.items())
        ],
        "identity_set_changes": identity_set_changes,
        "steps_over_quarter_image_diagonal_axes": large_steps,
        "interpretation": "A geometric screening statistic cannot independently confirm animal identity.",
    }


def box_bounds(boxes_by_frame, indices):
    minimum = math.inf
    maximum = -math.inf
    outside = []
    objects = 0
    for index in indices:
        for object_id, cx, cy, width, height in boxes_by_frame[index]:
            corners = (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)
            minimum = min(minimum, *corners)
            maximum = max(maximum, *corners)
            objects += 1
            if min(corners) < 0 or max(corners) > 1:
                outside.append({"frame_index": index, "object_id": object_id})
    return {"objects": objects, "minimum": minimum if objects else None,
            "maximum": maximum if objects else None, "outside_objects": len(outside),
            "outside_object_locations": outside, "tolerance": 0}


def preview_frames(output_dir, pairs, boxes_by_frame):
    indices = [row["frame_index"] for row in pairs]
    selected = sorted({min(indices, key=lambda index: (abs(index - target), index))
                       for target in QC_TARGET_INDICES})
    colors = ("#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00")
    tiles = []
    for index in selected:
        with Image.open(output_dir / "raw_frames" / f"{index:05d}.jpg") as source:
            image = source.convert("RGB")
        width, height = image.size
        draw = ImageDraw.Draw(image)
        for object_id, cx, cy, bw, bh in boxes_by_frame[index]:
            corners = ((cx - bw / 2) * width, (cy - bh / 2) * height,
                       (cx + bw / 2) * width, (cy + bh / 2) * height)
            color = colors[object_id % len(colors)]
            draw.rectangle(corners, outline=color, width=4)
            draw.text((corners[0] + 3, corners[1] + 3), str(object_id), fill=color,
                      stroke_width=1, stroke_fill="white")
        image.thumbnail((600, 480))
        tile = Image.new("RGB", (620, 520), "white")
        tile.paste(image, (10, 30))
        ImageDraw.Draw(tile).text((10, 8), f"Source frame {index:05d} / author GT boxes", fill="black")
        tiles.append(tile)
    columns = 3
    montage = Image.new("RGB", (columns * 620, math.ceil(len(tiles) / columns) * 520), "white")
    for position, tile in enumerate(tiles):
        montage.paste(tile, ((position % columns) * 620, (position // columns) * 520))
    qc_dir = output_dir / "visual-qc"
    qc_dir.mkdir()
    montage.save(qc_dir / "author-box-overlay.png")
    return {"selection": "nearest paired source index to each predetermined target; ties use lower index",
            "target_indices": list(QC_TARGET_INDICES), "selected_indices": selected,
            "overlay": "visual-qc/author-box-overlay.png", "human_review": "pending"}


def prepare(archive_path, output_dir):
    source_receipt = verified_receipt(archive_path)
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output_dir / "raw_frames").mkdir()
    (output_dir / "ground_truth").mkdir()
    pairs = []
    image_sizes = Counter()
    id_counts = Counter()
    id_sets = Counter()
    boxes_by_frame = {}
    raw_hashes = defaultdict(list)
    pixel_hashes = defaultdict(list)
    truth_hashes = defaultdict(list)
    perceptual_hashes = {}
    with zipfile.ZipFile(archive_path) as archive:
        raw, truth = selected_members(archive)
        common = sorted(set(raw) & set(truth))
        for index, entry in sorted(truth.items()):
            data = read_member(archive, entry)
            boxes = parse_truth(data)
            truth_hashes[sha256(data)].append(index)
            boxes_by_frame[index] = boxes
            id_counts[len(boxes)] += 1
            id_sets[tuple(sorted(box[0] for box in boxes))] += 1
            (output_dir / "ground_truth" / f"{index:05d}.txt").write_bytes(data)
        for index, entry in sorted(raw.items()):
            data = read_member(archive, entry)
            with Image.open(io.BytesIO(data)) as source:
                if source.format != "JPEG":
                    raise ValueError("selected original frame is not a JPEG")
                source.load()
                image = source.convert("RGB")
            image_sizes[image.size] += 1
            file_hash = sha256(data)
            raw_hashes[file_hash].append(index)
            pixel_hashes[sha256(image.tobytes())].append(index)
            perceptual_hashes[index] = difference_hash(image)
            (output_dir / "raw_frames" / f"{index:05d}.jpg").write_bytes(data)
            if index in truth:
                gt_data = (output_dir / "ground_truth" / f"{index:05d}.txt").read_bytes()
                pairs.append({"frame_index": index, "image": f"raw_frames/{index:05d}.jpg",
                              "truth": f"ground_truth/{index:05d}.txt", "image_sha256": file_hash,
                              "truth_sha256": sha256(gt_data), "width": image.width, "height": image.height,
                              "image_source_member": entry.filename, "truth_source_member": truth[index].filename})
    if len(image_sizes) != 1:
        raise ValueError("selected recording has inconsistent image dimensions")
    if not pairs:
        raise ValueError("no original images pair with author truth by source frame index")
    all_bounds = box_bounds(boxes_by_frame, sorted(truth))
    paired_bounds = box_bounds(boxes_by_frame, common)
    runs = continuous_runs(common)
    near_pairs = []
    for position, first in enumerate(common):
        for second in common[position + 1:]:
            distance = (perceptual_hashes[first] ^ perceptual_hashes[second]).bit_count()
            if distance <= 2:
                near_pairs.append({"first": first, "second": second, "hamming_distance": distance})
    write_json(output_dir / "near-duplicate-screen.json", {
        "method": "64-bit grayscale difference hash, Hamming distance <=2, paired original frames only",
        "interpretation": "Similarity screening only; static arena background can dominate this hash.",
        "pairs": near_pairs,
    })
    qc = preview_frames(output_dir, pairs, boxes_by_frame)
    manifest = {"schema": "bpb-sam2mice-source-pairs/1", "source": source_receipt,
                "source_sequence": "openfield_five_mouse", "pairs": pairs}
    write_json(output_dir / "paired-frames.json", manifest)
    report = {
        "schema": "bpb-sam2mice-source-audit/1", "status": "source_decoded_protocol_pending",
        "source": source_receipt, "upstream_commit": UPSTREAM,
        "original_frame_directory": RAW_PREFIX, "author_truth_directory": GT_PREFIX,
        "selected_raw_frames": len(raw), "selected_gt_frames": len(truth), "paired_frames": len(pairs),
        "raw_frames_without_gt": sorted(set(raw) - set(truth)),
        "gt_frames_without_raw": sorted(set(truth) - set(raw)),
        "raw_dimensions": [{"width": width, "height": height, "frames": count}
                           for (width, height), count in sorted(image_sizes.items())],
        "gt_boxes_per_frame": dict(sorted(id_counts.items())),
        "explicit_empty_gt_frames": sorted(index for index, boxes in boxes_by_frame.items() if not boxes),
        "gt_identity_sets": [{"ids": list(ids), "frames": count} for ids, count in sorted(id_sets.items())],
        "gt_box_contract_passed": all_bounds["outside_objects"] == 0,
        "normalized_xyxy_bounds": {"all_gt": all_bounds, "paired_gt": paired_bounds},
        "identity_continuity": identity_continuity(boxes_by_frame, common),
        "continuous_paired_runs": runs,
        "twelve_block_previews": {
            "raw_and_gt_index_extent": equal_width_blocks(common, max(set(raw) | set(truth)) + 1),
            "paired_index_extent": equal_width_blocks(common, max(common) + 1),
            "interpretation": "Index-only coverage previews. No roles, gap policy or task split are selected here.",
        },
        "run_summary": {"count": len(runs), "max_frames": max(run["frames"] for run in runs),
                        "median_frames": float(np.median([run["frames"] for run in runs])),
                        "runs_at_least_10_frames": sum(run["frames"] >= 10 for run in runs),
                        "runs_at_least_20_frames": sum(run["frames"] >= 20 for run in runs)},
        "exact_file_duplicate_groups": [indices for indices in raw_hashes.values() if len(indices) > 1],
        "exact_pixel_duplicate_groups": [indices for indices in pixel_hashes.values() if len(indices) > 1],
        "exact_gt_file_duplicate_groups": [indices for indices in truth_hashes.values() if len(indices) > 1],
        "near_duplicate_screen_pairs": len(near_pairs), "near_duplicate_screen": "near-duplicate-screen.json",
        "visual_qc": qc,
        "source_roles": {"ground_truth_bb_labels": "author benchmark annotations",
                         "openfield_five_mouse": "author original image frames",
                         "openfield_five_mouse_seg": "excluded model outputs and possible overlays",
                         "YOLO_data": "excluded automatic-mask-derived training boxes"},
        "label_provenance": {
            "author_benchmark_readme": f"https://github.com/Neurallabware/Airscope_toolbox/blob/{UPSTREAM}/Software/SAM2Mice/SAM2_Mice/benchmark/README.md",
            "author_annotation_pipeline": f"https://github.com/Neurallabware/Airscope_toolbox/blob/{UPSTREAM}/Software/SAM2Mice/training/README.md",
            "verification_scope": "Author identifies these boxes as benchmark ground truth. The training README describes human correction and independent review of masks; per-file lineage to that pipeline is unverified.",
        },
        "independent_recordings": 1, "task_accepted": False,
        "split_defined": False, "model_run": False,
    }
    write_json(output_dir / "audit.json", report)
    files = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            files[path.relative_to(output_dir).as_posix()] = {"bytes": len(data), "sha256": sha256(data)}
    write_json(output_dir / "complete.json", {
        "schema": "bpb-sam2mice-tracking-prepared/1",
        "source": source_receipt,
        "source_verified": True,
        "fixture": False,
        "paired_manifest": "paired-frames.json",
        "paired_manifest_sha256": files["paired-frames.json"]["sha256"],
        "audit": "audit.json",
        "files": files,
        "task_accepted": False,
        "visual_review": "pending",
    })
    print(json.dumps({"status": report["status"], "paired_frames": len(pairs),
                      "run_summary": report["run_summary"], "output": str(output_dir)}, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.absolute()
    output = args.output.absolute()
    if archive.name != FILE_NAME or ".." in archive.parts or ".." in output.parts:
        raise ValueError("explicit source archive and dedicated output paths required")
    if output in (Path("/"), Path.home()) or any(path.is_symlink() for path in (archive, *archive.parents, output, *output.parents)):
        raise ValueError("linked or unsafe source/output path")
    repo = Path(__file__).resolve().parents[3]
    if output.is_relative_to(repo) and not output.is_relative_to(repo / ".cache"):
        raise ValueError("prepared data inside the checkout must stay under .cache")
    os.umask(0o077)
    prepare(archive, output)


if __name__ == "__main__":
    main()
