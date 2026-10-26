"""Owner-only independent EEG Test scorer for hash-bound evaluator packets.

Only feature arrays and a frozen seed's required model files enter Docker. The
evaluator packet, labels, owner snapshot, and private report stay in this
trusted process. This result is not an official upstream leaderboard score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
import zipfile

import numpy as np

from score import (REQUIRED, balanced_accuracy, copy_verified_required_file, digest,
                   inspect_prediction, read_contract, valid_image_reference)

LOCK_SCHEMA = "bpb-evaluator-data/1"
FREEZE_SCHEMA = "bpb-private-submission-freeze/1"
REPO_ID = "BrainPilot-Bench/Tasks-Data-Private"
SLEEP_TASK = "eeg-sleep-stage-sleepedf"
STANDARD_FILES = {"binding.json", "test.npz", "test-labels.npy"}
SLEEP_FILES = {"binding.json", "shards.json", "test-shards.tar"}
LIMITS = {"model.py": 1_000_000, "config.json": 256_000,
          "weights.safetensors": 100_000_000}
HEX = set("0123456789abcdef")


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def _regular(path: Path, *, max_bytes: int | None = None) -> int:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            info.st_size <= 0 or (max_bytes and info.st_size > max_bytes)):
        raise ValueError(f"missing, linked, empty, or oversized regular file: {path.name}")
    return info.st_size


def _json(path: Path, *, max_bytes: int = 1_000_000) -> dict:
    _regular(path, max_bytes=max_bytes)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key in trusted metadata")
            result[key] = value
        return result
    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON metadata")))
    if not isinstance(result, dict):
        raise ValueError(f"invalid JSON object: {path.name}")
    return result


def _path_name(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("unsafe relative path in frozen metadata")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("unsafe relative path in frozen metadata")
    return value


def _task_version(task: Path) -> str:
    _regular(task / "task.yaml", max_bytes=1_000_000)
    values = re.findall(r'(?m)^version:\s*["\']?([^"\'\n]+)["\']?\s*$',
                        (task / "task.yaml").read_text(encoding="utf-8"))
    if len(values) != 1 or not values[0].strip():
        raise ValueError("task version is missing or ambiguous")
    return values[0].strip()


def verify_frozen(artifacts: Path, snapshot: dict, task_id: str,
                  task_version: str) -> dict[str, str]:
    """Verify the complete submitted tree, including unrequired extra files."""
    if artifacts.is_symlink() or not artifacts.is_dir() or artifacts.resolve(strict=True) != artifacts:
        raise ValueError("artifact root is missing or linked")
    if (set(snapshot) != {"schema", "task_id", "task_version", "files"} or
            snapshot.get("schema") != FREEZE_SCHEMA or snapshot.get("task_id") != task_id or
            snapshot.get("task_version") != task_version):
        raise ValueError("frozen submission identity mismatch")
    expected = snapshot.get("files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("frozen submission has no file map")
    for name, value in expected.items():
        _path_name(name)
        if not _sha(value):
            raise ValueError("invalid frozen submission digest")
    observed = {}
    for parent, dirs, files in os.walk(artifacts, followlinks=False):
        for name in dirs:
            if (Path(parent) / name).is_symlink():
                raise ValueError("linked artifact directory")
        for name in files:
            path = Path(parent) / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("artifact tree contains a linked or special file")
            relative = path.relative_to(artifacts).as_posix()
            observed[relative] = digest(path)
    if observed != expected:
        raise ValueError("artifact tree differs from frozen submission")
    for seed in range(3):
        for name in REQUIRED:
            if f"submission/seed-{seed}/{name}" not in observed:
                raise ValueError("frozen submission lacks a required seed file")
    return observed


def verify_packet(task: Path, data: Path, contract: dict) -> tuple[dict, dict, dict]:
    """Check the owner lock, local bytes, and normalized source/public binding."""
    if data.is_symlink() or not data.is_dir() or data.resolve(strict=True) != data:
        raise ValueError("prepared evaluator root is missing or linked")
    lock = _json(task / "evaluator.lock")
    revision = lock.get("revision")
    if (lock.get("schema") != LOCK_SCHEMA or lock.get("task_id") != contract["task_id"] or
            lock.get("repo_id") != REPO_ID or not isinstance(revision, str) or
            len(revision) != 40 or not set(revision) <= HEX):
        raise ValueError("invalid evaluator lock identity or immutable revision")
    files = lock.get("files")
    expected_names = SLEEP_FILES if contract["task_id"] == SLEEP_TASK else STANDARD_FILES
    if not isinstance(files, list) or len(files) != len(expected_names):
        raise ValueError("evaluator lock file set differs from private package")
    records = {}
    packet = data / "test"
    if (packet.is_symlink() or not packet.is_dir() or
            set(os.listdir(data)) != {"test", ".bpb-evaluator.json"} or
            set(os.listdir(packet)) != expected_names):
        raise ValueError("prepared evaluator root contains unexpected files")
    prepared = _json(data / ".bpb-evaluator.json", max_bytes=65_536)
    if (prepared.get("schema") != "bpb-prepared-evaluator/1" or
            prepared.get("task_id") != contract["task_id"] or
            prepared.get("revision") != revision or prepared.get("files") != len(files) or
            prepared.get("evaluator_lock_sha256") != digest(task / "evaluator.lock")):
        raise ValueError("prepared evaluator receipt differs from task lock")
    seen_names = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("invalid evaluator file record")
        name, relative = entry.get("name"), entry.get("path")
        if (not isinstance(name, str) or not name or name in seen_names or
                _path_name(relative) not in {"test/" + x for x in expected_names}):
            raise ValueError("unsafe or duplicate evaluator file record")
        seen_names.add(name)
        basename = PurePosixPath(relative).name
        if basename in records:
            raise ValueError("unsafe or duplicate evaluator file record")
        if not _sha(entry.get("sha256")) or type(entry.get("bytes")) is not int or entry["bytes"] <= 0:
            raise ValueError("invalid evaluator file hash or size")
        path = data / relative
        if _regular(path) != entry["bytes"] or digest(path) != entry["sha256"]:
            raise ValueError(f"private evaluator file differs from lock: {name}")
        records[basename] = entry
    if set(records) != expected_names:
        raise ValueError("evaluator lock omits a required private file")
    binding = _json(packet / "binding.json", max_bytes=65_536)
    sleep = contract["task_id"] == SLEEP_TASK
    if binding.get("schema") != ("bpb-eeg-private-sharded-test-binding/1" if sleep else
                                 "bpb-eeg-private-test-binding/1"):
        raise ValueError("unrecognized EEG private binding")
    for field in ("task_id", "source_task_id", "source_task_version"):
        if binding.get(field) != contract[field]:
            raise ValueError(f"private binding differs from task contract: {field}")
    spec_field = "source_task_spec_sha256_from_public_contract" if sleep else "source_task_spec_sha256"
    if binding.get(spec_field) != contract["source_task_spec_sha256"]:
        raise ValueError("private source task specification differs from public contract")
    if binding.get("public_data") != contract["data_files"]:
        raise ValueError("private binding differs from frozen public file hashes")
    rows = binding.get("test_samples")
    if type(rows) is not int or rows <= 0:
        raise ValueError("private Test row count is invalid")
    if sleep:
        if (binding.get("sample_shape") != contract["input_shape"] or
                binding.get("test_tar_sha256") != records["test-shards.tar"]["sha256"] or
                binding.get("test_tar_bytes") != records["test-shards.tar"]["bytes"] or
                binding.get("shards_manifest_sha256") != records["shards.json"]["sha256"]):
            raise ValueError("Sleep-EDF Test shard binding mismatch")
    else:
        if (binding.get("source_sha") != contract["source_sha"] or
                binding.get("test_npz_members") != ["x.npy"]):
            raise ValueError("private Test source or member binding mismatch")
        for name in ("test.npz", "test-labels.npy"):
            if binding.get("private_data", {}).get(name) != {
                    "sha256": records[name]["sha256"], "bytes": records[name]["bytes"]}:
                raise ValueError("private Test payload differs from normalized source binding")
    return lock, records, binding


def _labels(array: np.ndarray, rows: int, classes: int, profile: str,
            *, require_complete: bool = True) -> np.ndarray:
    """Accept native integer targets or strictly one-hot target rows."""
    if array.shape == (rows,) and array.dtype.kind in "iu":
        labels = array.astype(np.int64, copy=False)
    elif array.shape == (rows, classes) and array.dtype.kind in "biuf":
        if not np.isfinite(array).all() or not np.isin(array, (0, 1)).all() or not (array.sum(1) == 1).all():
            raise ValueError("private Test targets are not strictly one-hot")
        labels = np.argmax(array, axis=1).astype(np.int64)
    else:
        raise ValueError("private Test target shape or dtype is unsupported")
    if not np.isin(labels, np.arange(classes)).all():
        raise ValueError("private Test targets differ from class contract")
    if require_complete and profile == "native-balanced-accuracy-complete-classes" and len(np.unique(labels)) != classes:
        raise ValueError("native full-class metric requires every Test class")
    return labels


def _stage_x_member(package: Path, destination: Path, rows: int, shape: list[int]) -> None:
    with zipfile.ZipFile(package) as archive:
        if archive.namelist() != ["x.npy"]:
            raise ValueError("private Test NPZ must contain only x.npy")
        byte_count = archive.getinfo("x.npy").file_size
        elements = rows * math.prod(shape)
        if not elements * 4 <= byte_count <= elements * 8 + 4096:
            raise ValueError("private Test x member size is implausible")
        with archive.open("x.npy") as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    x = np.load(destination, mmap_mode="r", allow_pickle=False)
    if x.shape != (rows, *shape) or x.dtype not in (np.dtype("float32"), np.dtype("float64")):
        raise ValueError("private Test x differs from input contract")
    destination.chmod(0o444)


def _confusion(labels: np.ndarray, predictions: np.ndarray, classes: int) -> np.ndarray:
    result = np.zeros((classes, classes), dtype=np.int64)
    np.add.at(result, (labels, predictions), 1)
    return result


def _score_confusion(confusion: np.ndarray, profile: str) -> float:
    # Reuse the public metric implementation on the sufficient statistics only.
    truth, predicted = np.nonzero(confusion)
    labels = np.repeat(truth, confusion[truth, predicted])
    guesses = np.repeat(predicted, confusion[truth, predicted])
    return balanced_accuracy(labels, guesses, len(confusion), profile)


def _infer(seed_dir: Path, x: Path, output: Path, contract: dict, image: str,
           rows: int, expected_hashes: dict[str, str]) -> np.ndarray:
    output.mkdir(mode=0o777)
    output.chmod(0o777)
    container = "bpb-eeg-private-" + uuid.uuid4().hex
    command = ["docker", "run", "--rm", "--name", container, "--network", "none",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--cpus", "2", "--memory", "4g", "--pids-limit", "128",
               "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
               "-v", f"{seed_dir}:/submission:ro", "-v", f"{x}:/input/x.npy:ro",
               "-v", f"{Path(__file__).with_name('worker.py')}:/worker.py:ro",
               "-v", f"{output}:/output", image, "python", "/worker.py",
               "--submission", "/submission", "--x", "/input/x.npy",
               "--output", "/output/predictions.npy",
               "--channels", str(contract["input_shape"][0]),
               "--time-points", str(contract["input_shape"][1]),
               "--outputs", str(contract["output_size"]), "--kind", "classification"]
    try:
        subprocess.run(command, check=True, timeout=1200,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for name, expected in expected_hashes.items():
        if digest(seed_dir / name) != expected:
            raise ValueError("staged model changed during private inference")
    return inspect_prediction(output / "predictions.npy", rows, contract["output_size"])


def _staged_seeds(artifacts: Path, root: Path, frozen: dict[str, str]) -> list[tuple[Path, dict]]:
    staged = []
    for seed in range(3):
        source = artifacts / "submission" / f"seed-{seed}"
        if source.is_symlink() or not source.is_dir():
            raise ValueError("required seed directory missing or linked")
        directory = root / f"seed-{seed}"
        directory.mkdir(mode=0o755)
        hashes = {}
        for name in REQUIRED:
            key = f"submission/seed-{seed}/{name}"
            actual = copy_verified_required_file(source / name, directory / name, LIMITS[name])
            if actual != frozen[key]:
                raise ValueError("staged model differs from frozen submission")
            hashes[name] = actual
        staged.append((directory, hashes))
    return staged


def _standard(data: Path, root: Path, contract: dict, rows: int,
              staged: list[tuple[Path, dict]], image: str) -> list[float]:
    data = data / "test"
    x = root / "x.npy"
    _stage_x_member(data / "test.npz", x, rows, contract["input_shape"])
    labels = _labels(np.load(data / "test-labels.npy", allow_pickle=False), rows,
                     contract["output_size"], contract["metric_profile"])
    scores = []
    for seed, (directory, hashes) in enumerate(staged):
        output = root / f"out-{seed}"
        predictions = _infer(directory, x, output, contract, image, rows, hashes)
        scores.append(balanced_accuracy(labels, predictions, contract["output_size"],
                                        contract["metric_profile"]))
        shutil.rmtree(output)
    return scores


def _sleep(data: Path, root: Path, contract: dict, binding: dict,
           staged: list[tuple[Path, dict]], image: str) -> list[float]:
    data = data / "test"
    manifest = _json(data / "shards.json", max_bytes=1_000_000)
    pairs = manifest.get("ordered_pairs")
    if (manifest.get("schema") != "bpb-eeg-sharded-test-manifest/1" or
            not isinstance(pairs, list) or len(pairs) != binding.get("shard_pairs") or
            sum(pair.get("samples", 0) for pair in pairs if isinstance(pair, dict)) != binding["test_samples"] or
            manifest.get("source_complete_sha256") != binding.get("source_complete_sha256")):
        raise ValueError("Sleep-EDF shard manifest differs from binding")
    seen = set()
    confusion = [np.zeros((contract["output_size"], contract["output_size"]), dtype=np.int64)
                 for _ in staged]
    pending_x: list[np.ndarray] = []
    pending_y: list[np.ndarray] = []

    def flush() -> None:
        if not pending_x:
            return
        x = root / "sleep-x.npy"
        labels = np.concatenate(pending_y)
        np.save(x, np.concatenate(pending_x), allow_pickle=False)
        x.chmod(0o444)
        try:
            for seed, (directory, hashes) in enumerate(staged):
                output = root / f"sleep-out-{seed}"
                prediction = _infer(directory, x, output, contract, image, len(labels), hashes)
                confusion[seed] += _confusion(labels, prediction, contract["output_size"])
                shutil.rmtree(output)
        finally:
            x.unlink(missing_ok=True)
            pending_x.clear()
            pending_y.clear()

    with tarfile.open(data / "test-shards.tar", "r|") as archive:
        for pair in pairs:
            if not isinstance(pair, dict) or type(pair.get("samples")) is not int or not 0 < pair["samples"] <= 64:
                raise ValueError("invalid Sleep-EDF shard row count")
            x_name, y_name = pair.get("x"), pair.get("y")
            if not all(isinstance(name, str) and name.startswith("shard-") and "/" not in name
                       for name in (x_name, y_name)) or x_name in seen or y_name in seen or x_name == y_name:
                raise ValueError("invalid or duplicate Sleep-EDF shard names")
            if not x_name.endswith(".npz") or y_name != x_name[:-4] + "-labels.npy":
                raise ValueError("Sleep-EDF shard pair naming mismatch")
            seen.update((x_name, y_name))
            chunk = root / "sleep-shard"
            chunk.mkdir()
            try:
                for name, field in ((x_name, "x_sha256"), (y_name, "y_sha256")):
                    member = archive.next()
                    if member is None or member.name != "test/" + name or not member.isfile() or not _sha(pair.get(field)):
                        raise ValueError("Sleep-EDF tar order or member differs from manifest")
                    if not 0 < member.size <= 64 * math.prod(contract["input_shape"]) * 8 + 1_000_000:
                        raise ValueError("Sleep-EDF shard member is oversized")
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("Sleep-EDF tar member could not be read")
                    path = chunk / name
                    with path.open("wb") as output:
                        shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                    if digest(path) != pair[field]:
                        raise ValueError("Sleep-EDF shard hash mismatch")
                x = chunk / "x.npy"
                _stage_x_member(chunk / x_name, x, pair["samples"], contract["input_shape"])
                labels = _labels(np.load(chunk / y_name, allow_pickle=False), pair["samples"],
                                 contract["output_size"], contract["metric_profile"],
                                 require_complete=False)
                pending_x.append(np.array(np.load(x, mmap_mode="r", allow_pickle=False), copy=True))
                pending_y.append(labels)
            finally:
                shutil.rmtree(chunk)
            if len(pending_x) >= 32:
                flush()
        if archive.next() is not None:
            raise ValueError("Sleep-EDF tar contains extra members")
        flush()
    return [_score_confusion(table, contract["metric_profile"]) for table in confusion]


def score_private(task: Path, artifacts: Path, data: Path, frozen_path: Path,
                  report_path: Path | None = None) -> dict:
    strict_contract = _json(task / "contract.json")
    contract = read_contract(task)
    if contract != strict_contract:
        raise ValueError("task contract changed during private scoring setup")
    frozen = _json(frozen_path)
    version = _task_version(task)
    hashes = verify_frozen(artifacts, frozen, contract["task_id"], version)
    lock, records, binding = verify_packet(task, data, contract)
    image = os.environ.get("BPB_INFERENCE_IMAGE") or os.environ.get("BPB_EEG_IMAGE")
    if not valid_image_reference(image):
        raise ValueError("an immutable Docker inference image is required")
    with tempfile.TemporaryDirectory(prefix="bpb-eeg-private-") as temporary:
        root = Path(temporary)
        staged = _staged_seeds(artifacts, root, hashes)
        if contract["task_id"] == SLEEP_TASK:
            scores = _sleep(data, root, contract, binding, staged, image)
        else:
            scores = _standard(data, root, contract, binding["test_samples"], staged, image)
        for directory, file_hashes in staged:
            if any(digest(directory / name) != expected for name, expected in file_hashes.items()):
                raise ValueError("staged model changed after private scoring")
    verify_frozen(artifacts, frozen, contract["task_id"], version)
    for name, entry in records.items():
        if _regular(data / "test" / name) != entry["bytes"] or digest(data / "test" / name) != entry["sha256"]:
            raise ValueError("private evaluator packet changed during scoring")
    report = {"schema": "bpb-eeg-independent-private-score/1",
              "evaluation_scope": "independent-evaluator-test; not official leaderboard equivalence",
              "task_id": contract["task_id"], "source_task_id": contract["source_task_id"],
              "source_task_version": contract["source_task_version"],
              "source_task_spec_sha256": contract["source_task_spec_sha256"],
              "evaluator_repo_id": lock["repo_id"], "evaluator_revision": lock["revision"],
              "evaluator_file_sha256": {name: entry["sha256"] for name, entry in records.items()},
              "metric_profile": contract["metric_profile"], "test_samples": binding["test_samples"],
              "seed_scores": scores, "balanced_accuracy": float(np.mean(scores)),
              "frozen_submission_sha256": hashes, "image": image}
    destination = report_path or Path.cwd() / "eeg-private-test.json"
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(report, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    return {"balanced_accuracy": report["balanced_accuracy"], "seeds": 3,
            "test_samples": binding["test_samples"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--frozen", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    result = score_private(Path(args.task).resolve(), Path(args.artifacts).absolute(),
                           Path(args.data).absolute(), Path(args.frozen).absolute(),
                           Path(args.report).absolute() if args.report else None)
    print(">>>>> BPB_SCORES")
    print(json.dumps(result, sort_keys=True))
    print("<<<<< BPB_SCORES")


if __name__ == "__main__":
    main()
