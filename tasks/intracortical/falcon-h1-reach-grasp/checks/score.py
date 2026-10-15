"""Trusted H1 scorer: one causal bin at a time; labels never enter Docker."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import select
import signal
import shutil
import stat
import struct
import subprocess
import tempfile
import time
import uuid

import numpy as np

PROFILE = "bpb-falcon-public-derived-cross-session-zs-v1"
SCHEMA = "bpb-h1-evaluation-data/1"
REQUIRED = ("model.py", "config.json", "weights.safetensors")
ARRAYS = ("x.npy", "y.npy", "mask.npy", "trial_start.npy")
IMAGE_RE = re.compile(r"(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64})\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_REPLY = 4096
MAX_MESSAGE = 16384
VALID_DATES = ("19250120",)
TEST_DATES = ("19250126", "19250127", "19250129", "19250202", "19250203", "19250206", "19250209")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_unique(path: Path, *, max_bytes: int | None = None) -> os.stat_result:
    if path.is_symlink():
        raise ValueError(f"symlink rejected: {path}")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0:
        raise ValueError(f"not a unique regular file: {path}")
    if max_bytes is not None and info.st_size > max_bytes:
        raise ValueError(f"file exceeds limit: {path}")
    return info


def confined(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("invalid manifest relative path")
    parts = PurePosixPath(relative).parts
    if (relative.startswith("/") or PurePosixPath(relative).as_posix() != relative or
            any(p in ("", ".", "..") for p in parts)):
        raise ValueError("manifest path escapes root")
    current = root
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise ValueError("unsafe manifest path component")
    result = current / parts[-1]
    if result.is_symlink() or not result.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("manifest path escapes root")
    return result


def bound_file(path: Path, record: dict, *, max_bytes: int):
    if (not isinstance(record, dict) or type(record.get("bytes")) is not int or
            not isinstance(record.get("sha256"), str) or
            SHA_RE.fullmatch(record["sha256"]) is None):
        raise ValueError("invalid frozen file binding")
    info = regular_unique(path, max_bytes=max_bytes)
    if info.st_size != record["bytes"] or sha256(path) != record["sha256"]:
        raise ValueError(f"frozen file bytes/hash mismatch: {path}")


def strict_json(data: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def no_constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    return json.loads(data, object_pairs_hook=unique, parse_constant=no_constant)


def finite_json(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite_json(item) for item in value)
    if isinstance(value, dict):
        return all(finite_json(item) for item in value.values())
    return value is None or isinstance(value, (str, int, bool))


def validate_staged_config_and_state(staged: Path):
    """Inspect submitted bytes on trusted host without importing submitted code."""
    config = strict_json((staged / "config.json").read_bytes())
    if not isinstance(config, dict) or not finite_json(config):
        raise ValueError("config must be a finite JSON object")
    content = (staged / "weights.safetensors").read_bytes()
    if len(content) < 10:
        raise ValueError("truncated safetensors state")
    header_size = struct.unpack_from("<Q", content)[0]
    if header_size <= 0 or header_size > 1_000_000 or header_size + 8 >= len(content):
        raise ValueError("invalid safetensors header size")
    header = strict_json(content[8:8 + header_size])
    if not isinstance(header, dict) or not header:
        raise ValueError("empty safetensors state")
    data = memoryview(content)[8 + header_size:]
    widths = {"F16": 2, "BF16": 2, "F32": 4, "F64": 8,
              "I8": 1, "U8": 1, "I16": 2, "U16": 2,
              "I32": 4, "U32": 4, "I64": 8, "U64": 8, "BOOL": 1}
    float_formats = {"F16": "<f2", "F32": "<f4", "F64": "<f8"}
    spans = []
    elements = 0
    for name, record in header.items():
        if name == "__metadata__":
            if not isinstance(record, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                   for k, v in record.items()):
                raise ValueError("invalid safetensors metadata")
            continue
        if (not isinstance(record, dict) or set(record) != {"dtype", "shape", "data_offsets"} or
                not isinstance(record["dtype"], str) or record["dtype"] not in widths or
                not isinstance(record["shape"], list) or
                any(type(d) is not int or d < 0 for d in record["shape"])):
            raise ValueError("invalid numeric state entry")
        shape = record["shape"]
        count = math.prod(shape)
        elements += count
        if elements > 10_000_000:
            raise ValueError("persisted numeric state exceeds 10M elements")
        offsets = record["data_offsets"]
        if (not isinstance(offsets, list) or len(offsets) != 2 or
                any(type(offset) is not int for offset in offsets)):
            raise ValueError("invalid numeric state offsets")
        start, end = offsets
        if start < 0 or end < start or end > len(data) or end - start != count * widths[record["dtype"]]:
            raise ValueError("numeric state length contradicts shape")
        spans.append((start, end))
        values = data[start:end]
        if record["dtype"] in float_formats and not np.isfinite(
                np.frombuffer(values, dtype=float_formats[record["dtype"]])).all():
            raise ValueError("nonfinite persisted numeric state")
        if record["dtype"] == "BF16" and np.any((np.frombuffer(values, dtype="<u2") & 0x7f80) == 0x7f80):
            raise ValueError("nonfinite persisted numeric state")
        if record["dtype"] == "BOOL" and any(byte not in (0, 1) for byte in values):
            raise ValueError("invalid boolean persisted state")
    if not spans or sorted(spans)[0][0] != 0 or sorted(spans)[-1][1] != len(data):
        raise ValueError("safetensors data span mismatch")
    ordered = sorted(spans)
    if any(a[1] != b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("overlapping or gapped safetensors entries")


def read_protocol(task: Path):
    protocol = json.loads((task / "protocol.json").read_text(encoding="utf-8"))
    if (protocol.get("schema") != "bpb-invasive-protocol/1" or
            protocol.get("profile") != PROFILE or protocol.get("task_id") != "falcon-h1-reach-grasp" or
            protocol.get("input", {}).get("channels") != 176 or
            protocol.get("input", {}).get("bin_ms") != 20 or
            protocol.get("output", {}).get("dimensions") != 7 or
            protocol.get("metric", {}).get("id") != "R2_variance_weighted" or
            tuple(protocol.get("split", {}).get("valid_dates", ())) != VALID_DATES or
            tuple(protocol.get("split", {}).get("test_dates", ())) != TEST_DATES):
        raise ValueError("unsupported H1 protocol")
    return protocol


def expected_manifest(task: Path, role: str) -> dict:
    contract = json.loads((task / "contract.json").read_text(encoding="utf-8"))
    if (contract.get("schema") != "bpb-h1-contract/1" or
            contract.get("task_version") != "0.1-public-validation-stream" or
            contract.get("science_profile") != PROFILE or
            contract.get("task_id") != "falcon-h1-reach-grasp"):
        raise ValueError("missing or unsupported tracked H1 contract")
    binding = contract.get("evaluation_manifests", {}).get(role)
    if not isinstance(binding, dict):
        raise ValueError(f"tracked contract does not bind {role} manifest")
    return binding


def load_manifest(task: Path, manifest_path: Path, role: str):
    bound_file(manifest_path, expected_manifest(task, role), max_bytes=2_000_000)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or manifest.get("profile") != PROFILE or
            manifest.get("role") != role or not isinstance(manifest.get("runs"), list)):
        raise ValueError("manifest schema/profile/role mismatch")
    runs = manifest["runs"]
    expected_dates = set(VALID_DATES if role == "valid" else TEST_DATES)
    expected_count = 2 if role == "valid" else 14
    if len(runs) != expected_count:
        raise ValueError("manifest run count differs from frozen protocol")
    seen_id, seen_path, dates = set(), set(), set()
    validated = []
    for index, run in enumerate(runs):
        if (not isinstance(run, dict) or run.get("role") != role or
                type(run.get("order")) is not int or run["order"] != index or
                not isinstance(run.get("id"), str) or not run["id"] or
                run["id"] in seen_id or run.get("session_id") not in expected_dates or
                set(run.get("files", {})) != set(ARRAYS)):
            raise ValueError("manifest run identity/order/role differs from contract")
        seen_id.add(run["id"])
        dates.add(run["session_id"])
        files = {}
        for name, shape_tail, dtype, max_bytes in (
                ("x.npy", [176], "uint8", 1_000_000_000),
                ("y.npy", [7], "float64", 1_000_000_000),
                ("mask.npy", [], "bool", 100_000_000),
                ("trial_start.npy", [], "bool", 100_000_000)):
            entry = run["files"][name]
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("invalid array entry")
            path = confined(manifest_path.parent, entry["path"])
            if path in seen_path:
                raise ValueError("duplicate array path")
            seen_path.add(path)
            bound_file(path, entry, max_bytes=max_bytes)
            arr = np.load(path, mmap_mode="r", allow_pickle=False)
            expected_shape = [entry["shape"][0], *shape_tail] if isinstance(entry.get("shape"), list) and entry["shape"] else None
            if (expected_shape is None or list(arr.shape) != expected_shape or
                    entry["shape"] != expected_shape or arr.dtype != np.dtype(dtype) or
                    entry.get("dtype") != dtype or arr.shape[0] <= 0):
                raise ValueError("array shape/dtype contradicts manifest")
            files[name] = arr
        length = len(files["x.npy"])
        if any(len(a) != length for a in files.values()):
            raise ValueError("run array lengths differ")
        if (not np.isfinite(files["y.npy"]).all() or
                not np.any(files["mask.npy"])):
            raise ValueError("invalid labels or empty scoring mask")
        validated.append((run, files))
    if dates != expected_dates:
        raise ValueError("manifest dates incomplete")
    return validated


def stage_submission(artifacts: Path, target: Path, frozen_manifest: Path | None, *, test: bool):
    if artifacts.is_symlink() or (artifacts / "submission").is_symlink():
        raise ValueError("submission directory symlink rejected")
    source = artifacts / "submission"
    if not source.is_dir():
        raise ValueError("submission directory missing")
    frozen = None
    if test:
        regular_unique(frozen_manifest, max_bytes=100_000)
        frozen = json.loads(frozen_manifest.read_text(encoding="utf-8"))
        if (frozen.get("schema") != "bpb-h1-frozen-artifact/1" or
                frozen.get("profile") != PROFILE or set(frozen.get("files", {})) != set(REQUIRED)):
            raise ValueError("invalid owner-frozen submission manifest")
    target.mkdir(mode=0o755)
    hashes = {}
    for name, limit in (("model.py", 1_000_000), ("config.json", 256_000),
                        ("weights.safetensors", 100_000_000)):
        original = source / name
        initial = regular_unique(original, max_bytes=limit)
        staged = target / name
        descriptor = os.open(original, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as inp, staged.open("xb") as out:
            opened = os.fstat(inp.fileno())
            if (opened.st_ino != initial.st_ino or opened.st_dev != initial.st_dev or
                    opened.st_nlink != 1 or not stat.S_ISREG(opened.st_mode)):
                raise ValueError("submission changed before staging")
            shutil.copyfileobj(inp, out, length=1024 * 1024)
            after = os.fstat(inp.fileno())
            if after.st_size != initial.st_size or after.st_mtime_ns != initial.st_mtime_ns:
                raise ValueError("submission changed during staging")
        before = sha256(staged)
        if frozen and frozen["files"].get(name) != {"sha256": before, "bytes": initial.st_size}:
            raise ValueError("submission differs from owner-frozen artifact")
        if sha256(original) != before or regular_unique(original, max_bytes=limit).st_ino != initial.st_ino:
            raise ValueError("submission changed during staging")
        staged.chmod(0o444)
        hashes[name] = before
    validate_staged_config_and_state(target)
    return hashes


def date_score(target: np.ndarray, prediction: np.ndarray):
    if target.shape != prediction.shape or target.ndim != 2 or target.shape[1] != 7 or len(target) < 2:
        raise ValueError("invalid scored date shape")
    mean = target.mean(axis=0)
    denominator = np.square(target - mean).sum(axis=0)
    numerator = np.square(target - prediction).sum(axis=0)
    varying = denominator > 0
    total = float(denominator[varying].sum())
    if total <= 0 or not math.isfinite(total):
        raise ValueError("date has no target variance")
    # This is sklearn's variance_weighted behavior: constant dimensions carry
    # zero weight even if the submission predicts them badly.
    result = 1.0 - float(numerator[varying].sum()) / total
    if not math.isfinite(result):
        raise ValueError("nonfinite date R2")
    return result


class LockedDocker:
    def __init__(self, image: str, staged: Path, worker: Path, *, total_seconds=600, step_seconds=30):
        if IMAGE_RE.fullmatch(image) is None:
            raise ValueError("Docker image must be an immutable digest or image ID")
        self.name = "bpb-h1-" + uuid.uuid4().hex
        self.deadline = time.monotonic() + total_seconds
        self.step_seconds = step_seconds
        self.buffer = bytearray()
        command = ["docker", "run", "--rm", "-i", "--name", self.name,
                   "--network", "none", "--read-only", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges", "--cpus", "2", "--memory", "4g",
                   "--pids-limit", "128", "--user", "65534:65534",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
                   "--mount", f"type=bind,src={staged},dst=/submission,readonly",
                   "--mount", f"type=bind,src={worker},dst=/worker.py,readonly",
                   image, "python", "-u", "/worker.py"]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def exchange(self, kind: str, **fields):
        nonce = uuid.uuid4().hex
        packet = json.dumps({"nonce": nonce, "kind": kind, **fields}, allow_nan=False,
                            separators=(",", ":")).encode() + b"\n"
        if len(packet) > MAX_MESSAGE or self.buffer:
            raise ValueError("oversized message or unsolicited worker output")
        if select.select([self.process.stdout], [], [], 0)[0]:
            raise ValueError("H1 worker emitted output before receiving this bin")
        deadline = min(self.deadline, time.monotonic() + self.step_seconds)
        written = 0
        while written < len(packet):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.process.poll() is not None:
                raise TimeoutError("H1 worker failed before request was sent")
            _, writable, _ = select.select([], [self.process.stdin], [], remaining)
            if writable:
                written += os.write(self.process.stdin.fileno(), packet[written:])
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("H1 worker prediction timeout")
            readable, _, _ = select.select([self.process.stdout], [], [], remaining)
            if readable:
                chunk = os.read(self.process.stdout.fileno(), MAX_REPLY + 1 - len(self.buffer))
                if not chunk:
                    raise ValueError("H1 worker closed protocol output")
                self.buffer.extend(chunk)
                if len(self.buffer) > MAX_REPLY:
                    raise ValueError("H1 worker protocol line too long")
        line, _, leftover = self.buffer.partition(b"\n")
        self.buffer = bytearray(leftover)
        if self.buffer:
            raise ValueError("H1 worker sent unsolicited future output")
        message = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite reply")))
        if not isinstance(message, dict) or message.get("nonce") != nonce or message.get("kind") != kind:
            raise ValueError("H1 worker nonce/kind mismatch")
        if kind == "step":
            values = message.get("prediction")
            if (set(message) != {"nonce", "kind", "prediction"} or
                    not isinstance(values, list) or len(values) != 7 or
                    any(type(v) not in (float, int) or not math.isfinite(v) for v in values)):
                raise ValueError("invalid H1 worker prediction")
            return np.asarray(values, dtype=np.float64)
        if set(message) != {"nonce", "kind"}:
            raise ValueError("invalid H1 worker acknowledgment")
        return None

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=15)
        finally:
            self.process.stdin.close()
            self.process.stdout.close()
            subprocess.run(["docker", "rm", "-f", self.name], check=False, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def score(task: Path, artifacts: Path, manifest: Path, image: str, *, role="valid",
          owner_test=False, frozen_artifact_manifest: Path | None = None):
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1":
        raise ValueError("this derived H1 profile is not official FALCON scoring")
    read_protocol(task)
    if role not in ("valid", "test"):
        raise ValueError("score role must be valid or test")
    if role == "test" and (not owner_test or frozen_artifact_manifest is None or
                           "/evaluator/test/" not in str(manifest.resolve())):
        raise ValueError("Test requires owner flag, frozen artifact, and explicit evaluator path")
    if role == "valid" and (owner_test or frozen_artifact_manifest is not None):
        raise ValueError("Valid scoring cannot use Test authority")
    runs = load_manifest(task, manifest, role)
    data_hashes = [(confined(manifest.parent, entry["path"]), entry["sha256"])
                   for run, _ in runs for entry in run["files"].values()]
    manifest_hash = sha256(manifest)
    worker = Path(__file__).with_name("worker.py")
    bound_file(worker, {"sha256": sha256(worker), "bytes": worker.stat().st_size}, max_bytes=100_000)
    with tempfile.TemporaryDirectory(prefix="bpb-h1-isolated-") as temp:
        temp_root = Path(temp)
        temp_root.chmod(0o755)
        staged = temp_root / "submission"
        hashes = stage_submission(artifacts, staged, frozen_artifact_manifest, test=role == "test")
        grouped = defaultdict(lambda: {"y": [], "prediction": [], "timesteps": 0})
        for run, arrays in runs:
            # A fresh process per recording prevents module globals or unregistered
            # tensors from carrying hidden state across files.
            docker = LockedDocker(image, staged, worker)
            try:
                docker.exchange("reset")
                predictions = np.empty((len(arrays["x.npy"]), 7), dtype=np.float64)
                for index in range(len(predictions)):
                    x = np.asarray(arrays["x.npy"][index], dtype=np.float32)
                    if x.shape != (176,) or not np.isfinite(x).all():
                        raise ValueError("invalid H1 input bin")
                    predictions[index] = docker.exchange(
                        "step", x=x.tolist(), trial_start=bool(arrays["trial_start.npy"][index]))
                selected = np.asarray(arrays["mask.npy"], dtype=np.bool_)
                entry = grouped[run["session_id"]]
                entry["y"].append(np.asarray(arrays["y.npy"][selected], dtype=np.float64))
                entry["prediction"].append(predictions[selected])
                entry["timesteps"] += int(selected.sum())
                docker.exchange("end")
            finally:
                docker.close()
        for name, expected in hashes.items():
            if sha256(staged / name) != expected or sha256(artifacts / "submission" / name) != expected:
                raise ValueError("submission changed during isolated scoring")
        if sha256(manifest) != manifest_hash or any(sha256(path) != expected for path, expected in data_hashes):
            raise ValueError("evaluation data changed during isolated scoring")
    by_date = {date: date_score(np.concatenate(entry["y"]), np.concatenate(entry["prediction"]))
               for date, entry in sorted(grouped.items())}
    scores = list(by_date.values())
    report = {"schema": "bpb-h1-score-report/1", "profile": PROFILE,
              "evaluation_profile": ("bpb-h1-public-validation-stream-v1" if role == "valid"
                                     else "bpb-h1-owner-independent-test-v1"),
              "scope": "public-validation-only" if role == "valid" else "independent-evaluator-test",
              "official_falcon": False, "role": role, "r2_variance_weighted": float(np.mean(scores)),
              "date_population_std": float(np.std(scores, ddof=0)), "date_scores": by_date,
              "date_timesteps": {date: entry["timesteps"] for date, entry in sorted(grouped.items())},
              "submission_sha256": hashes, "manifest_sha256": manifest_hash, "image": image}
    return report


def main():
    # Normal operator cancellation still reaches the per-container finally block.
    # SIGKILL cannot be caught; the Valid run budgets remain below the outer CLI timeout.
    def stop_scoring(signum, _frame):
        raise KeyboardInterrupt(f"scoring interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, stop_scoring)
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--data-manifest", required=True, type=Path)
    parser.add_argument("--image", default=os.environ.get("BPB_INFERENCE_IMAGE") or os.environ.get("BPB_H1_INFERENCE_IMAGE"))
    parser.add_argument("--role", choices=("valid", "test"), default="valid")
    parser.add_argument("--owner-test", action="store_true")
    parser.add_argument("--frozen-artifact-manifest", type=Path)
    args = parser.parse_args()
    if not args.image:
        parser.error("immutable Docker image or image ID required")
    report = score(args.task, args.artifacts, args.data_manifest, args.image,
                   role=args.role, owner_test=args.owner_test,
                   frozen_artifact_manifest=args.frozen_artifact_manifest)
    if args.role == "valid":
        print(">>>>> BPB_SCORES")
        print(json.dumps({"R2_variance_weighted": report["r2_variance_weighted"],
                          "date_population_std": report["date_population_std"]}, allow_nan=False,
                         sort_keys=True))
        print("<<<<< BPB_SCORES")
        print(json.dumps(report, allow_nan=False, sort_keys=True), file=os.sys.stderr)
    else:
        print(json.dumps(report, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
