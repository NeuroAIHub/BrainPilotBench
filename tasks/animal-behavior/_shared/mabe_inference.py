"""Trusted MABe22 inference with Docker-only candidate execution.

Supervised mode scores complete 1,800-frame clips with four independent
probabilities. Representation mode exports finite embeddings in batches of at
most 16 clips; the optional six-task Ridge probe runs afterward on the trusted
host. No label, eligibility mask, or owner directory is mounted in Docker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

import numpy as np

from mabe_metrics import SEGMENTATION_CLASSES, score_supervised_segmentation
from mabe_pose_valid import pose_valid_frames


MODEL_FILES = ("model.py", "config.json", "weights.npz")
MODEL_SCHEMA = "bpb-mabe-frozen/1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SUP_ID_RE = re.compile(r"^[A-Z0-9]{20}$")
PROBE_ID_RE = re.compile(r"^[A-Z0-9]{20}$")


def _no_untrusted_symlink_ancestors(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            info = component.lstat()
            if (sys.platform == "darwin" and component == Path("/var")
                    and component.resolve() == Path("/private/var") and info.st_uid == 0):
                continue  # macOS system alias used by tempfile; no caller-controlled link.
            raise ValueError("symlink path component forbidden")


def _regular(path: Path, *, private: bool = False) -> None:
    _no_untrusted_symlink_ancestors(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("regular single-link file required")
    if private and stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("private 0600 file required")


def _sha(path: Path, *, private: bool = False, limit: int | None = None) -> tuple[int, str]:
    _regular(path, private=private)
    if limit is not None and path.stat().st_size > limit:
        raise ValueError("file exceeds size bound")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _json(path: Path, *, private: bool = False) -> dict:
    _sha(path, private=private, limit=5_000_000)
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


def _expected_json(path: Path, expected: str) -> dict:
    if not SHA_RE.fullmatch(expected) or _sha(path, limit=5_000_000)[1] != expected:
        raise ValueError("manifest differs from trusted contract SHA-256")
    return _json(path)


def _packet_contract(root: Path, expected: str | None, mode: str, split: str | None,
                     pose_sha: str | None, label_sha: str | None,
                     probe_sha: str | None) -> str | None:
    """Bind a revisioned role packet to its trusted manifest and exact payload."""
    manifest_path = root / "manifest.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        if expected is not None:
            raise ValueError("expected packet manifest is missing")
        return None  # Legacy prepared root, used only for local preparation QA.
    if expected is None:
        raise ValueError("trusted packet manifest SHA-256 required")
    manifest = _expected_json(manifest_path, expected)
    role = "agent" if split in ("val", "agent") else "evaluator"
    task_id = ("mabe22-supervised-segmentation" if mode == "supervised"
               else "mabe22-representation-classification")
    if (manifest.get("schema") != "bpb-mabe-role-packet/1"
            or manifest.get("role") != role or manifest.get("task_id") != task_id
            or not isinstance(manifest.get("files"), list)):
        raise ValueError("role packet schema/role mismatch")
    sources = manifest.get("source_manifests", {})
    required = ({"pose_preparation_manifest.json": pose_sha,
                 "label_extraction_manifest.json": label_sha} if mode == "supervised"
                else {"probe_preparation_manifest.json": probe_sha})
    if not isinstance(sources, dict) or any(sources.get(name) != sha for name, sha in required.items()
                                            if sha is not None):
        raise ValueError("role packet source manifest binding mismatch")
    expected_paths = set()
    for row in manifest["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ValueError("role packet file row schema mismatch")
        relative = row["path"]
        if not isinstance(relative, str) or "\\" in relative:
            raise ValueError("unsafe packet relative path")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
            raise ValueError("unsafe packet path components")
        if relative in expected_paths or type(row["bytes"]) is not int or row["bytes"] <= 0 or not SHA_RE.fullmatch(str(row["sha256"])):
            raise ValueError("duplicate or invalid packet file binding")
        expected_paths.add(relative)
        size, digest = _sha(root / relative)
        if (size, digest) != (row["bytes"], row["sha256"]):
            raise ValueError("role packet byte/SHA-256 mismatch")
    actual_paths = set()
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError("packet symlink forbidden")
        if item.is_file():
            actual_paths.add(item.relative_to(root).as_posix())
        elif not item.is_dir():
            raise ValueError("packet special file forbidden")
    if actual_paths != expected_paths | {"manifest.json"}:
        raise ValueError("role packet exact file set mismatch")
    return expected


def _slim_public_supervised(root: Path, packet_sha: str) -> tuple[dict, list[str], dict[str, np.ndarray]]:
    """Use only Agent-visible Train/Val files; no Test metadata is opened."""
    manifest = _expected_json(root / "manifest.json", packet_sha)
    if (manifest.get("schema") != "bpb-mabe-role-packet/1"
            or manifest.get("role") != "agent"
            or manifest.get("task_id") != "mabe22-supervised-segmentation"):
        raise ValueError("slim supervised packet schema mismatch")
    files = {row["path"]: row for row in manifest["files"]}
    train = {PurePosixPath(path).stem for path in files if path.startswith("public/pose/train/") and path.endswith(".npz")}
    val = {PurePosixPath(path).stem for path in files if path.startswith("public/pose/val/") and path.endswith(".npz")}
    if (len(train) != 54 or len(val) != 11 or train & val
            or any(not SUP_ID_RE.fullmatch(video_id) for video_id in train | val)
            or set(files) != {f"public/pose/train/{video_id}.npz" for video_id in train}
               | {f"public/pose/val/{video_id}.npz" for video_id in val}
               | {"public/train_labels.npz", "public/val_labels.npz"}):
        raise ValueError("slim public Train/Val file set mismatch")
    label_path = root / "public/val_labels.npz"
    if _sha(label_path)[1] != files["public/val_labels.npz"]["sha256"]:
        raise ValueError("public Valid label digest mismatch")
    with np.load(label_path, allow_pickle=False) as source:
        if set(source.files) != val:
            raise ValueError("public Valid label IDs mismatch")
        labels = {video_id: source[video_id].copy() for video_id in sorted(val)}
    if any(row.shape != (1800, 4) or row.dtype != np.uint8 or np.any(row > 1)
           for row in labels.values()):
        raise ValueError("public Valid label schema mismatch")
    pose_manifest = {"files": {video_id: {"path": f"public/pose/val/{video_id}.npz",
                                           "role": "val", "frames": 1800,
                                           "sha256": files[f"public/pose/val/{video_id}.npz"]["sha256"]}
                               for video_id in val}}
    return pose_manifest, sorted(val), labels


def snapshot_model(path: Path, *, frozen: bool = True) -> dict[str, dict[str, object]]:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("model directory required")
    if {child.name for child in path.iterdir()} != set(MODEL_FILES) | ({"freeze.json"} if frozen else set()):
        raise ValueError("model file set mismatch")
    bounds = {"model.py": 1_000_000, "config.json": 100_000, "weights.npz": 100_000_000}
    files = {name: {"bytes": size, "sha256": sha}
             for name in MODEL_FILES
             for size, sha in [_sha(path / name, limit=bounds[name])]}
    _json(path / "config.json")
    with zipfile.ZipFile(path / "weights.npz") as archive:
        members = archive.infolist()
        if (not members or len(members) > 128 or len({m.filename for m in members}) != len(members)
                or any(not m.filename.endswith(".npy") or "/" in m.filename or "\\" in m.filename
                       or m.file_size > 100_000_000 for m in members)
                or sum(m.file_size for m in members) > 100_000_000):
            raise ValueError("numeric weight archive bound")
    with np.load(path / "weights.npz", allow_pickle=False) as weights:
        if not weights.files:
            raise ValueError("empty weights")
        for key in weights.files:
            if not np.issubdtype(weights[key].dtype, np.number):
                raise ValueError("weights must be numeric without pickle")
    if frozen and _json(path / "freeze.json", private=True) != {"schema": MODEL_SCHEMA, "files": files}:
        raise ValueError("frozen model digest mismatch")
    return files


def freeze_model(source: Path, output: Path) -> dict:
    before = snapshot_model(source, frozen=False)
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh frozen model directory required")
    output.mkdir(mode=0o700, parents=True)
    for name in MODEL_FILES:
        with (source / name).open("rb") as reader, os.fdopen(os.open(output / name,
             os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as writer:
            shutil.copyfileobj(reader, writer)
    if snapshot_model(source, frozen=False) != before:
        raise ValueError("model mutated during freeze")
    manifest = {"schema": MODEL_SCHEMA, "files": before}
    with os.fdopen(os.open(output / "freeze.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if snapshot_model(output) != before:
        raise ValueError("frozen copy mismatch")
    return manifest


def _image_id(image: str) -> str:
    if not IMAGE_RE.fullmatch(image):
        raise ValueError("immutable sha256 image ID required")
    result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15)
    if result.returncode or result.stdout.strip() != image:
        raise RuntimeError("pinned Docker image unavailable")
    return image


def _container_batch(image: str, model: Path, keypoints: list[np.ndarray],
                     scores: list[np.ndarray], mode: str, scratch: Path) -> list[np.ndarray]:
    count = len(keypoints)
    if count != len(scores) or not 1 <= count <= (1 if mode == "supervised" else 16):
        raise ValueError("invalid inference batch")
    input_dir, output_dir = scratch / "input", scratch / "output"
    input_dir.mkdir(mode=0o700)
    output_dir.mkdir(mode=0o700)
    with os.fdopen(os.open(input_dir / "features.npz", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        np.savez(stream, **{**{f"keypoints_{i:03d}": value for i, value in enumerate(keypoints)},
                            **{f"scores_{i:03d}": value for i, value in enumerate(scores)}})
    context = {"task": "mabe22", "mode": mode, "count": count,
               "class_count": 4 if mode == "supervised" else 6}
    with os.fdopen(os.open(input_dir / "context.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(context, stream)
    uid, gid = (os.getuid(), os.getgid()) if os.getuid() != 0 else (65532, 65532)
    if os.getuid() == 0:
        for path in (input_dir, output_dir, input_dir / "features.npz", input_dir / "context.json"):
            os.chown(path, uid, gid)
    worker = Path(__file__).with_name("mabe_worker.py")
    command = ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
               "--cpus", "2", "--memory", "1g", "--memory-swap", "1g",
               "--ulimit", "fsize=67108864:67108864", "--ulimit", "nofile=64:64",
               "--user", f"{uid}:{gid}", "--tmpfs", "/tmp:rw,nosuid,noexec,size=64m",
               "--mount", f"type=bind,src={input_dir},dst=/input,readonly",
               "--mount", f"type=bind,src={output_dir},dst=/output",
               "--mount", f"type=bind,src={model},dst=/model,readonly",
               "--mount", f"type=bind,src={worker},dst=/worker/mabe_worker.py,readonly",
               "--entrypoint", "python", image, "/worker/mabe_worker.py", "/input/features.npz",
               "/input/context.json", "/model", "/output/results.npz"]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("isolated MABe prediction failed") from exc
    if result.returncode:
        raise RuntimeError("isolated MABe prediction rejected")
    result_path = output_dir / "results.npz"
    if {p.name for p in output_dir.iterdir()} != {"results.npz"}:
        raise ValueError("unexpected isolated output files")
    info = result_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("isolated result must be regular private single-link file")
    maximum = count * 1800 * (4 if mode == "supervised" else 128) * 4 + 16384
    if result_path.stat().st_size > maximum:
        raise ValueError("isolated output exceeds bound")
    with np.load(result_path, allow_pickle=False) as output:
        if set(output.files) != {f"output_{i:03d}" for i in range(count)}:
            raise ValueError("prediction array name mismatch")
        arrays = [output[f"output_{i:03d}"].copy() for i in range(count)]
    dimensions = set()
    for array in arrays:
        if array.dtype != np.float32 or not np.isfinite(array).all():
            raise ValueError("invalid isolated numeric output")
        if mode == "supervised":
            if array.shape != (1800, 4) or np.any((array < 0) | (array > 1)):
                raise ValueError("invalid independent probabilities")
        else:
            if array.ndim != 2 or array.shape[0] != 1800 or not 1 <= array.shape[1] <= 128:
                raise ValueError("invalid embedding shape")
            dimensions.add(array.shape[1])
    if len(dimensions) > 1:
        raise ValueError("embedding dimension differs within batch")
    return arrays


def _pose_contract(root: Path, expected_pose_sha: str) -> tuple[dict, dict[str, list[str]]]:
    manifest = _expected_json(root / "pose_preparation_manifest.json", expected_pose_sha)
    if manifest.get("schema") != "bpb-mabe-pose-preparation/1" or len(manifest.get("files", {})) != 108:
        raise ValueError("pose preparation manifest schema/count")
    source_path = root / "pose_source_manifest.json"
    if _sha(source_path)[1] != manifest.get("source_manifest_sha256"):
        raise ValueError("pose source manifest binding mismatch")
    source = _json(source_path)
    split_path = root / "mabe_finetune_split.json"
    if _sha(split_path)[1] != source.get("split_sha256"):
        raise ValueError("supervised split source binding mismatch")
    splits = _json(split_path).get("splits")
    if not isinstance(splits, dict) or {key: len(value) for key, value in splits.items()} != {"train": 54, "val": 11, "test": 43}:
        raise ValueError("supervised split count mismatch")
    ids = [video_id for rows in splits.values() for video_id in rows]
    if len(set(ids)) != 108 or set(ids) != set(manifest["files"]) or any(not SUP_ID_RE.fullmatch(i) for i in ids):
        raise ValueError("supervised split ID mismatch")
    return manifest, splits


def _read_pose(root: Path, entry: dict, video_id: str, role: str) -> np.ndarray:
    expected_path = f"public/pose/{role}/{video_id}.npz"
    if entry.get("path") != expected_path or entry.get("role") != role or entry.get("frames") != 1800:
        raise ValueError("pose manifest role/path mismatch")
    path = root / expected_path
    if _sha(path, limit=10_000_000)[1] != entry.get("sha256"):
        raise ValueError("pose NPZ SHA-256 mismatch")
    with np.load(path, allow_pickle=False) as source:
        if set(source.files) != {"pose", "frame_index"}:
            raise ValueError("pose array set mismatch")
        pose, index = source["pose"], source["frame_index"]
    if (pose.shape != (1800, 3, 12, 3) or pose.dtype != np.float32
            or index.dtype != np.int32 or not np.array_equal(index, np.arange(1800, dtype=np.int32))
            or np.isinf(pose).any()):
        raise ValueError("pose frame/dtype/infinity mismatch")
    return pose


def _read_labels(root: Path, role: str, ids: list[str], expected_label_sha: str,
                 owner_labels: Path | None) -> tuple[dict[str, np.ndarray], Path]:
    manifest = _expected_json(root / "label_extraction_manifest.json", expected_label_sha)
    if (manifest.get("schema") != "bpb-mabe-numeric-label-extraction/1"
            or manifest.get("class_order") != list(SEGMENTATION_CLASSES)):
        raise ValueError("label extraction contract mismatch")
    entry = manifest.get("outputs", {}).get(role)
    expected_path = f"owner/test_labels.npz" if role == "test" else f"public/{role}_labels.npz"
    if not isinstance(entry, dict) or entry.get("path") != expected_path or entry.get("videos") != len(ids):
        raise ValueError("label manifest role/count mismatch")
    path = owner_labels if role == "test" else root / expected_path
    if path is None or _sha(path, private=role == "test", limit=20_000_000)[1] != entry.get("sha256"):
        raise ValueError("trusted label NPZ SHA-256 mismatch")
    with np.load(path, allow_pickle=False) as source:
        if set(source.files) != set(ids):
            raise ValueError("label sequence ID set mismatch")
        labels = {video_id: source[video_id].copy() for video_id in ids}
    if any(row.shape != (1800, 4) or row.dtype != np.uint8 or np.any(row > 1)
           for row in labels.values()):
        raise ValueError("label array schema mismatch")
    return labels, path


def _probe_contract(root: Path, expected_probe_sha: str) -> tuple[dict, list[str]]:
    manifest = _expected_json(root / "probe_preparation_manifest.json", expected_probe_sha)
    if manifest.get("schema") != "bpb-mabe-probe-preparation/1":
        raise ValueError("probe preparation schema mismatch")
    profile = root / "public/probe_profile.json"
    if _sha(profile)[1] != manifest.get("profile_sha256"):
        raise ValueError("probe profile SHA-256 mismatch")
    mapping = manifest.get("pose_sha256_by_video")
    if not isinstance(mapping, dict) or len(mapping) != 1830 or any(not PROBE_ID_RE.fullmatch(key) or not SHA_RE.fullmatch(value)
                                                                   for key, value in mapping.items()):
        raise ValueError("probe pose mapping mismatch")
    return manifest, sorted(mapping)


def _read_probe_pose(root: Path, video_id: str, expected: str) -> np.ndarray:
    path = root / "public/probe_pose" / f"{video_id}.npz"
    if _sha(path, limit=5_000_000)[1] != expected:
        raise ValueError("probe keypoint NPZ SHA-256 mismatch")
    with np.load(path, allow_pickle=False) as source:
        if set(source.files) != {"keypoints"}:
            raise ValueError("probe pose array set mismatch")
        pose = source["keypoints"]
    if pose.shape != (1800, 3, 12, 2) or pose.dtype != np.int32:
        raise ValueError("probe keypoint shape/dtype mismatch")
    return pose.astype(np.float32)


def _private_output(path: Path) -> None:
    _no_untrusted_symlink_ancestors(path)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ValueError("output directory must be owner-only 0700")


def _save_npz(path: Path, name: str, value: np.ndarray) -> str:
    if path.exists() or path.is_symlink():
        raise FileExistsError("fresh result file required")
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        np.savez(stream, **{name: value})
    return _sha(path, private=True)[1]


def evaluate(args: argparse.Namespace) -> dict:
    image = _image_id(args.image)
    before_model = snapshot_model(args.submission)
    _private_output(args.output_dir)
    packet_sha = _packet_contract(args.root, args.expected_packet_manifest_sha256, args.mode, args.split,
                                  args.expected_pose_manifest_sha256, args.expected_label_manifest_sha256,
                                  args.expected_probe_manifest_sha256)
    if args.mode == "supervised":
        if args.split not in ("val", "test"):
            raise ValueError("supervised mode requires explicit val or test split")
        slim_public = args.split == "val" and not (args.root / "pose_preparation_manifest.json").exists()
        if slim_public:
            if packet_sha is None:
                raise ValueError("slim public validation requires trusted packet digest")
            pose_manifest, ids, labels = _slim_public_supervised(args.root, packet_sha)
            label_path = args.root / "public/val_labels.npz"
            splits = None
        else:
            if args.expected_pose_manifest_sha256 is None or args.expected_label_manifest_sha256 is None:
                raise ValueError("trusted pose/label manifest SHAs required")
            pose_manifest, splits = _pose_contract(args.root, args.expected_pose_manifest_sha256)
            ids = splits[args.split]
            labels, label_path = _read_labels(args.root, args.split, ids, args.expected_label_manifest_sha256,
                                             args.owner_labels)
        if args.split == "test" and args.owner_labels is None:
            raise ValueError("explicit owner label path required for Test")
        if {p.name for p in args.output_dir.iterdir()}:
            raise ValueError("fresh empty output directory required")
        truth, prediction, mask, output_hashes = {}, {}, {}, {}
        with tempfile.TemporaryDirectory(prefix="bpb-mabe-inference-") as tmp:
            scratch = Path(tmp)
            model_mount = _model_mount(args.submission, before_model, scratch)
            for index, video_id in enumerate(ids):
                pose = _read_pose(args.root, pose_manifest["files"][video_id], video_id, args.split)
                clip = scratch / f"clip-{index:03d}"
                clip.mkdir(mode=0o700)
                result = _container_batch(image, model_mount, [pose[..., :2].copy()],
                                          [pose[..., 2].copy()], "supervised", clip)[0]
                truth[video_id] = labels[video_id].astype(int).tolist()
                prediction[video_id] = result.astype(float).tolist()
                mask[video_id] = (labels[video_id].any(axis=1) & pose_valid_frames(pose)).tolist()
                output_hashes[video_id] = _save_npz(args.output_dir / f"{video_id}.npz", "probabilities", result)
        for video_id in ids:
            _read_pose(args.root, pose_manifest["files"][video_id], video_id, args.split)
        if slim_public:
            if _slim_public_supervised(args.root, packet_sha)[1] != ids:
                raise ValueError("public Valid packet mutated during inference")
        else:
            if (_sha(args.root / "label_extraction_manifest.json")[1] != args.expected_label_manifest_sha256
                    or _sha(label_path)[1] != _json(args.root / "label_extraction_manifest.json")["outputs"][args.split]["sha256"]):
                raise ValueError("labels mutated during inference")
            if _sha(args.root / "pose_preparation_manifest.json")[1] != args.expected_pose_manifest_sha256:
                raise ValueError("pose manifest mutated during inference")
            if _pose_contract(args.root, args.expected_pose_manifest_sha256)[1] != splits:
                raise ValueError("supervised split mutated during inference")
        if {video_id: _sha(args.output_dir / f"{video_id}.npz", private=True)[1] for video_id in ids} != output_hashes:
            raise ValueError("prediction artifacts mutated during scoring")
        metrics = score_supervised_segmentation(truth, prediction, mask)
        result = {"schema": "bpb-mabe-isolated-inference/1", "mode": "supervised", "split": args.split,
                  "profile": "Bench adaptation; source-style pose validity and positive frame eligibility",
                  "metrics": metrics, "videos": len(ids), "output_sha256_by_video": output_hashes,
                  "pose_manifest_sha256": args.expected_pose_manifest_sha256,
                  "label_manifest_sha256": args.expected_label_manifest_sha256}
    else:
        if args.split is not None or args.expected_probe_manifest_sha256 is None:
            raise ValueError("representation mode requires trusted probe manifest SHA")
        manifest, all_ids = _probe_contract(args.root, args.expected_probe_manifest_sha256)
        ids = all_ids[:args.max_clips] if args.max_clips else all_ids
        if {p.name for p in args.output_dir.iterdir()}:
            raise ValueError("fresh empty output directory required")
        dimensions, output_hashes = set(), {}
        with tempfile.TemporaryDirectory(prefix="bpb-mabe-inference-") as tmp:
            scratch = Path(tmp)
            model_mount = _model_mount(args.submission, before_model, scratch)
            for batch_index in range(0, len(ids), 16):
                batch_ids = ids[batch_index:batch_index + 16]
                poses = [_read_probe_pose(args.root, video_id, manifest["pose_sha256_by_video"][video_id])
                         for video_id in batch_ids]
                batch = scratch / f"batch-{batch_index // 16:03d}"
                batch.mkdir(mode=0o700)
                outputs = _container_batch(image, model_mount, poses,
                                           [np.empty((1800, 0), np.float32) for _ in poses],
                                           "representation", batch)
                for video_id, embedding in zip(batch_ids, outputs):
                    dimensions.add(embedding.shape[1])
                    if len(dimensions) != 1:
                        raise ValueError("embedding dimensions differ across clips")
                    output_hashes[video_id] = _save_npz(args.output_dir / f"{video_id}.npz", "embedding", embedding)
        for video_id in ids:
            _read_probe_pose(args.root, video_id, manifest["pose_sha256_by_video"][video_id])
        if _sha(args.root / "probe_preparation_manifest.json")[1] != args.expected_probe_manifest_sha256:
            raise ValueError("probe manifest mutated during inference")
        if _sha(args.root / "public/probe_profile.json")[1] != manifest["profile_sha256"]:
            raise ValueError("probe profile mutated during inference")
        if {video_id: _sha(args.output_dir / f"{video_id}.npz", private=True)[1] for video_id in ids} != output_hashes:
            raise ValueError("embedding artifacts mutated during inference")
        result = {"schema": "bpb-mabe-isolated-inference/1", "mode": "representation",
                  "complete": len(ids) == 1830, "videos": len(ids), "embedding_dimension": dimensions.pop(),
                  "output_sha256_by_video": output_hashes,
                  "probe_manifest_sha256": args.expected_probe_manifest_sha256}
        if args.score_probe:
            if len(ids) != 1830:
                raise ValueError("owner probe score requires all 1,830 clips")
            from mabe_probe import embedding_file, score_owner_test, validate_embedding_directory
            validate_embedding_directory(args.root, args.output_dir)
            _verify_probe_labels(args.root, manifest)
            result["metrics"] = score_owner_test(args.root, lambda video_id: embedding_file(args.output_dir, video_id))
            _verify_probe_labels(args.root, manifest)
    if snapshot_model(args.submission) != before_model:
        raise ValueError("frozen model mutated during inference")
    if _packet_contract(args.root, args.expected_packet_manifest_sha256, args.mode, args.split,
                        args.expected_pose_manifest_sha256, args.expected_label_manifest_sha256,
                        args.expected_probe_manifest_sha256) != packet_sha:
        raise ValueError("role packet mutated during inference")
    result.update({"kind": args.run_kind, "image_id": image, "frozen_files": before_model,
                   "packet_manifest_sha256": packet_sha})
    return result


def _model_mount(source: Path, frozen_files: dict, scratch: Path) -> Path:
    if os.getuid() != 0:
        return source
    staged = scratch / "model"
    staged.mkdir(mode=0o755)
    for name in (*MODEL_FILES, "freeze.json"):
        shutil.copyfile(source / name, staged / name)
        os.chmod(staged / name, 0o644)
    if {name: _sha(staged / name)[1] for name in MODEL_FILES} != {
            name: row["sha256"] for name, row in frozen_files.items()}:
        raise ValueError("model staging digest mismatch")
    return staged


def _verify_probe_labels(root: Path, manifest: dict) -> None:
    for role, entry in manifest.get("label_files", {}).items():
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative.startswith(("owner/probe_labels/", "evaluator/probe_labels/")):
            raise ValueError("probe label path outside trusted roots")
        if _sha(root / relative, private=True)[1] != entry.get("sha256"):
            raise ValueError("trusted probe label SHA-256 mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("supervised", "representation"), required=True)
    parser.add_argument("--split", choices=("val", "test"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--owner-labels", type=Path)
    parser.add_argument("--expected-pose-manifest-sha256")
    parser.add_argument("--expected-label-manifest-sha256")
    parser.add_argument("--expected-probe-manifest-sha256")
    parser.add_argument("--expected-packet-manifest-sha256",
                        help="trusted digest required when --root is a revisioned role packet")
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="existing empty 0700 result directory")
    parser.add_argument("--max-clips", type=int, default=0, help="representation smoke limit; 0 means all clips")
    parser.add_argument("--score-probe", action="store_true", help="explicit owner-only six-task probe")
    parser.add_argument("--run-kind", choices=("fixed-reference", "agent-submission"), default="agent-submission")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.max_clips < 0 or args.max_clips > 1830:
        parser.error("max clips must be 0..1830")
    if args.mode == "supervised" and (args.max_clips or args.score_probe or args.expected_probe_manifest_sha256):
        parser.error("supervised mode cannot use representation options")
    if args.mode == "representation" and (args.owner_labels or args.expected_pose_manifest_sha256
                                           or args.expected_label_manifest_sha256):
        parser.error("representation mode cannot use supervised options")
    private = args.split == "test" or args.score_probe
    _no_untrusted_symlink_ancestors(args.report)
    if private and ("owner" not in args.report.parts or stat.S_IMODE(args.report.parent.stat().st_mode) != 0o700):
        parser.error("private report requires owner 0700 directory")
    if args.report.exists() or args.report.is_symlink():
        raise FileExistsError("fresh report path required")
    result = evaluate(args)
    with os.fdopen(os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if private:
        print(json.dumps({"mode": args.mode, "split": args.split, "scored": True,
                          "report": str(args.report), "metrics_redacted": True}))
    else:
        print(json.dumps({"mode": args.mode, "split": args.split, "videos": result["videos"],
                          "complete": result.get("complete", True), "metrics": result.get("metrics")}))


if __name__ == "__main__":
    main()
