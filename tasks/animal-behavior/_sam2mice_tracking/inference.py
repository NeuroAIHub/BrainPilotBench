"""Trusted tracking inference. Submitted Python runs only in isolated Docker."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile

import numpy as np

TASK_ID = "sam2mice-multi-animal-tracking"
FILES = ("model.py", "config.json", "weights.npz")
MODEL_LIMITS = {"model.py": 1_000_000, "config.json": 100_000,
                "weights.npz": 100_000_000}
MAX_FEATURE_BYTES = 512_000_000
MAX_FRAMES = 128
MAX_DETECTIONS_PER_FRAME = 64
MAX_TRACKS_PER_SEQUENCE = 1024
SHA = re.compile(r"^[0-9a-f]{64}$")
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")


def safe_file(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("symlink path component forbidden")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("independent regular file required")


def digest_file(path: Path) -> dict:
    safe_file(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after):
        raise ValueError("file changed while hashing")
    return {"bytes": before.st_size, "sha256": digest.hexdigest()}


def _json(path: Path) -> dict:
    safe_file(path)
    if path.stat().st_size > 100_000:
        raise ValueError("JSON exceeds bound")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def invalid_constant(_value):
        raise ValueError("nonfinite JSON constant")

    value = json.loads(path.read_text(), object_pairs_hook=pairs,
                       parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _npy_header(stream, file_bytes: int, max_bytes: int) -> tuple:
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, order, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=4096)
    elif version == (2, 0):
        shape, order, dtype = np.lib.format.read_array_header_2_0(stream, max_header_size=4096)
    else:
        raise ValueError("unsupported numeric NPY header")
    if (dtype.hasobject or dtype.kind not in "biufc" or len(shape) > 8
            or any(type(size) is not int or size < 0 for size in shape)):
        raise ValueError("numeric array header required")
    payload_bytes = math.prod(shape) * dtype.itemsize
    if payload_bytes > max_bytes or stream.tell() + payload_bytes != file_bytes:
        raise ValueError("NPY payload/header size mismatch")
    return shape, order, dtype


def numeric_npz(path: Path, *, max_bytes: int) -> dict[str, np.ndarray]:
    """Validate archive expansion and array headers before NumPy allocates data."""
    safe_file(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("archive exceeds compressed size bound")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (not entries or len(entries) > 128
                or len({entry.filename for entry in entries}) != len(entries)
                or sum(entry.file_size for entry in entries) > max_bytes):
            raise ValueError("archive member or expansion bound")
        for entry in entries:
            if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.npy", entry.filename)
                    or entry.file_size > max_bytes):
                raise ValueError("unsafe archive member")
            with archive.open(entry) as source:
                _npy_header(source, entry.file_size, max_bytes)
    with np.load(path, allow_pickle=False) as source:
        return {key: source[key] for key in source.files}


def snapshot_model(source: Path, *, frozen: bool = False) -> dict:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("model directory required")
    expected = set(FILES) | ({"freeze.json"} if frozen else set())
    if {item.name for item in source.iterdir()} != expected:
        raise ValueError("exact three-file model contract required")
    result = {}
    for name in FILES:
        safe_file(source / name)
        if (source / name).stat().st_size > MODEL_LIMITS[name]:
            raise ValueError("model artifact exceeds size bound")
        result[name] = digest_file(source / name)
    _json(source / "config.json")
    weights = numeric_npz(source / "weights.npz", max_bytes=MODEL_LIMITS["weights.npz"])
    if any(not np.isfinite(value).all() for value in weights.values()):
        raise ValueError("weights contain nonfinite values")
    if frozen:
        manifest = _json(source / "freeze.json")
        if manifest != {"schema": "bpb-sam2mice-tracking-frozen/1", "files": result}:
            raise ValueError("frozen model identity mismatch")
    return result


def freeze_model(source: Path, destination: Path) -> dict:
    before = snapshot_model(source)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("fresh model freeze required")
    if any(part.is_symlink() for part in (destination.parent, *destination.parent.parents)):
        raise ValueError("freeze destination has a symlink ancestor")
    destination.mkdir(mode=0o700, parents=True)
    for name in FILES:
        with (source / name).open("rb") as reader, os.fdopen(os.open(
                destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
            shutil.copyfileobj(reader, writer)
    if snapshot_model(source) != before or snapshot_model(destination) != before:
        raise ValueError("model changed during freeze")
    manifest = {"schema": "bpb-sam2mice-tracking-frozen/1", "files": before}
    with os.fdopen(os.open(destination / "freeze.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as writer:
        json.dump(manifest, writer, sort_keys=True)
    snapshot_model(destination, frozen=True)
    return manifest


def _verify_bound(path: Path, size: int, sha: str) -> None:
    if type(size) is not int or size <= 0 or not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError("exact byte and SHA-256 binding required")
    if digest_file(path) != {"bytes": size, "sha256": sha}:
        raise ValueError("data byte or SHA-256 mismatch")


def _features(frames: np.ndarray) -> None:
    if (not isinstance(frames, np.ndarray) or frames.ndim != 4
            or frames.dtype != np.uint8 or not 0 < len(frames) <= MAX_FRAMES
            or frames.shape[-1] != 3 or not 1 <= frames.shape[1] <= 4096
            or not 1 <= frames.shape[2] <= 4096 or frames.nbytes > MAX_FEATURE_BYTES - 4096):
        raise ValueError("RGB frame shape, dtype or size differs")


def load_features(path: Path, *, expected_bytes: int, expected_sha256: str,
                  frames: int | None = None) -> np.ndarray:
    _verify_bound(path, expected_bytes, expected_sha256)
    arrays = numeric_npz(path, max_bytes=MAX_FEATURE_BYTES)
    if set(arrays) != {"frames"}:
        raise ValueError("feature packet must contain RGB frames only")
    rgb = arrays["frames"]
    _features(rgb)
    if frames is not None and (type(frames) is not int or len(rgb) != frames):
        raise ValueError("bound sequence frame count differs")
    _verify_bound(path, expected_bytes, expected_sha256)
    return rgb


def validate_detections(detections: np.ndarray, frames: int) -> np.ndarray:
    """Rows contain local frame index, arbitrary track ID, and normalized xyxy."""
    if (type(frames) is not int or not 0 < frames <= MAX_FRAMES
            or not isinstance(detections, np.ndarray) or detections.ndim != 2
            or detections.shape[1] != 6 or detections.dtype.kind != "f"
            or len(detections) > frames * MAX_DETECTIONS_PER_FRAME
            or not np.isfinite(detections).all()):
        raise ValueError("tracking output shape, dtype or count differs")
    indices, identities, boxes = detections[:, 0], detections[:, 1], detections[:, 2:]
    if (np.any(indices != np.floor(indices)) or np.any((indices < 0) | (indices >= frames))
            or np.any(identities != np.floor(identities))
            or np.any((identities < 0) | (identities > 2**31 - 1))
            or np.any((boxes < 0) | (boxes > 1))
            or np.any(boxes[:, 2:] <= boxes[:, :2])):
        raise ValueError("tracking frame, identity or box values differ")
    if len(detections):
        if (len(np.unique(detections[:, :2], axis=0)) != len(detections)
                or np.max(np.bincount(indices.astype(np.int64), minlength=frames)) > MAX_DETECTIONS_PER_FRAME
                or len(np.unique(identities)) > MAX_TRACKS_PER_SEQUENCE):
            raise ValueError("duplicate identity or tracking count bound exceeded")
        order = np.lexsort((identities, indices))
        return detections[order].astype(np.float64)
    return np.empty((0, 6), dtype=np.float64)


def load_truth(path: Path, *, expected_bytes: int, expected_sha256: str,
               frames: int) -> np.ndarray:
    _verify_bound(path, expected_bytes, expected_sha256)
    arrays = numeric_npz(path, max_bytes=4_000_000)
    if set(arrays) != {"detections"}:
        raise ValueError("truth packet must contain detections only")
    result = validate_detections(arrays["detections"], frames)
    _verify_bound(path, expected_bytes, expected_sha256)
    return result


def _image_id(image: str) -> str:
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise ValueError("immutable local Docker image ID required")
    result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, timeout=15)
    if result.returncode or result.stdout.strip() != image:
        raise RuntimeError("pinned Docker image unavailable")
    return image


def predict_sequence(image: str, frozen_submission: Path, frames: np.ndarray,
                     *, timeout: int = 180) -> np.ndarray:
    """A fresh container sees only one RGB sequence and the frozen model."""
    _features(frames)
    _image_id(image)
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise ValueError("bounded timeout required")
    before = snapshot_model(frozen_submission, frozen=True)
    with tempfile.TemporaryDirectory(prefix="bpb-tracking-infer-", dir=Path(tempfile.gettempdir()).resolve()) as directory:
        scratch = Path(directory)
        inputs, outputs = scratch / "input", scratch / "output"
        inputs.mkdir(mode=0o700)
        outputs.mkdir(mode=0o700)
        target = outputs / "predictions.npy"
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"):
            pass
        target_identity = (target.stat().st_dev, target.stat().st_ino)
        mounted_model = scratch / "model"
        mounted_model.mkdir(mode=0o700)
        for name in (*FILES, "freeze.json"):
            with (frozen_submission / name).open("rb") as reader, os.fdopen(os.open(
                    mounted_model / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
                shutil.copyfileobj(reader, writer)
        if snapshot_model(mounted_model, frozen=True) != before:
            raise ValueError("staged model differs from frozen model")
        with os.fdopen(os.open(inputs / "features.npz", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
            np.savez(writer, frames=frames)
        uid, gid = (os.getuid(), os.getgid()) if os.getuid() else (65532, 65532)
        if os.getuid() == 0:
            for item in (scratch, inputs, outputs, target, inputs / "features.npz", mounted_model, *mounted_model.iterdir()):
                os.chown(item, uid, gid)
        worker = Path(__file__).with_name("worker.py").resolve()
        safe_file(worker)
        container = "bpb-tracking-" + uuid.uuid4().hex
        command = ["docker", "run", "--rm", "--pull", "never", "--name", container,
                   "--network", "none", "--read-only", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges", "--pids-limit", "64",
                   "--cpus", "2", "--memory", "2g", "--memory-swap", "2g",
                   "--ulimit", "fsize=4194304:4194304", "--ulimit", "nofile=64:64",
                   "--user", f"{uid}:{gid}", "--tmpfs", "/tmp:rw,nosuid,noexec,size=64m",
                   "--mount", f"type=bind,src={inputs},dst=/input,readonly",
                   "--mount", f"type=bind,src={target},dst=/output/predictions.npy",
                   "--mount", f"type=bind,src={mounted_model},dst=/model,readonly",
                   "--mount", f"type=bind,src={worker},dst=/worker/worker.py,readonly",
                   "--entrypoint", "python", image, "/worker/worker.py"]
        try:
            result = subprocess.run(command, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=timeout)
            if result.returncode:
                raise RuntimeError("isolated tracking prediction rejected")
        except (subprocess.TimeoutExpired, OSError) as error:
            raise RuntimeError("isolated tracking prediction failed") from error
        finally:
            try:
                subprocess.run(["docker", "rm", "--force", container],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except (subprocess.TimeoutExpired, OSError):
                pass
        if {item.name for item in outputs.iterdir()} != {"predictions.npy"}:
            raise ValueError("unexpected isolated outputs")
        safe_file(target)
        if (target.stat().st_dev, target.stat().st_ino) != target_identity:
            raise ValueError("isolated output file identity changed")
        if stat.S_IMODE(target.stat().st_mode) != 0o600:
            raise ValueError("isolated output must be mode 0600")
        max_output = len(frames) * MAX_DETECTIONS_PER_FRAME * 6 * 8
        if target.stat().st_size > max_output + 4096:
            raise ValueError("prediction exceeds output bound")
        with target.open("rb") as reader:
            shape, _order, dtype = _npy_header(reader, target.stat().st_size, max_output)
        if len(shape) != 2 or shape[1] != 6 or dtype.kind != "f":
            raise ValueError("prediction header differs from contract")
        result = validate_detections(np.load(target, allow_pickle=False), len(frames))
        if (snapshot_model(frozen_submission, frozen=True) != before
                or snapshot_model(mounted_model, frozen=True) != before):
            raise ValueError("frozen model changed during prediction")
        return result


def _resolve(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or relative.startswith("/")
            or any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) or part in (".", "..")
                   for part in relative.split("/"))):
        raise ValueError("safe relative data path required")
    return root / relative


def evaluate_sequences(feature_root: Path, rows: list[dict], submission: Path,
                       image: str) -> dict[str, np.ndarray]:
    if not isinstance(rows, list) or not 0 < len(rows) <= 128:
        raise ValueError("nonempty evaluation sequence list required")
    identifiers = [row.get("id") for row in rows]
    if (any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in identifiers)
            or len(set(identifiers)) != len(identifiers)
            or len({row.get("feature_path") for row in rows}) != len(rows)):
        raise ValueError("unique safe sequence identifiers required")
    original = snapshot_model(submission)
    predictions = {}
    with tempfile.TemporaryDirectory(prefix="bpb-tracking-model-", dir=Path(tempfile.gettempdir()).resolve()) as directory:
        frozen = Path(directory) / "model"
        freeze_model(submission, frozen)
        for row in rows:
            source = _resolve(feature_root, row["feature_path"])
            frames = load_features(source, expected_bytes=row["feature_bytes"],
                                   expected_sha256=row["feature_sha256"], frames=row["frames"])
            predictions[row["id"]] = predict_sequence(image, frozen, frames)
            _verify_bound(source, row["feature_bytes"], row["feature_sha256"])
        if snapshot_model(submission) != original or snapshot_model(frozen, frozen=True) != original:
            raise ValueError("model changed across evaluation")
    return predictions
