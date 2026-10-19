#!/usr/bin/env python3
"""Trusted private Test dispatch. Run only after a lock-verified data materialization.

The generic freeze binds every file in ``artifacts``. Task-specific receipts are
created from that verified tree for legacy owner Test scorers; no scientific
metric or split is implemented here. Submitted Python is executed only by the
existing scorers' isolated Docker workers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
START, END = ">>>>> BPB_SCORES", "<<<<< BPB_SCORES"
SHA = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64})\Z")
PROFILE_BCI = "bpb-bciciv4-offline-guarded-v1"
PROFILE_FALCON = "bpb-falcon-public-derived-cross-session-zs-v1"
MODEL_FILES = ("model.py", "config.json", "weights.safetensors")
FALCON = {
    "falcon-h2-handwriting": "h2",
    "falcon-m1-emg": "m1", "falcon-m2-finger-velocity": "m2",
    "falcon-b1-birdsong": "b1",
}
SUPPORTED = {
    "ieeg-finger-flexion-bciciv4": "ieeg/ieeg-finger-flexion-bciciv4",
    "ieeg-film-speech-music": "ieeg/ieeg-film-speech-music",
    **{name: f"intracortical/{name}" for name in FALCON},
    "brain-age-mri": "mri/brain-age-mri",
    "celegans-structure-function-divergence": "connectomics/celegans-structure-function-divergence",
}
PYTHON_ENV = {
    "ieeg-finger-flexion-bciciv4": "BPB_BCI_PYTHON",
    "ieeg-film-speech-music": "BPB_FILM_PYTHON",
    "falcon-h2-handwriting": "BPB_H2_PYTHON",
    "falcon-m1-emg": "BPB_M1_PYTHON",
    "falcon-m2-finger-velocity": "BPB_M2_PYTHON",
    "falcon-b1-birdsong": "BPB_B1_PYTHON",
    "brain-age-mri": "BPB_BRAIN_AGE_PYTHON",
    "celegans-structure-function-divergence": "BPB_PYTHON",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def strict_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def ordinary_file(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("artifact contains a link or special file")
    return info


def artifact_snapshot(artifacts: Path) -> dict[str, str]:
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise ValueError("artifacts must be an ordinary directory")
    files = {}
    for path in artifacts.rglob("*"):
        relative = path.relative_to(artifacts).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        ordinary_file(path)
        files[relative] = digest(path)
    if not files:
        raise ValueError("artifact tree is empty")
    return files


def verify_freeze(task_id: str, artifacts: Path, frozen: Path,
                  task_version: str | None = None) -> dict[str, str]:
    if frozen.is_symlink() or not frozen.is_file() or frozen.stat().st_size > 2_000_000:
        raise ValueError("invalid frozen receipt")
    receipt = strict_json(frozen)
    expected_keys = {"schema", "task_id", "files", "task_version"}
    if (not isinstance(receipt, dict) or set(receipt) != expected_keys
            or receipt["schema"] != "bpb-private-submission-freeze/1"
            or receipt["task_id"] != task_id or
            not isinstance(receipt["task_version"], str) or
            (task_version is not None and receipt["task_version"] != task_version) or
            not isinstance(receipt["files"], dict)
            or not receipt["files"] or any(not isinstance(name, str) or
            not isinstance(value, str) or SHA.fullmatch(value) is None
            for name, value in receipt["files"].items())):
        raise ValueError("frozen receipt schema, task, or file digests differ")
    if artifact_snapshot(artifacts) != receipt["files"]:
        raise ValueError("artifacts differ from the frozen submission")
    return receipt["files"]


def task_identity(task: Path) -> str:
    if task.is_symlink():
        raise ValueError("unknown task directory")
    task = task.resolve()
    if not (task / "task.yaml").is_file():
        raise ValueError("unknown task directory")
    ids = re.findall(r"(?m)^id: ([a-z0-9-]+)\s*$", (task / "task.yaml").read_text(encoding="utf-8"))
    eeg = (len(ids) == 1 and task.parent == ROOT / "tasks/eeg" and
           task.name == ids[0] and ids[0].startswith("eeg-") and
           (ROOT / "tasks/eeg/_shared/private_score.py").is_file())
    known = len(ids) == 1 and ids[0] in SUPPORTED and task == ROOT / "tasks" / SUPPORTED[ids[0]]
    if not (eeg or known):
        raise ValueError("private Test scoring is unsupported for this task")
    return ids[0]


def task_version(task: Path) -> str:
    values = re.findall(r'(?m)^version:\s*["\']?([^"\'\n]+)["\']?\s*$',
                        (task / "task.yaml").read_text(encoding="utf-8"))
    if len(values) != 1 or not values[0].strip():
        raise ValueError("task version is missing or ambiguous")
    return values[0].strip()


def legacy_receipt(task_id: str, artifacts: Path, hashes: dict[str, str]) -> dict:
    required = {f"submission/{name}" for name in MODEL_FILES}
    if not required.issubset(hashes):
        raise ValueError("submission model files are missing from the freeze")
    files = {name: {"sha256": hashes[f"submission/{name}"],
                    "bytes": ordinary_file(artifacts / "submission" / name).st_size}
             for name in MODEL_FILES}
    if task_id == "ieeg-finger-flexion-bciciv4":
        return {"schema": "bpb-bci-frozen-artifact/1", "profile": PROFILE_BCI, "files": files}
    name = FALCON[task_id]
    if name in ("h2", "b1"):
        return {"schema": f"bpb-{name}-frozen-artifact/1", "task_id": task_id,
                "profile": PROFILE_FALCON, "files": files}
    return {"schema": f"bpb-{name}-frozen-artifact/1", "profile": PROFILE_FALCON,
            "files": files}


def write_new_json(path: Path, payload: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(payload, output, allow_nan=False, sort_keys=True)
        output.write("\n")


def run_scorer(command: list[str], *, env: dict[str, str] | None = None,
               cwd: Path | None = None) -> str:
    # Raw stderr may contain hidden paths or task labels; do not forward it.
    result = subprocess.run(command, env=env, cwd=cwd, text=True, capture_output=True, timeout=14400,
                            check=False)
    if result.returncode != 0:
        raise RuntimeError(f"trusted task scorer exited {result.returncode}; private Test remains unscored")
    if len(result.stdout) > 2_000_000:
        raise ValueError("trusted scorer output is oversized")
    return result.stdout


def flat_metrics(report: dict, task_id: str) -> dict[str, float]:
    if task_id == "ieeg-finger-flexion-bciciv4":
        metrics = {"pearson_r": report["pearson_r"]}
    elif task_id == "ieeg-film-speech-music":
        metrics = {"balanced_accuracy": report["value"]}
    elif task_id in ("falcon-m1-emg", "falcon-m2-finger-velocity"):
        metrics = {"R2_variance_weighted": report["r2_variance_weighted"],
                   "date_population_std": report["date_population_std"]}
    elif task_id == "falcon-h2-handwriting":
        metrics = {"WER": report["metrics"]["WER"]["mean"],
                   "CER": report["metrics"]["CER"]["mean"]}
    elif task_id == "falcon-b1-birdsong":
        metrics = {"normalized_spectrogram_MSE": report["metrics"]["mean"],
                   "date_population_std": report["metrics"]["std_population"]}
    else:
        metrics = report
    if not isinstance(metrics, dict) or not metrics or any(
            not isinstance(key, str) or type(value) not in (float, int) or
            not math.isfinite(value) for key, value in metrics.items()):
        raise ValueError("trusted scorer did not return finite flat metrics")
    return metrics


def parse_sentinel(output: str) -> dict:
    lines = output.splitlines()
    if lines.count(START) != 1 or lines.count(END) != 1:
        raise ValueError("trusted scorer did not emit exactly one score block")
    first, last = lines.index(START), lines.index(END)
    if last != first + 2:
        raise ValueError("invalid trusted scorer score block")
    result = json.loads(lines[first + 1])
    return result


def evaluator_python(task_id: str) -> str:
    chosen = (os.environ.get("BPB_EVALUATOR_PYTHON") or
              os.environ.get(PYTHON_ENV.get(task_id, ""), "") or sys.executable)
    path = Path(chosen)
    if (not path.is_absolute() or not path.is_file() or
            not os.access(path, os.X_OK)):
        raise ValueError("trusted evaluator Python must be an executable absolute path")
    return str(path)


def verify_prepared_data(task: Path, data: Path) -> tuple[Path, dict]:
    spec = importlib.util.spec_from_file_location(
        "bpb_private_prepare_for_score", Path(__file__).with_name("prepare.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_prepared(task, data)


def verify_materialization_data(task: Path, data: Path) -> dict:
    spec = importlib.util.spec_from_file_location(
        "bpb_private_prepare_for_materialization", Path(__file__).with_name("prepare.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_materialization(task, data)


def score(task: Path, artifacts: Path, data: Path, frozen: Path) -> dict[str, float]:
    task_id = task_identity(task)
    task = task.resolve()
    if artifacts.is_symlink():
        raise ValueError("artifacts root must not be a symlink")
    artifacts = artifacts.resolve()
    if data.name != "evaluator" or data.is_symlink() or not data.is_dir():
        raise ValueError("private data root must be an ordinary evaluator directory")
    data = data.resolve()
    if data == artifacts or data.is_relative_to(artifacts) or artifacts.is_relative_to(data):
        raise ValueError("private data and artifacts must be separate")
    materialized_sources = verify_materialization_data(task, data)
    if frozen.is_symlink():
        raise ValueError("frozen receipt must not be a symlink")
    frozen = frozen.resolve()
    hashes = verify_freeze(task_id, artifacts, frozen, task_version(task))
    image = os.environ.get("BPB_INFERENCE_IMAGE", "")
    if IMAGE.fullmatch(image) is None:
        raise ValueError("BPB_INFERENCE_IMAGE must be an immutable digest or image ID")
    python = evaluator_python(task_id)
    prepared_receipt = None
    if task_id in ("brain-age-mri", "celegans-structure-function-divergence"):
        _prepared, prepared_receipt = verify_prepared_data(task, data)
    with tempfile.TemporaryDirectory(prefix="bpb-private-score-") as temporary:
        owner = Path(temporary)
        if task_id.startswith("eeg-"):
            output = run_scorer([python, str(ROOT / "tasks/eeg/_shared/private_score.py"),
                                 "--task", str(task), "--artifacts", str(artifacts),
                                 "--data", str(data), "--frozen", str(frozen)], cwd=owner)
            metrics = flat_metrics(parse_sentinel(output), task_id)
        elif task_id == "ieeg-finger-flexion-bciciv4":
            receipt = owner / "legacy-freeze.json"
            write_new_json(receipt, legacy_receipt(task_id, artifacts, hashes))
            output = run_scorer([python, str(task / "checks/evaluate.py"),
                                 "--artifacts", str(artifacts), "--data", str(data / "test"),
                                 "--image", image, "--role", "test", "--owner-test",
                                 "--frozen", str(receipt)])
            metrics = flat_metrics(json.loads(output), task_id)
        elif task_id == "ieeg-film-speech-music":
            owner_dir = data / "derived-v2/owner"
            if owner_dir.is_symlink() or not owner_dir.is_dir():
                raise ValueError("film owner data directory is missing")
            nonce = uuid.uuid4().hex
            receipt = owner_dir / f".dispatch-{nonce}-freeze.json"
            report = owner_dir / f".dispatch-{nonce}-report.json"
            submission = artifacts / "submission"
            if set(path.name for path in submission.iterdir()) != set(MODEL_FILES):
                raise ValueError("film submission file set differs")
            write_new_json(receipt, {"schema": "bpb-ieeg-film-frozen-submission/1",
                                     "sha256": {name: hashes[f"submission/{name}"] for name in MODEL_FILES}})
            try:
                run_scorer([python, str(task / "checks/run.py"), "--data-root", str(data),
                            "--submission", str(submission), "--role", "test", "--image", image,
                            "--frozen-submission-receipt", str(receipt), "--owner-test",
                            "--report-out", str(report)])
                metrics = flat_metrics(strict_json(report), task_id)
            finally:
                receipt.unlink(missing_ok=True)
                report.unlink(missing_ok=True)
        elif task_id in FALCON:
            receipt = owner / "legacy-freeze.json"
            write_new_json(receipt, legacy_receipt(task_id, artifacts, hashes))
            name = FALCON[task_id]
            if name in ("h2", "b1"):
                report = owner / "report.json"
                run_scorer([python, str(ROOT / "tasks/intracortical/_sequence_shared/score.py"),
                            "--sequence-task", name, "--task", str(task),
                            "--artifacts", str(artifacts), "--data-manifest", str(data / "test/manifest.json"),
                            "--image", image, "--role", "test", "--owner-test",
                            "--frozen-artifact-manifest", str(receipt), "--report-output", str(report)])
                metrics = flat_metrics(strict_json(report), task_id)
            else:
                output = run_scorer([python, str(task / "checks/score.py"), "--task", str(task),
                                     "--artifacts", str(artifacts), "--data-manifest", str(data / "test/manifest.json"),
                                     "--image", image, "--role", "test", "--owner-test",
                                     "--frozen-artifact-manifest", str(receipt)])
                metrics = flat_metrics(json.loads(output), task_id)
        elif task_id == "brain-age-mri":
            prepared = data / "prepared"
            output = run_scorer([python, str(task / "checks/evaluate_external.py"),
                                 "--submission-dir", str(artifacts), "--evaluator-data", str(prepared),
                                 "--output-dir", str(owner), "--image", image,
                                 "--gpus", "none", "--bpb-sentinel"])
            metrics = flat_metrics(parse_sentinel(output), task_id)
        else:
            prepared = data / "prepared"
            output = run_scorer([python, str(task / "checks/evaluate_external.py"),
                                 "--artifacts", str(artifacts), "--private", str(prepared),
                                 "--worker-image", image])
            metrics = flat_metrics(parse_sentinel(output), task_id)
    if artifact_snapshot(artifacts) != hashes:
        raise ValueError("submission changed during private Test scoring")
    if verify_materialization_data(task, data) != materialized_sources:
        raise ValueError("private evaluator source changed during scoring")
    if prepared_receipt is not None and verify_prepared_data(task, data)[1] != prepared_receipt:
        raise ValueError("prepared private data changed during scoring")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--frozen", required=True, type=Path)
    args = parser.parse_args()
    try:
        metrics = score(args.task, args.artifacts, args.data, args.frozen)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError,
            json.JSONDecodeError) as error:
        print(f"private Test unscored: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(START)
    print(json.dumps(metrics, allow_nan=False, sort_keys=True))
    print(END)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
