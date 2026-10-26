"""Prepare CalMS21 Task1 native JSON with strict Train/Valid/Test role separation.

Requires numpy and ijson>=3.4. The official archive is read in place; its mixed
contents are never extracted into an agent-visible directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import zipfile

import ijson
import numpy as np

from calms_metrics import CLASSIC_VOCAB


SOURCE_NAME = "task1_classic_classification.zip"
SOURCE_SIZE = 457_357_950
SOURCE_MD5 = "8a02654fddae28614ee24a6a082261b8"
SOURCE_SHA256 = "f1cd2f46771cc3834020d187604da53e5ff330121f5a816146f14192fb0bf427"
PREFIX = "task1_classic_classification/"
MEMBERS = {PREFIX + f"calms21_task1_{split}.json" for split in ("train", "test")}
MEMBERS |= {PREFIX + f"taskprog_features_task1_{split}.json" for split in ("train", "test")}
MAX_EXPANDED = 4_000_000_000
ARRAY_SPEC = {
    "keypoints": {"dtype": "float32", "shape": ["frames", 2, 2, 7]},
    "scores": {"dtype": "float32", "shape": ["frames", 2, 7]},
    "labels": {"dtype": "uint8", "shape": ["frames"]},
}


def _assert_no_symlink_ancestors(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise ValueError(f"symlink path component forbidden: {candidate}")


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _regular_file(path: Path) -> None:
    _assert_no_symlink_ancestors(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"regular file required: {path}")


def _private_directory(path: Path) -> None:
    _assert_no_symlink_ancestors(path)
    mode = path.lstat().st_mode
    if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) != 0o700:
        raise ValueError(f"private 0700 directory required: {path}")


def _private_file(path: Path) -> None:
    _regular_file(path)
    if stat.S_IMODE(path.lstat().st_mode) != 0o600:
        raise ValueError(f"private 0600 file required: {path}")


def _read_json(path: Path) -> dict[str, object]:
    _private_file(path)
    if path.stat().st_size > 5_000_000:
        raise ValueError("manifest exceeds size bound")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def source_hashes(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def validate_zip(zf: zipfile.ZipFile) -> None:
    seen, expanded = set(), 0
    for info in zf.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise ValueError("unsafe ZIP member path")
        if info.filename in seen:
            raise ValueError("duplicate ZIP member")
        seen.add(info.filename)
        mode = (info.external_attr >> 16) & 0o170000
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
            raise ValueError("ZIP links, special files, and encrypted entries are forbidden")
        if info.filename == PREFIX and info.is_dir():
            continue
        if info.filename not in MEMBERS or info.is_dir():
            raise ValueError("unexpected ZIP member")
        if info.file_size > 1_500_000_000 or info.compress_size == 0:
            raise ValueError("ZIP member exceeds resource bound")
        if info.file_size / info.compress_size > 100:
            raise ValueError("ZIP expansion ratio exceeds bound")
        expanded += info.file_size
    if set(seen) != MEMBERS | {PREFIX} or expanded > MAX_EXPANDED:
        raise ValueError("ZIP member set or total expansion mismatch")


def _safe_sequence_id(value: object, split: str) -> str:
    if not isinstance(value, str) or not value.startswith(f"task1/{split}/"):
        raise ValueError("unexpected sequence ID or source split")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 3 or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("unsafe sequence ID")
    return value


def _arrays(sequence: object) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not isinstance(sequence, dict) or set(sequence) != {"annotations", "keypoints", "scores", "metadata"}:
        raise ValueError("source sequence schema mismatch")
    metadata = sequence["metadata"]
    if not isinstance(metadata, dict) or metadata.get("annotator-id") != 0 or metadata.get("vocab") != CLASSIC_VOCAB:
        raise ValueError("source annotator or vocabulary mismatch")
    labels = np.asarray(sequence["annotations"])
    if labels.ndim != 1 or labels.size == 0 or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("annotations must be nonempty integer frames")
    if np.any((labels < 0) | (labels > 3)):
        raise ValueError("annotation vocabulary mismatch")
    n = labels.size
    keypoints = np.asarray(sequence["keypoints"], dtype=np.float32)
    scores = np.asarray(sequence["scores"], dtype=np.float32)
    if keypoints.shape != (n, 2, 2, 7) or scores.shape != (n, 2, 7):
        raise ValueError("pose, confidence, and annotation frame counts or shapes mismatch")
    if not np.isfinite(keypoints).all() or not np.isfinite(scores).all():
        raise ValueError("nonfinite pose or confidence")
    if np.any((scores < 0) | (scores > 1)):
        raise ValueError("confidence outside [0, 1]")
    return keypoints, scores, labels.astype(np.uint8)


def _write_json(path: Path, data: object) -> None:
    _assert_no_symlink_ancestors(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _reject_duplicate_source_keys(zf: zipfile.ZipFile, member: str) -> None:
    """Check every JSON map key, including nested metadata/vocab keys."""
    map_keys: list[set[str]] = []
    with zf.open(member) as stream:
        for _, event, value in ijson.parse(stream):
            if event == "start_map":
                map_keys.append(set())
            elif event == "map_key":
                if not map_keys or value in map_keys[-1]:
                    raise ValueError("duplicate or invalid source JSON key")
                map_keys[-1].add(value)
            elif event == "end_map":
                map_keys.pop()
    if map_keys:
        raise ValueError("unterminated source JSON object")


def _load_split(zf: zipfile.ZipFile, split: str, destination: Path) -> list[dict[str, object]]:
    member = PREFIX + f"calms21_task1_{split}.json"
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with zf.open(member) as stream:
        for sequence_id, sequence in ijson.kvitems(stream, "annotator-id_0"):
            sequence_id = _safe_sequence_id(sequence_id, split)
            if sequence_id in seen:
                raise ValueError("duplicate sequence ID")
            seen.add(sequence_id)
            keypoints, scores, labels = _arrays(sequence)
            filename = hashlib.sha256(sequence_id.encode("utf-8")).hexdigest() + ".npz"
            path = destination / filename
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                np.savez(output, keypoints=keypoints, scores=scores, labels=labels)
            byte_count, digest = _file_digest(path)
            rows.append({"id": sequence_id, "file": filename, "frames": int(labels.size),
                         "bytes": byte_count, "sha256": digest})
    if not rows:
        raise ValueError("source split is empty")
    return sorted(rows, key=lambda row: row["id"])


def _exact_children(directory: Path, expected: set[str]) -> None:
    _private_directory(directory)
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError(f"prepared file set mismatch: {directory}")


def _verify_rows(base: Path, rows: object, split: str) -> tuple[set[str], int]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty or invalid prepared split")
    expected_files, ids, frames = set(), set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "file", "frames", "bytes", "sha256"}:
            raise ValueError("prepared row schema mismatch")
        sequence_id = _safe_sequence_id(row["id"], split)
        if sequence_id in ids:
            raise ValueError("duplicate prepared sequence ID")
        ids.add(sequence_id)
        filename = hashlib.sha256(sequence_id.encode("utf-8")).hexdigest() + ".npz"
        if row["file"] != filename or filename in expected_files:
            raise ValueError("prepared filename binding mismatch")
        expected_files.add(filename)
        count, size, digest = row["frames"], row["bytes"], row["sha256"]
        if (type(count) is not int or count <= 0 or type(size) is not int or size <= 0
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("invalid prepared frame count or file digest")
        path = base / filename
        _private_file(path)
        actual_size, actual_digest = _file_digest(path)
        if (actual_size, actual_digest) != (size, digest):
            raise ValueError("prepared NPZ bytes or SHA-256 mismatch")
        with np.load(path, allow_pickle=False) as arrays:
            if set(arrays.files) != set(ARRAY_SPEC):
                raise ValueError("prepared NPZ array set mismatch")
            for name, spec in ARRAY_SPEC.items():
                array = arrays[name]
                shape = (count, *spec["shape"][1:])
                if array.shape != shape or str(array.dtype) != spec["dtype"]:
                    raise ValueError("prepared NPZ shape or dtype mismatch")
            labels = arrays["labels"]
            scores = arrays["scores"]
            if np.any(labels > 3) or not np.isfinite(arrays["keypoints"]).all():
                raise ValueError("prepared label or pose vocabulary mismatch")
            if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
                raise ValueError("prepared confidence bounds mismatch")
        frames += count
    _exact_children(base, expected_files)
    return ids, frames


def verify_prepared(root: Path, *, require_complete: bool = True, include_owner: bool = False) -> dict[str, object]:
    """Verify exact public files; owner arrays are read only with include_owner=True.

    The public-only mode is safe for a reference process and never opens Test
    arrays or labels. It still checks the root completion marker and public
    manifest digest. A missing completion marker is accepted only by prepare()
    immediately before its final write.
    """
    _assert_no_symlink_ancestors(root)
    root_files = {"public", "owner", "preparation-evidence.json"}
    if require_complete:
        root_files.add("complete.json")
    _exact_children(root, root_files)
    _private_file(root / "preparation-evidence.json")
    public = root / "public"
    _exact_children(public, {"manifest.json", "train", "valid"})
    public_manifest = _read_json(public / "manifest.json")
    if (public_manifest.get("schema") != "bpb-calms21-public/1"
            or public_manifest.get("task") != "task1"
            or public_manifest.get("source_sha256") != SOURCE_SHA256
            or public_manifest.get("vocab") != CLASSIC_VOCAB
            or public_manifest.get("arrays") != ARRAY_SPEC
            or set(public_manifest.get("splits", {})) != {"train", "valid"}):
        raise ValueError("public manifest binding mismatch")
    split_ids, split_frames = {}, {}
    for role in ("train", "valid"):
        split_ids[role], split_frames[role] = _verify_rows(public / role, public_manifest["splits"][role], "train")
        if public_manifest.get("counts", {}).get(role) != {"sequences": len(split_ids[role]), "frames": split_frames[role]}:
            raise ValueError("public manifest count mismatch")
    if split_ids["train"] & split_ids["valid"]:
        raise ValueError("prepared Train/Valid overlap")
    rank = sorted(split_ids["train"] | split_ids["valid"],
                  key=lambda value: hashlib.sha256(("bpb-calms21-valid-v1:" + value).encode()).hexdigest())
    if split_ids["valid"] != set(rank[:math.ceil(0.2 * len(rank))]):
        raise ValueError("prepared Valid membership differs from frozen policy")
    if require_complete:
        completion = _read_json(root / "complete.json")
        if (completion.get("schema") != "bpb-calms21-complete/1"
                or completion.get("source_sha256") != SOURCE_SHA256
                or completion.get("public_manifest_sha256") != _file_digest(public / "manifest.json")[1]):
            raise ValueError("public completion binding mismatch")
    else:
        completion = None
    result = {"train_sequences": len(split_ids["train"]), "train_frames": split_frames["train"],
              "valid_sequences": len(split_ids["valid"]), "valid_frames": split_frames["valid"]}
    if include_owner:
        owner = root / "owner"
        _exact_children(owner, {"test", "test-manifest.json"})
        owner_manifest = _read_json(owner / "test-manifest.json")
        if (owner_manifest.get("schema") != "bpb-calms21-owner-test/1"
                or owner_manifest.get("task") != "task1"
                or owner_manifest.get("source_sha256") != SOURCE_SHA256
                or owner_manifest.get("vocab") != CLASSIC_VOCAB
                or owner_manifest.get("arrays") != ARRAY_SPEC):
            raise ValueError("owner manifest binding mismatch")
        test_ids, test_frames = _verify_rows(owner / "test", owner_manifest.get("sequences"), "test")
        if owner_manifest.get("counts") != {"sequences": len(test_ids), "frames": test_frames}:
            raise ValueError("owner manifest count mismatch")
        if test_ids & (split_ids["train"] | split_ids["valid"]):
            raise ValueError("official Train/Test sequence ID overlap")
        if {PurePosixPath(value).name for value in test_ids} & {PurePosixPath(value).name for value in (split_ids["train"] | split_ids["valid"])}:
            raise ValueError("official Train/Test canonical recording ID overlap")
        if require_complete and completion.get("owner_manifest_sha256") != _file_digest(owner / "test-manifest.json")[1]:
            raise ValueError("owner completion binding mismatch")
        result.update({"owner_test_sequences": len(test_ids), "owner_test_frames": test_frames})
    return result


def prepare(zip_path: Path, output: Path) -> dict[str, object]:
    _assert_no_symlink_ancestors(zip_path)
    _assert_no_symlink_ancestors(output)
    if not zip_path.is_file() or zip_path.is_symlink() or zip_path.stat().st_size != SOURCE_SIZE:
        raise ValueError("official ZIP missing or byte size mismatch")
    md5, sha256 = source_hashes(zip_path)
    if md5 != SOURCE_MD5 or sha256 != SOURCE_SHA256:
        raise ValueError("official ZIP checksum mismatch")
    if output.exists():
        raise FileExistsError("output must be a fresh path; existing data will not be overwritten")
    output.mkdir(mode=0o700, parents=True)
    for name in ("public", "public/train", "public/valid", "owner", "owner/test", "owner/train-stage"):
        (output / name).mkdir(mode=0o700)
    with zipfile.ZipFile(zip_path) as zf:
        validate_zip(zf)
        for split in ("train", "test"):
            _reject_duplicate_source_keys(zf, PREFIX + f"calms21_task1_{split}.json")
        train_rows = _load_split(zf, "train", output / "owner/train-stage")
        test_rows = _load_split(zf, "test", output / "owner/test")
    train_ids = {row["id"] for row in train_rows}
    test_ids = {row["id"] for row in test_rows}
    if train_ids & test_ids:
        raise ValueError("official Train and Test sequence IDs overlap")
    if {PurePosixPath(value).name for value in train_ids} & {PurePosixPath(value).name for value in test_ids}:
        raise ValueError("official Train and Test canonical recording IDs overlap")
    rank = sorted(train_rows, key=lambda row: hashlib.sha256(("bpb-calms21-valid-v1:" + row["id"]).encode()).hexdigest())
    valid_ids = {row["id"] for row in rank[:math.ceil(0.2 * len(rank))]}
    if not valid_ids or valid_ids == train_ids:
        raise ValueError("cannot form nonempty disjoint Train/Valid")
    public_rows: dict[str, list[dict[str, object]]] = {"train": [], "valid": []}
    for row in train_rows:
        role = "valid" if row["id"] in valid_ids else "train"
        shutil.move(output / "owner/train-stage" / row["file"], output / "public" / role / row["file"])
        public_rows[role].append(row)
    (output / "owner/train-stage").rmdir()
    if {row["id"] for row in public_rows["train"]} & valid_ids:
        raise AssertionError("Train/Valid overlap")
    public = {"schema": "bpb-calms21-public/1", "task": "task1", "source_sha256": sha256,
              "arrays": ARRAY_SPEC,
              "vocab": CLASSIC_VOCAB, "split_policy": "BPB SHA-256 rank of whole official-Train sequence IDs; first ceil(20%) Valid; not asserted animal-disjoint",
              "splits": public_rows,
              "counts": {role: {"sequences": len(rows), "frames": sum(row["frames"] for row in rows)} for role, rows in public_rows.items()}}
    owner = {"schema": "bpb-calms21-owner-test/1", "task": "task1", "source_sha256": sha256,
             "arrays": ARRAY_SPEC,
             "vocab": CLASSIC_VOCAB, "split": "official Test", "sequences": test_rows,
             "counts": {"sequences": len(test_rows), "frames": sum(row["frames"] for row in test_rows)}}
    _write_json(output / "public/manifest.json", public)
    _write_json(output / "owner/test-manifest.json", owner)
    evidence = {"schema": "bpb-calms21-preparation-evidence/1", "source_url": "https://data.caltech.edu/records/s0vdx-0k302",
                "source_filename": SOURCE_NAME, "source_bytes": SOURCE_SIZE, "source_md5": md5,
                "source_sha256": sha256, "public_counts": public["counts"], "owner_test_counts": owner["counts"],
                "public_manifest": "public/manifest.json", "owner_test_manifest": "owner/test-manifest.json",
                "test_scored": False, "agent_run_started": False}
    _write_json(output / "preparation-evidence.json", evidence)
    verify_prepared(output, require_complete=False, include_owner=True)
    _write_json(output / "complete.json", {
        "schema": "bpb-calms21-complete/1", "source_sha256": sha256,
        "public_manifest_sha256": _file_digest(output / "public/manifest.json")[1],
        "owner_manifest_sha256": _file_digest(output / "owner/test-manifest.json")[1],
    })
    verify_prepared(output, include_owner=True)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=["task1"])
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-prepared", type=Path,
                        help="verify all public and owner NPZ files without scoring Test")
    args = parser.parse_args()
    if args.verify_prepared is not None:
        if any(value is not None for value in (args.task, args.zip, args.output)):
            parser.error("--verify-prepared cannot be combined with preparation arguments")
        result = verify_prepared(args.verify_prepared, include_owner=True)
    else:
        if args.task != "task1" or args.zip is None or args.output is None:
            parser.error("preparation requires --task task1, --zip, and --output")
        result = prepare(args.zip, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
