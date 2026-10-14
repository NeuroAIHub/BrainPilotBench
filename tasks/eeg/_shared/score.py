"""Trusted public-validation scorer for frozen EEG task packages.

Only x enters the submitted-program container. Validation labels remain in
this process. This does not run private Test or confer scientific acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile

import numpy as np

REQUIRED = ("model.py", "config.json", "weights.safetensors")
IMAGE_RE = re.compile(r"(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64})\Z", re.IGNORECASE)


def valid_image_reference(image: str | None) -> bool:
    return isinstance(image, str) and IMAGE_RE.fullmatch(image) is not None


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cache_root() -> Path:
    explicit = os.environ.get("BPB_CACHE_ROOT")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "brainpilot-bench"


def read_contract(task: Path) -> dict:
    contract = json.loads((task / "contract.json").read_text(encoding="utf-8"))
    if (contract.get("kind") != "classification" or
            contract.get("primary_metric") != "balanced_accuracy" or
            contract.get("direction") != "maximize" or
            contract.get("metric_profile") not in
            ("native-balanced-accuracy-complete-classes", "native-typing-sparse-macro-torchmetrics-1.9")):
        raise ValueError("unsupported public-validation metric contract")
    shape = contract.get("input_shape")
    if (not isinstance(shape, list) or len(shape) != 2 or
            any(type(x) is not int or x <= 0 for x in shape) or
            type(contract.get("output_size")) is not int or contract["output_size"] < 2 or
            type(contract.get("valid_samples")) is not int or contract["valid_samples"] <= 0):
        raise ValueError("invalid frozen input/output dimensions")
    if (contract.get("max_parameters") != 10_000_000 or
            contract.get("max_numeric_state_elements") != 10_000_000):
        raise ValueError("unsupported model budget")
    return contract


def validation_file(contract: dict) -> Path:
    expected = contract["data_files"]["val.npz"]
    direct = os.environ.get("BPB_EEG_PUBLIC_DATA_DIR")
    path = Path(direct) / "val.npz" if direct else cache_root() / expected["sha256"] / "data"
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["bytes"]:
        raise ValueError("frozen public validation file is missing or unsafe")
    if digest(path) != expected["sha256"]:
        raise ValueError("frozen public validation SHA-256 mismatch")
    return path


def stage_x_and_y(package: Path, destination: Path, contract: dict):
    """Expand one hash-bound NPZ member to disk for bounded mmap inference."""
    with zipfile.ZipFile(package) as archive:
        if "x.npy" not in archive.namelist() or "y.npy" not in archive.namelist():
            raise ValueError("validation NPZ lacks x.npy or y.npy")
        expected_elements = contract["valid_samples"] * math.prod(contract["input_shape"])
        byte_count = archive.getinfo("x.npy").file_size
        if not expected_elements * 4 <= byte_count <= expected_elements * 8 + 4096:
            raise ValueError("validation x member has implausible uncompressed size")
        with archive.open("x.npy") as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    x = np.load(destination, mmap_mode="r", allow_pickle=False)
    if (x.shape != (contract["valid_samples"], *contract["input_shape"]) or
            x.dtype not in (np.dtype("float32"), np.dtype("float64"))):
        raise ValueError("validation x shape/dtype differs from the frozen task")
    with np.load(package, allow_pickle=False) as arrays:
        y = arrays["y"]
    if (y.shape != (contract["valid_samples"],) or y.dtype.kind not in "iu" or
            not np.isin(y, np.arange(contract["output_size"])).all()):
        raise ValueError("validation labels differ from the frozen class contract")
    if contract["metric_profile"] == "native-balanced-accuracy-complete-classes":
        if set(np.unique(y).tolist()) != set(range(contract["output_size"])):
            raise ValueError("native full-class metric requires all classes in validation labels")
    return y.astype(np.int64, copy=False)


def inspect_prediction(path: Path, rows: int, classes: int):
    if path.is_symlink() or not path.is_file():
        raise ValueError("inference produced no regular predictions.npy")
    if not 0 < path.stat().st_size <= rows * classes * 8 + 4096:
        raise ValueError("predictions.npy size is out of range")
    with path.open("rb") as source:
        version = np.lib.format.read_magic(source)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(source)
        elif version == (2, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(source)
        else:
            raise ValueError("unsupported prediction array version")
        if (shape != (rows, classes) or fortran or
                dtype not in (np.dtype("float32"), np.dtype("float64")) or
                path.stat().st_size != source.tell() + rows * classes * dtype.itemsize):
            raise ValueError("prediction header contradicts the frozen task")
    predictions = np.load(path, mmap_mode="r", allow_pickle=False)
    if (not np.isfinite(predictions).all() or
            (predictions < -1e-6).any() or (predictions > 1 + 1e-6).any() or
            not np.allclose(predictions.sum(1), 1.0, atol=1e-4, rtol=1e-4)):
        raise ValueError("invalid class probabilities")
    return np.argmax(predictions, axis=1)


def copy_verified_required_file(source: Path, destination: Path, limit: int) -> str:
    """Bind the bytes actually mounted for inference to the source artifact."""
    if (source.is_symlink() or not source.is_file() or
            not 0 < source.stat().st_size <= limit):
        raise ValueError(f"invalid required submission file: {source.name}")
    source_sha = digest(source)
    shutil.copyfile(source, destination)
    staged_sha = digest(destination)
    if staged_sha != source_sha:
        raise ValueError(f"staged submission differs from source: {source.name}")
    destination.chmod(0o444)
    return staged_sha


def balanced_accuracy(labels, predictions, classes: int, profile: str) -> float:
    confusion = np.zeros((classes, classes), dtype=np.int64)
    np.add.at(confusion, (labels, predictions), 1)
    true_counts = confusion.sum(axis=1)
    recall = np.divide(np.diag(confusion), true_counts,
                       out=np.zeros(classes, dtype=np.float64), where=true_counts > 0)
    if profile == "native-balanced-accuracy-complete-classes":
        if (true_counts == 0).any():
            raise ValueError("native score has an absent true class")
        return float(recall.mean())
    if profile == "native-typing-sparse-macro-torchmetrics-1.9":
        predicted_counts = confusion.sum(axis=0)
        included = (true_counts + predicted_counts - np.diag(confusion)) > 0
        if not included.any():
            raise ValueError("typing score has no observed or predicted class")
        return float(np.sum(recall[included] / int(included.sum())))
    raise ValueError("unknown metric profile")


def score(task: Path, raw_artifacts: Path) -> dict:
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1":
        raise ValueError("this task provides public validation only, not private Test scoring")
    if raw_artifacts.is_symlink() or (raw_artifacts / "submission").is_symlink():
        raise ValueError("submitted artifact directories cannot be symbolic links")
    artifacts = raw_artifacts.resolve(strict=True)
    contract = read_contract(task)
    public_validation = validation_file(contract)
    image = os.environ.get("BPB_INFERENCE_IMAGE") or os.environ.get("BPB_EEG_IMAGE")
    if not valid_image_reference(image):
        raise ValueError("an immutable Docker inference image is required")
    execution_hashes = {}
    scores = []
    with tempfile.TemporaryDirectory(prefix="bpb-eeg-public-") as temporary:
        root = Path(temporary)
        input_array = root / "x.npy"
        labels = stage_x_and_y(public_validation, input_array, contract)
        for seed in range(3):
            source = artifacts / "submission" / f"seed-{seed}"
            if source.is_symlink() or not source.is_dir():
                raise ValueError(f"missing required seed-{seed} submission")
            staged = root / f"seed-{seed}"
            output = root / f"out-{seed}"
            staged.mkdir(mode=0o755)
            output.mkdir(mode=0o777)
            output.chmod(0o777)
            execution_hashes[str(seed)] = {}
            for name, limit in (("model.py", 1_000_000), ("config.json", 256_000),
                                ("weights.safetensors", 100_000_000)):
                file = source / name
                execution_hashes[str(seed)][name] = copy_verified_required_file(
                    file, staged / name, limit)
            container = "bpb-eeg-" + uuid.uuid4().hex
            command = ["docker", "run", "--rm", "--name", container, "--network", "none",
                       "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                       "--cpus", "2", "--memory", "4g", "--pids-limit", "128",
                       "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
                       "-v", f"{staged}:/submission:ro", "-v", f"{input_array}:/input/x.npy:ro",
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
            for name, staged_sha in execution_hashes[str(seed)].items():
                if digest(staged / name) != staged_sha or digest(source / name) != staged_sha:
                    raise ValueError(f"seed-{seed}/{name} changed during isolated inference")
            predictions = inspect_prediction(output / "predictions.npy", len(labels), contract["output_size"])
            scores.append(balanced_accuracy(labels, predictions, contract["output_size"],
                                            contract["metric_profile"]))
    report = {"scope": "public-validation-only", "private_test": False,
              "task_id": contract["task_id"], "source_task_id": contract["source_task_id"],
              "source_task_version": contract["source_task_version"],
              "source_task_spec_sha256": contract["source_task_spec_sha256"],
              "validation_sha256": contract["data_files"]["val.npz"]["sha256"],
              "metric_profile": contract["metric_profile"], "seed_scores": scores,
              "balanced_accuracy": float(np.mean(scores)),
              "staged_executed_submission_sha256": execution_hashes,
              "image": image}
    report_path = artifacts.parent / "eeg-public-validation.json"
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"balanced_accuracy": report["balanced_accuracy"],
            "seeds": 3, "validation_samples": contract["valid_samples"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--artifacts", required=True)
    args = parser.parse_args()
    metrics = score(Path(args.task).resolve(), Path(args.artifacts).absolute())
    print(">>>>> BPB_SCORES")
    print(json.dumps(metrics, sort_keys=True))
    print("<<<<< BPB_SCORES")


if __name__ == "__main__":
    main()
