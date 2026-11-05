"""Prepare and verify CalMS21 Task 2/3 from the official native ZIPs.

The source ZIP is read in place. Only numeric, source-bound sequence arrays are
written; official Test labels remain under owner/. Requires numpy and ijson.
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
import zipfile

import ijson
import numpy as np

from calms_metrics import CLASSIC_VOCAB, NEW_BEHAVIORS
from calms_prepare import ARRAY_SPEC, _assert_no_symlink_ancestors, _file_digest, _private_directory, _private_file, _read_json, _write_json, source_hashes


SOURCE = {
    "task2": {"name": "task2_annotation_styles.zip", "bytes": 912_092_847,
              "md5": "c97e87e13e77ffb80c073e05c05a4683"},
    "task3": {"name": "task3_new_behaviors.zip", "bytes": 556_170_163,
              "md5": "df59df02d069bab1cfc376cdc1a3925b"},
}
GROUPS = {"task2": tuple(f"annotator-id_{i}" for i in range(1, 6)),
          "task3": NEW_BEHAVIORS}
SPLIT_SALT = "bpb-calms21-family-recording-valid-v1:"
SOURCE_URL = "https://data.caltech.edu/records/s0vdx-0k302"


def vocab_by_group(task: str) -> dict[str, dict[str, int]]:
    if task == "task2":
        return {group: dict(CLASSIC_VOCAB) for group in GROUPS[task]}
    if task == "task3":
        return {group: {"other": 0, group: 1} for group in GROUPS[task]}
    raise ValueError("unsupported task")


def _source_members(task: str) -> set[str]:
    prefix = f"{task}_{'annotation_styles' if task == 'task2' else 'new_behaviors'}/"
    return {prefix + f"{stem}_{task}_{split}.json"
            for stem in ("calms21", "taskprog_features") for split in ("train", "test")}


def _validate_zip(zf: zipfile.ZipFile, task: str) -> None:
    members = _source_members(task)
    prefix = next(iter(members)).split("/")[0] + "/"
    seen: set[str] = set()
    expanded = 0
    for info in zf.infolist():
        name = info.filename
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or name in seen:
            raise ValueError("unsafe or duplicate ZIP member")
        seen.add(name)
        mode = (info.external_attr >> 16) & 0o170000
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
            raise ValueError("ZIP link, special file, or encrypted member")
        if name == prefix and info.is_dir():
            continue
        if name not in members or info.is_dir() or info.file_size > 4_000_000_000 or not info.compress_size:
            raise ValueError("unexpected or oversized ZIP member")
        if info.file_size / info.compress_size > 100:
            raise ValueError("ZIP expansion ratio exceeds bound")
        expanded += info.file_size
    if seen != members | {prefix} or expanded > 12_000_000_000:
        raise ValueError("ZIP member set or total expansion mismatch")


def _reject_duplicate_source_keys(zf: zipfile.ZipFile, member: str,
                                  expected_groups: set[str] | None = None) -> None:
    stack: list[set[str]] = []
    root_keys: set[str] = set()
    with zf.open(member) as stream:
        for prefix, event, value in ijson.parse(stream):
            if event == "start_map":
                stack.append(set())
            elif event == "map_key":
                if not stack or value in stack[-1]:
                    raise ValueError("duplicate source JSON key")
                stack[-1].add(value)
                if prefix == "":
                    root_keys.add(value)
            elif event == "end_map":
                stack.pop()
    if stack or (expected_groups is not None and root_keys != expected_groups):
        raise ValueError("source JSON root group set or map structure mismatch")


def _safe_id(value: object, task: str, group: str, split: str) -> str:
    if not isinstance(value, str):
        raise ValueError("sequence ID must be a string")
    path = PurePosixPath(value)
    component = f"annotator{group.rsplit('_', 1)[1]}" if task == "task2" else group
    if (path.is_absolute() or len(path.parts) != 4 or path.parts[:3] != (task, component, split)
            or any(part in ("", ".", "..") for part in path.parts)):
        raise ValueError(f"unexpected sequence ID or source split: {value}")
    return value


def _recording_id(task: str, sequence_id: str) -> str:
    """Source-local counter token; never use alone as a cross-group identity."""
    basename = PurePosixPath(sequence_id).name
    marker = "_task2_annotator" if task == "task2" else "_task3_"
    if marker not in basename:
        raise ValueError("unrecognized canonical recording ID")
    recording, suffix = basename.split(marker, 1)
    component = PurePosixPath(sequence_id).parts[1]
    expected_suffix = component.removeprefix("annotator") if task == "task2" else component
    if not recording or suffix != expected_suffix or "/" in recording:
        raise ValueError("invalid canonical recording ID")
    return PurePosixPath(sequence_id).parts[1] + "/" + recording


def _pose_identity(keypoints: np.ndarray, scores: np.ndarray) -> str:
    """Detect exact repeat recordings, including copies with different labels."""
    digest = hashlib.sha256()
    digest.update(b"bpb-calms21-pose-recording-v1\0")
    digest.update(int(keypoints.shape[0]).to_bytes(8, "big"))
    digest.update(keypoints.tobytes())
    digest.update(scores.tobytes())
    return digest.hexdigest()


def _valid_recordings(by_group: dict[str, set[str]]) -> set[str]:
    selected: set[str] = set()
    protected = set().union(*(ids for ids in by_group.values() if len(ids) <= 1))
    def rank_key(value: str) -> str:
        return hashlib.sha256((SPLIT_SALT + value).encode()).hexdigest()
    for group in sorted(by_group):
        identities = by_group[group]
        eligible = identities - protected
        if len(identities) <= 1 or not eligible:
            continue
        rank = sorted(eligible, key=rank_key)
        take = min(math.ceil(0.2 * len(identities)), len(rank), len(identities) - 1)
        selected.update(rank[:take])
    for group in sorted(by_group):
        identities = by_group[group]
        if identities and identities <= selected:
            selected.remove(max(identities, key=rank_key))
    return selected


def _arrays(sequence: object, task: str, group: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not isinstance(sequence, dict) or set(sequence) != {"annotations", "keypoints", "scores", "metadata"}:
        raise ValueError("source sequence schema mismatch")
    metadata = sequence["metadata"]
    if not isinstance(metadata, dict) or metadata.get("vocab") != vocab_by_group(task)[group]:
        raise ValueError("source vocabulary mismatch")
    if task == "task2" and metadata.get("annotator-id") != int(group.rsplit("_", 1)[1]):
        raise ValueError("source annotator ID mismatch")
    labels = np.asarray(sequence["annotations"])
    if labels.ndim != 1 or labels.size == 0 or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("annotations must be nonempty integer frames")
    n = labels.size
    if np.any((labels < 0) | (labels >= (4 if task == "task2" else 2))):
        raise ValueError("annotation vocabulary mismatch")
    keypoints = np.asarray(sequence["keypoints"], dtype=np.float32)
    scores = np.asarray(sequence["scores"], dtype=np.float32)
    if keypoints.shape != (n, 2, 2, 7) or scores.shape != (n, 2, 7):
        raise ValueError("pose, confidence, and annotation frame count mismatch")
    if not np.isfinite(keypoints).all() or not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
        raise ValueError("nonfinite pose or out-of-range confidence")
    return keypoints, scores, labels.astype(np.uint8)


def _load_split(zf: zipfile.ZipFile, task: str, split: str, destination: Path) -> tuple[list[dict[str, object]], dict[str, str]]:
    member = next(name for name in _source_members(task) if name.endswith(f"/calms21_{task}_{split}.json"))
    rows: list[dict[str, object]] = []
    recording_by_file: dict[str, str] = {}
    for group in GROUPS[task]:
        count = 0
        with zf.open(member) as stream:
            for sequence_id, sequence in ijson.kvitems(stream, group):
                sequence_id = _safe_id(sequence_id, task, group, split)
                keypoints, scores, labels = _arrays(sequence, task, group)
                filename = hashlib.sha256((group + "\0" + sequence_id).encode()).hexdigest() + ".npz"
                recording_by_file[filename] = _pose_identity(keypoints, scores)
                path = destination / filename
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                    np.savez(output, keypoints=keypoints, scores=scores, labels=labels)
                size, digest = _file_digest(path)
                rows.append({"group": group, "id": sequence_id, "file": filename,
                             "frames": int(labels.size), "bytes": size, "sha256": digest})
                count += 1
        if not count:
            raise ValueError(f"empty source group: {group}/{split}")
    return sorted(rows, key=lambda row: (row["group"], row["id"])), recording_by_file


def _exact_children(path: Path, expected: set[str]) -> None:
    _private_directory(path)
    if {child.name for child in path.iterdir()} != expected:
        raise ValueError(f"prepared file set mismatch: {path}")


def _strict_file(path: Path) -> None:
    _private_file(path)
    if path.stat().st_nlink != 1:
        raise ValueError(f"hardlinked file forbidden: {path}")


def _verify_rows(base: Path, rows: object, task: str, split: str, *,
                 require_all_groups: bool = True) -> tuple[set[tuple[str, str]], set[str], dict[str, set[str]], int]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty or invalid prepared split")
    expected_files: set[str] = set()
    seen: set[tuple[str, str]] = set()
    recordings: set[str] = set()
    by_group: dict[str, set[str]] = {group: set() for group in GROUPS[task]}
    total_frames = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"group", "id", "file", "frames", "bytes", "sha256"}:
            raise ValueError("prepared row schema mismatch")
        group = row["group"]
        if group not in GROUPS[task]:
            raise ValueError("prepared group mismatch")
        sequence_id = _safe_id(row["id"], task, group, split)
        key = group, sequence_id
        if key in seen:
            raise ValueError("duplicate prepared sequence")
        seen.add(key)
        _recording_id(task, sequence_id)
        filename = hashlib.sha256((group + "\0" + sequence_id).encode()).hexdigest() + ".npz"
        if row["file"] != filename or filename in expected_files:
            raise ValueError("prepared filename binding mismatch")
        expected_files.add(filename)
        frames, size, digest = row["frames"], row["bytes"], row["sha256"]
        if (type(frames) is not int or frames <= 0 or type(size) is not int or size <= 0
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("invalid prepared count or digest")
        path = base / filename
        _strict_file(path)
        if _file_digest(path) != (size, digest):
            raise ValueError("prepared NPZ hardlink, bytes, or digest mismatch")
        with np.load(path, allow_pickle=False) as arrays:
            if set(arrays.files) != set(ARRAY_SPEC):
                raise ValueError("prepared NPZ array set mismatch")
            for name, spec in ARRAY_SPEC.items():
                if arrays[name].shape != (frames, *spec["shape"][1:]) or str(arrays[name].dtype) != spec["dtype"]:
                    raise ValueError("prepared NPZ shape or dtype mismatch")
            labels, keypoints, scores = arrays["labels"], arrays["keypoints"], arrays["scores"]
            if (np.any(labels >= (4 if task == "task2" else 2))
                    or not np.isfinite(keypoints).all()
                    or not np.isfinite(scores).all()
                    or np.any((scores < 0) | (scores > 1))):
                raise ValueError("prepared NPZ values mismatch")
            recording = _pose_identity(keypoints, scores)
            recordings.add(recording)
            by_group[group].add(recording)
        total_frames += frames
    _exact_children(base, expected_files)
    if require_all_groups and {group for group, _ in seen} != set(GROUPS[task]):
        raise ValueError("missing prepared group")
    return seen, recordings, by_group, total_frames


def _counts(rows: list[dict[str, object]]) -> dict[str, int]:
    return {"sequences": len(rows), "frames": sum(int(row["frames"]) for row in rows)}


def verify_prepared(root: Path, *, require_complete: bool = True, include_owner: bool = False) -> dict[str, object]:
    """Verify public bytes only by default; inspect owner Test only when explicit."""
    _assert_no_symlink_ancestors(root)
    _exact_children(root, {"public", "owner", "preparation-evidence.json"} | ({"complete.json"} if require_complete else set()))
    _strict_file(root / "preparation-evidence.json")
    _exact_children(root / "public", {"manifest.json", "train", "valid"})
    _strict_file(root / "public/manifest.json")
    public = _read_json(root / "public/manifest.json")
    task = public.get("task")
    evidence = _read_json(root / "preparation-evidence.json")
    if (task not in SOURCE or public.get("schema") != "bpb-calms21-family-public/1"
            or public.get("arrays") != ARRAY_SPEC or public.get("vocab_by_group") != vocab_by_group(task)
            or set(public.get("splits", {})) != {"train", "valid"}
            or public.get("source_md5") != SOURCE[task]["md5"]
            or evidence.get("schema") != "bpb-calms21-family-preparation-evidence/1"
            or evidence.get("task") != task or evidence.get("source_bytes") != SOURCE[task]["bytes"]
            or evidence.get("source_md5") != SOURCE[task]["md5"]
            or evidence.get("source_sha256") != public.get("source_sha256")
            or not isinstance(public.get("source_sha256"), str)
            or len(public["source_sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in public["source_sha256"])):
        raise ValueError("public manifest binding mismatch")
    groups = set(GROUPS[task])
    split_data = {}
    for role in ("train", "valid"):
        rows = public["splits"][role]
        seen, recordings, by_group, frames = _verify_rows(root / "public" / role, rows, task, "train",
                                                           require_all_groups=role == "train")
        if public.get("counts", {}).get(role) != {"sequences": len(seen), "frames": frames}:
            raise ValueError("public count mismatch")
        split_data[role] = (seen, recordings, by_group, frames)
    if evidence.get("public_counts") != public.get("counts"):
        raise ValueError("public evidence count mismatch")
    if split_data["train"][0] & split_data["valid"][0] or split_data["train"][1] & split_data["valid"][1]:
        raise ValueError("Train/Valid sequence or recording leakage")
    all_recordings = split_data["train"][1] | split_data["valid"][1]
    all_by_group = {group: split_data["train"][2][group] | split_data["valid"][2][group]
                    for group in GROUPS[task]}
    if split_data["valid"][1] != _valid_recordings(all_by_group):
        raise ValueError("Valid membership differs from frozen recording policy")
    unavailable = [group for group in GROUPS[task] if not split_data["valid"][2][group]]
    if public.get("validation_unavailable_groups", []) != unavailable:
        raise ValueError("validation availability mismatch")
    if require_complete:
        _strict_file(root / "complete.json")
        complete = _read_json(root / "complete.json")
        if (complete.get("schema") != "bpb-calms21-family-complete/1"
                or complete.get("task") != task or complete.get("source_sha256") != public.get("source_sha256")
                or complete.get("public_manifest_sha256") != _file_digest(root / "public/manifest.json")[1]):
            raise ValueError("public completion binding mismatch")
    else:
        complete = None
    result = {role: {"sequences": len(split_data[role][0]), "frames": split_data[role][3]}
              for role in ("train", "valid")}
    if include_owner:
        _exact_children(root / "owner", {"test", "test-manifest.json"})
        _strict_file(root / "owner/test-manifest.json")
        owner = _read_json(root / "owner/test-manifest.json")
        if (owner.get("schema") != "bpb-calms21-family-owner-test/1"
                or owner.get("task") != task or owner.get("source_sha256") != public.get("source_sha256")
                or owner.get("source_md5") != SOURCE[task]["md5"]
                or owner.get("arrays") != ARRAY_SPEC or owner.get("vocab_by_group") != vocab_by_group(task)):
            raise ValueError("owner manifest binding mismatch")
        seen, recordings, test_by_group, frames = _verify_rows(root / "owner/test", owner.get("sequences"), task, "test")
        if owner.get("counts") != {"sequences": len(seen), "frames": frames}:
            raise ValueError("owner count mismatch")
        overlap = sorted(recordings & all_recordings)
        if any(test_by_group[group] & all_by_group[group] for group in GROUPS[task]):
            raise ValueError("same target group official Train/Test pose overlap")
        if (owner.get("official_cross_role_pose_overlap_sha256") != overlap
                or evidence.get("official_cross_role_pose_overlap_count") != len(overlap)
                or evidence.get("owner_test_counts") != owner.get("counts")):
            raise ValueError("official cross-role pose overlap evidence mismatch")
        if require_complete and complete.get("owner_manifest_sha256") != _file_digest(root / "owner/test-manifest.json")[1]:
            raise ValueError("owner completion binding mismatch")
        result["owner_test"] = {"sequences": len(seen), "frames": frames}
    return result


def prepare(task: str, zip_path: Path, output: Path) -> dict[str, object]:
    if task not in SOURCE:
        raise ValueError("unsupported task")
    _assert_no_symlink_ancestors(zip_path)
    _assert_no_symlink_ancestors(output)
    _private_file(zip_path)
    if zip_path.stat().st_nlink != 1 or zip_path.stat().st_size != SOURCE[task]["bytes"]:
        raise ValueError("official ZIP hardlink or byte size mismatch")
    md5, sha256 = source_hashes(zip_path)
    if md5 != SOURCE[task]["md5"]:
        raise ValueError("official ZIP MD5 mismatch")
    if output.exists():
        raise FileExistsError("output must be a fresh path")
    output.mkdir(mode=0o700, parents=True)
    for name in ("public", "public/train", "public/valid", "owner", "owner/test", "owner/train-stage"):
        (output / name).mkdir(mode=0o700)
    with zipfile.ZipFile(zip_path) as zf:
        _validate_zip(zf, task)
        for member in sorted(_source_members(task)):
            _reject_duplicate_source_keys(zf, member, set(GROUPS[task]))
        train_rows, train_identity = _load_split(zf, task, "train", output / "owner/train-stage")
        test_rows, test_identity = _load_split(zf, task, "test", output / "owner/test")
    train_recordings = set(train_identity.values())
    test_recordings = set(test_identity.values())
    test_by_group = {group: {test_identity[row["file"]] for row in test_rows if row["group"] == group}
                     for group in GROUPS[task]}
    train_by_group = {group: {train_identity[row["file"]] for row in train_rows if row["group"] == group}
                      for group in GROUPS[task]}
    if any(train_by_group[group] & test_by_group[group] for group in GROUPS[task]):
        raise ValueError("same target group official Train/Test pose overlap")
    official_cross_role_overlap = sorted(train_recordings & test_recordings)
    valid_recordings = _valid_recordings(train_by_group)
    if not valid_recordings or valid_recordings == train_recordings:
        raise ValueError("cannot form disjoint Train/Valid")
    public_rows: dict[str, list[dict[str, object]]] = {"train": [], "valid": []}
    for row in train_rows:
        role = "valid" if train_identity[row["file"]] in valid_recordings else "train"
        shutil.move(output / "owner/train-stage" / row["file"], output / "public" / role / row["file"])
        public_rows[role].append(row)
    (output / "owner/train-stage").rmdir()
    if {row["group"] for row in public_rows["train"]} != set(GROUPS[task]) or not public_rows["valid"]:
        raise ValueError("recording split leaves no Train group or no Valid data")
    unavailable = [group for group in GROUPS[task]
                   if group not in {row["group"] for row in public_rows["valid"]}]
    public = {"schema": "bpb-calms21-family-public/1", "task": task, "source_sha256": sha256,
              "source_md5": md5, "arrays": ARRAY_SPEC, "vocab_by_group": vocab_by_group(task),
              "split_policy": "Within each group, SHA-256 rank of delivered float32 keypoints+scores fingerprints selects up to ceil(20%) of official Train recordings, reserving one Train recording per target; singleton targets have no disjoint Valid; union across groups prevents exact-pose Train/Valid crossing; not asserted animal-disjoint or near-duplicate-disjoint",
              "validation_unavailable_groups": unavailable,
              "splits": public_rows, "counts": {role: _counts(rows) for role, rows in public_rows.items()}}
    owner = {"schema": "bpb-calms21-family-owner-test/1", "task": task, "source_sha256": sha256,
             "source_md5": md5, "arrays": ARRAY_SPEC, "vocab_by_group": vocab_by_group(task),
             "split": "official Test; same target group pose-disjoint from official Train; cross-group pose reuse retained",
             "sequences": test_rows, "counts": _counts(test_rows),
             "official_cross_role_pose_overlap_sha256": official_cross_role_overlap}
    _write_json(output / "public/manifest.json", public)
    _write_json(output / "owner/test-manifest.json", owner)
    evidence = {"schema": "bpb-calms21-family-preparation-evidence/1", "task": task,
                "source_url": SOURCE_URL, "source_filename": SOURCE[task]["name"],
                "source_bytes": SOURCE[task]["bytes"], "source_md5": md5, "source_sha256": sha256,
                "public_counts": public["counts"], "owner_test_counts": owner["counts"],
                "validation_unavailable_groups": unavailable,
                "official_cross_role_pose_overlap_count": len(official_cross_role_overlap),
                "public_manifest": "public/manifest.json", "owner_test_manifest": "owner/test-manifest.json",
                "test_scored": False, "agent_run_started": False}
    _write_json(output / "preparation-evidence.json", evidence)
    verify_prepared(output, require_complete=False, include_owner=True)
    _write_json(output / "complete.json", {"schema": "bpb-calms21-family-complete/1", "task": task,
                "source_sha256": sha256,
                "public_manifest_sha256": _file_digest(output / "public/manifest.json")[1],
                "owner_manifest_sha256": _file_digest(output / "owner/test-manifest.json")[1]})
    verify_prepared(output, include_owner=True)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=SOURCE)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-prepared", type=Path)
    parser.add_argument("--include-owner", action="store_true")
    args = parser.parse_args()
    if args.verify_prepared is not None:
        if any(value is not None for value in (args.task, args.zip, args.output)):
            parser.error("verification cannot be combined with preparation")
        result = verify_prepared(args.verify_prepared, include_owner=args.include_owner)
    else:
        if args.task is None or args.zip is None or args.output is None or args.include_owner:
            parser.error("preparation requires --task, --zip, and --output")
        result = prepare(args.task, args.zip, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
