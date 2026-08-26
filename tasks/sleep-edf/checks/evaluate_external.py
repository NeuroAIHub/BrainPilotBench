#!/usr/bin/env python3
"""sleep-edf external evaluator.

Contract with the agent submission:
  the agent puts   `EEG_sleep/sleep_agent_model.py`   in its workspace.
  BPB collects it as `run_dir/artifacts/EEG_sleep/sleep_agent_model.py`.
The scorer spawns an isolated child process (train_and_infer.py) that
trains one SleepAgentModel on subjects 0-13 (val 14-15 for early stop)
and produces predictions for subjects 16-19. This process then reads
predictions back, loads the true hypnogram labels for the same test
subjects (in the scorer process only), and computes metrics.

Failure modes (missing artifact / private data / bad forward shape /
non-finite output / child crash) print to stderr and exit 0 without
printing the sentinels — the BPB exec scorer then reports unscored
(never zero), which is what we want.

Output: single flat {str:number} JSON between BPB_SCORES sentinels.
Keys line up with categories.yaml `eeg-sleep-staging`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    cohen_kappa_score,
    f1_score,
    recall_score,
)

warnings.filterwarnings("ignore")

SENTINEL_START = ">>>>> BPB_SCORES"
SENTINEL_END = "<<<<< BPB_SCORES"
CHILD_TIMEOUT_S = 60 * 150  # 150 min for training + all-subject inference
CLASS_NAMES = ["wake", "n1", "n2", "n3", "rem"]

DEFAULT_TRAIN_SUBJECTS = list(range(14))      # 0..13
DEFAULT_VAL_SUBJECTS = [14, 15]
DEFAULT_TEST_SUBJECTS = [16, 17, 18, 19]

# Chance-level baseline for a 5-class problem: acc = 1/5, kappa = 0, per-class
# recall = 1/5. These fixed numbers are only used to walk the pipeline in the
# Oracle sandbox and have no scientific meaning.
ORACLE_ACC = 0.20
ORACLE_KAPPA = 0.0
ORACLE_F1 = 0.20
ORACLE_RECALL = 0.20


def _fail(msg: str) -> int:
    """Print to stderr, return 0 → BPB scorer sees no sentinel → unscored."""
    print(f"sleep-edf evaluator: {msg}", file=sys.stderr)
    return 0


def resolve_private_dir(run_dir: Path) -> Path | None:
    """Env var → runDir/private_eval (Oracle fallback) → None."""
    env = os.environ.get("BPB_SLEEP_EDF_PRIVATE_EVAL_DIR")
    if env:
        p = Path(env)
        if (p / "train_edf").is_dir() and (p / "test_edf").is_dir() and (p / "manifests").is_dir():
            return p
    local = run_dir / "private_eval"
    if (local / "train_edf").is_dir() and (local / "test_edf").is_dir() and (local / "manifests").is_dir():
        return local
    return None


def find_agent_model(run_dir: Path) -> Path:
    """The submitted class file lands at artifacts/EEG_sleep/sleep_agent_model.py.

    The task's `expected_artifacts` fixes this path; there is no fallback.
    A submission that puts the file elsewhere is treated as missing.
    """
    p = run_dir / "artifacts" / "EEG_sleep" / "sleep_agent_model.py"
    if not p.exists():
        raise RuntimeError(f"missing submitted model: {p}")
    return p


def _container_user() -> str:
    explicit = os.environ.get("BPB_INFERENCE_USER")
    if explicit:
        import re
        if not re.fullmatch(r"[1-9]\d*:[1-9]\d*", explicit):
            raise ValueError("BPB_INFERENCE_USER must be a non-root numeric uid:gid")
        return explicit
    uid = os.getuid()
    gid = os.getgid()
    if uid == 0 or gid == 0:
        raise ValueError("refusing to run submission inference as root; set BPB_INFERENCE_USER")
    return f"{uid}:{gid}"


def _docker_mount(source: Path, target: str, readonly: bool = False) -> str:
    resolved = str(source.resolve())
    if "," in resolved or "\n" in resolved or "\r" in resolved:
        raise ValueError(f"Docker mount path contains an unsupported character: {resolved}")
    suffix = ",readonly" if readonly else ""
    return f"type=bind,source={resolved},target={target}{suffix}"


def _docker_client_env() -> dict[str, str]:
    allowed = ["PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"]
    return {key: os.environ[key] for key in allowed if os.environ.get(key)}


def run_child_process(
    script: Path,
    private_dir: Path,
    sandbox_dir: Path,
    out_csv: Path,
    train_subjects: list[int],
    val_subjects: list[int],
    test_subjects: list[int],
) -> None:
    home_dir = sandbox_dir / "home"
    tmp_dir = sandbox_dir / "tmp"
    home_dir.mkdir(exist_ok=True)
    tmp_dir.mkdir(exist_ok=True)
    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home_dir),
        "TMPDIR": str(tmp_dir),
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
    }
    cmd = [
        sys.executable, "-I", str(script),
        "--model-source", str(sandbox_dir / "sleep_agent_model.py"),
        "--train-subjects", ",".join(str(i) for i in train_subjects),
        "--val-subjects", ",".join(str(i) for i in val_subjects),
        "--test-subjects", ",".join(str(i) for i in test_subjects),
        "--train-edf-root", str(private_dir / "train_edf"),
        "--test-edf-root", str(private_dir / "test_edf"),
        "--manifest-dir", str(private_dir / "manifests"),
        "--out", str(out_csv),
    ]
    subprocess.run(cmd, cwd=sandbox_dir, env=child_env, check=True, timeout=CHILD_TIMEOUT_S)


def run_child_docker(
    script: Path,
    private_dir: Path,
    sandbox_dir: Path,
    out_csv: Path,
    train_subjects: list[int],
    val_subjects: list[int],
    test_subjects: list[int],
    *,
    use_gpu: bool = True,
) -> None:
    import re, uuid
    image = os.environ.get("BPB_INFERENCE_IMAGE", "").strip()
    if not image:
        raise ValueError("Docker submission isolation requires BPB_INFERENCE_IMAGE")
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1" and not re.search(r"@sha256:[0-9a-fA-F]{64}$", image):
        raise ValueError("official scoring requires an immutable BPB_INFERENCE_IMAGE digest")
    docker = os.environ.get("BPB_DOCKER_BINARY", "docker")
    name = f"bpb-sleep-{uuid.uuid4().hex[:8]}"
    out_dir = out_csv.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    gpu_args = ["--gpus", "all"] if use_gpu else []
    cmd = [
        docker, "run", "--rm", "--init", "--name", name,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "256",
        *gpu_args,
        "--memory", "16g",
        "--user", _container_user(),
        "--workdir", "/work",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=4g",
        "--env", "HOME=/tmp",
        "--env", "PYTHONHASHSEED=0",
        "--env", "PYTHONNOUSERSITE=1",
        "--mount", _docker_mount(script.parent, "/work/scripts", readonly=True),
        "--mount", _docker_mount(sandbox_dir, "/work/sandbox", readonly=True),
        "--mount", _docker_mount(private_dir / "train_edf", "/work/train_edf", readonly=True),
        "--mount", _docker_mount(private_dir / "test_edf", "/work/test_edf", readonly=True),
        "--mount", _docker_mount(private_dir / "manifests", "/work/manifests", readonly=True),
        "--mount", _docker_mount(out_dir, "/work/out"),
        "--entrypoint", "python3",
        image,
        "-I", "/work/scripts/" + script.name,
        "--model-source", "/work/sandbox/sleep_agent_model.py",
        "--train-subjects", ",".join(str(i) for i in train_subjects),
        "--val-subjects", ",".join(str(i) for i in val_subjects),
        "--test-subjects", ",".join(str(i) for i in test_subjects),
        "--train-edf-root", "/work/train_edf",
        "--test-edf-root", "/work/test_edf",
        "--manifest-dir", "/work/manifests",
        "--out", "/work/out/" + out_csv.name,
    ]
    docker_env = _docker_client_env()
    try:
        subprocess.run(cmd, env=docker_env, check=True, timeout=CHILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "rm", "-f", name], env=docker_env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise


def load_true_labels(private_dir: Path, manifest: dict, test_subjects: list[int]) -> dict[int, np.ndarray]:
    """Return {subject_id: (N,) labels 0..4} using the same load pipeline as
    train_and_infer.py — this guarantees N and epoch order match the child's
    predictions exactly.
    """
    # Local import so the scorer parent doesn't pay mne startup cost until
    # after we've decided we're not in oracle mode.
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).parent))
    try:
        import train_and_infer as tai  # noqa: F401
    finally:
        sys.path.pop(0)

    out: dict[int, list[int]] = {}
    for sid in test_subjects:
        entry = manifest.get(str(sid))
        if entry is None:
            raise RuntimeError(f"manifest missing test subject {sid}")
        acc: list[int] = []
        for rec in entry["recordings"].values():
            _, y = tai.load_subject_recording(
                psg_path=private_dir / "test_edf" / rec["psg"],
                hyp_path=private_dir / "test_edf" / rec["hypnogram"],
            )
            acc.extend(y.tolist())
        out[sid] = np.asarray(acc, dtype=np.int64)
    return out


def read_predictions(csv_path: Path) -> dict[int, np.ndarray]:
    """Return {subject_id: (N,) predicted_label} with each subject's rows in
    the same epoch order the CSV was written in.
    """
    if not csv_path.exists():
        raise RuntimeError(f"missing prediction file: {csv_path}")
    by_subject: dict[int, list[tuple[int, int]]] = {}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        expected = ["subject_id", "epoch_id", "predicted_label"]
        if reader.fieldnames != expected:
            raise RuntimeError(f"{csv_path.name}: expected header {expected}, got {reader.fieldnames}")
        for row in reader:
            sid = int(row["subject_id"])
            eid = int(row["epoch_id"])
            p = int(row["predicted_label"])
            if p < 0 or p >= 5:
                raise RuntimeError(f"predicted_label out of range: {p}")
            by_subject.setdefault(sid, []).append((eid, p))
    result: dict[int, np.ndarray] = {}
    for sid, rows in by_subject.items():
        rows.sort(key=lambda x: x[0])
        eids = [e for e, _ in rows]
        if eids != list(range(len(eids))):
            raise RuntimeError(f"subject {sid}: epoch_id must be 0..N-1 with no gaps, got {eids[:5]}...")
        result[sid] = np.asarray([p for _, p in rows], dtype=np.int64)
    return result


def emit_scores(payload: dict) -> None:
    print(SENTINEL_START)
    print(json.dumps(payload, sort_keys=True))
    print(SENTINEL_END)


def oracle_payload() -> dict:
    """Chance-level scores for the Oracle gate (validate 120 s sandbox).

    Real training on subjects 0-13 takes tens of minutes on an A10; the
    Oracle only checks that the scorer pipeline can emit a sentinel.
    """
    return {
        "score": ORACLE_KAPPA,           # kappa clipped to [0,1] → 0.0
        "test_kappa": ORACLE_KAPPA,
        "test_accuracy": ORACLE_ACC,
        "test_balanced_accuracy": ORACLE_ACC,
        "test_macro_f1": ORACLE_F1,
        "wake_recall": ORACLE_RECALL,
        "n1_recall": ORACLE_RECALL,
        "n2_recall": ORACLE_RECALL,
        "n3_recall": ORACLE_RECALL,
        "rem_recall": ORACLE_RECALL,
    }


def load_manifest(private_dir: Path) -> dict:
    p = private_dir / "manifests" / "subjects.json"
    if not p.exists():
        raise RuntimeError(f"missing manifests/subjects.json under {private_dir}")
    return json.loads(p.read_text(encoding="utf-8"))


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Compute the production metric payload from aligned epoch labels."""
    y_true = np.asarray(y_true, dtype=np.int64)
    y_pred = np.asarray(y_pred, dtype=np.int64)
    if y_true.shape != y_pred.shape:
        raise ValueError(f"prediction shape {y_pred.shape} does not match labels {y_true.shape}")
    if not np.isfinite(y_pred).all():
        raise ValueError("non-finite predictions")
    labels_all = [0, 1, 2, 3, 4]
    test_accuracy = float(accuracy_score(y_true, y_pred))
    test_balanced_accuracy = float(balanced_accuracy_score(y_true, y_pred))
    test_macro_f1 = float(f1_score(y_true, y_pred, labels=labels_all, average="macro", zero_division=0))
    test_kappa = float(cohen_kappa_score(y_true, y_pred, labels=labels_all))
    per_class_recall = recall_score(
        y_true, y_pred, labels=labels_all, average=None, zero_division=0,
    )
    out = {
        "score": max(0.0, min(1.0, test_kappa)),
        "test_kappa": test_kappa,
        "test_accuracy": test_accuracy,
        "test_balanced_accuracy": test_balanced_accuracy,
        "test_macro_f1": test_macro_f1,
    }
    for name, recall in zip(CLASS_NAMES, per_class_recall):
        out[f"{name}_recall"] = float(recall)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--oracle-mode", action="store_true",
                    help="Skip GPU training, emit a chance-level sentinel (for Oracle gate)")
    args = ap.parse_args(argv[1:])

    run_dir = args.run_dir.resolve()

    if args.oracle_mode:
        emit_scores(oracle_payload())
        return 0

    private = resolve_private_dir(run_dir)
    if private is None:
        return _fail(
            "no private eval data found (checked BPB_SLEEP_EDF_PRIVATE_EVAL_DIR and "
            f"{run_dir}/private_eval)"
        )

    try:
        model_source = find_agent_model(run_dir)
    except Exception as e:
        return _fail(str(e))

    try:
        manifest = load_manifest(private)
    except Exception as e:
        return _fail(str(e))

    isolation = os.environ.get("BPB_SUBMISSION_ISOLATION", "process")
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1" and isolation != "docker":
        return _fail("official scoring requires BPB_SUBMISSION_ISOLATION=docker")

    runner_script = Path(__file__).with_name("train_and_infer.py")
    if not runner_script.exists():
        return _fail(f"scorer runner missing: {runner_script}")

    try:
        with tempfile.TemporaryDirectory(prefix="sleep-edf-") as tmp:
            tmp_path = Path(tmp)
            sandbox_dir = tmp_path / "sandbox"
            sandbox_dir.mkdir()
            shutil.copy2(model_source, sandbox_dir / "sleep_agent_model.py")
            out_csv = tmp_path / "pred.csv"

            print("sleep-edf: launching training + inference child ...", file=sys.stderr, flush=True)
            if isolation == "docker":
                run_child_docker(
                    script=runner_script, private_dir=private, sandbox_dir=sandbox_dir,
                    out_csv=out_csv,
                    train_subjects=DEFAULT_TRAIN_SUBJECTS,
                    val_subjects=DEFAULT_VAL_SUBJECTS,
                    test_subjects=DEFAULT_TEST_SUBJECTS,
                )
            elif isolation == "process":
                run_child_process(
                    script=runner_script, private_dir=private, sandbox_dir=sandbox_dir,
                    out_csv=out_csv,
                    train_subjects=DEFAULT_TRAIN_SUBJECTS,
                    val_subjects=DEFAULT_VAL_SUBJECTS,
                    test_subjects=DEFAULT_TEST_SUBJECTS,
                )
            else:
                return _fail(f"unknown BPB_SUBMISSION_ISOLATION: {isolation}")

            preds_by_subject = read_predictions(out_csv)
    except subprocess.CalledProcessError as e:
        return _fail(f"training subprocess exited {e.returncode}")
    except subprocess.TimeoutExpired:
        return _fail(f"training exceeded {CHILD_TIMEOUT_S//60} min timeout")
    except Exception as e:
        return _fail(str(e))

    try:
        labels_by_subject = load_true_labels(private, manifest, DEFAULT_TEST_SUBJECTS)
    except Exception as e:
        return _fail(f"failed to load ground-truth labels: {e}")

    y_true_all: list[int] = []
    y_pred_all: list[int] = []
    for sid in DEFAULT_TEST_SUBJECTS:
        if sid not in preds_by_subject:
            return _fail(f"predictions missing for subject {sid}")
        y_true = labels_by_subject[sid]
        y_pred = preds_by_subject[sid]
        if y_pred.shape != y_true.shape:
            return _fail(
                f"subject {sid}: prediction count {y_pred.shape[0]} does not match "
                f"ground-truth epoch count {y_true.shape[0]}"
            )
        y_true_all.extend(y_true.tolist())
        y_pred_all.extend(y_pred.tolist())

    y_true = np.asarray(y_true_all, dtype=np.int64)
    y_pred = np.asarray(y_pred_all, dtype=np.int64)

    try:
        out = compute_metrics(y_true, y_pred)
    except Exception as e:
        return _fail(str(e))

    emit_scores(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
