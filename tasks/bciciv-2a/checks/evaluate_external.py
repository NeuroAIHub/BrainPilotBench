#!/usr/bin/env python3
"""bciciv-2a external evaluator.

Contract with the agent submission:
  the agent puts   `EEG_MI/mi_agent_model.py`   in its workspace.
  BPB collects it as `run_dir/artifacts/EEG_MI/mi_agent_model.py`.
This scorer loops over 9 subjects, spawns an isolated child process per
subject (train_and_infer.py) that trains a fresh MIAgentModel on the
public session-T GDF and predicts on the private session-E GDF, then
reads back the predictions and compares against private true labels.

Failure modes (missing artifact / private data / bad forward shape /
non-finite output / child crash) print to stderr and exit 0 without
printing the sentinels — the BPB exec scorer then reports unscored
(never zero), which is what we want.

Output: single flat {str:number} JSON between BPB_SCORES sentinels.
Keys line up with categories.yaml `eeg-motor-imagery`.
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
from pathlib import Path

import numpy as np
import scipy.io as sio
from sklearn.metrics import accuracy_score, cohen_kappa_score, f1_score

SUBJECTS = list(range(1, 10))
N_TEST_TRIALS = 288
SENTINEL_START = ">>>>> BPB_SCORES"
SENTINEL_END = "<<<<< BPB_SCORES"
CHILD_TIMEOUT_S = 60 * 25  # 25 min per subject, generous on A10-class GPU

# Chance-level baseline for a 4-class balanced problem: acc = 1/4, kappa = 0.
ORACLE_ACC = 0.25
ORACLE_KAPPA = 0.0
ORACLE_F1 = 0.25


def _fail(msg: str) -> int:
    """Print to stderr, return 0 → BPB scorer sees no sentinel → unscored."""
    print(f"bciciv-2a evaluator: {msg}", file=sys.stderr)
    return 0


def resolve_private_dir(run_dir: Path) -> Path | None:
    """Env var → runDir/private_eval (Oracle fallback) → None."""
    env = os.environ.get("BPB_BCI2A_PRIVATE_EVAL_DIR")
    if env:
        p = Path(env)
        if (p / "train_gdf").is_dir() and (p / "test_gdf").is_dir() and (p / "true_labels").is_dir():
            return p
    local = run_dir / "private_eval"
    if (local / "train_gdf").is_dir() and (local / "test_gdf").is_dir() and (local / "true_labels").is_dir():
        return local
    return None


def load_subjects_manifest(private_dir: Path) -> dict:
    """Load the same subjects.json the agent has, for stratified split indices."""
    manifest_path = private_dir / "manifests" / "subjects.json"
    if not manifest_path.exists():
        raise RuntimeError(f"missing manifests/subjects.json under {private_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_true_labels(private_dir: Path, subject_id: int) -> np.ndarray:
    """Return (288,) labels 1..4 for A0xE.mat."""
    mat_path = private_dir / "true_labels" / f"A0{subject_id}E.mat"
    if not mat_path.exists():
        raise RuntimeError(f"missing true labels: {mat_path}")
    data = sio.loadmat(str(mat_path))
    if "classlabel" not in data:
        raise RuntimeError(f"{mat_path.name}: expected key 'classlabel'")
    labels = np.asarray(data["classlabel"]).astype(np.int64).reshape(-1)
    if labels.shape != (N_TEST_TRIALS,):
        raise RuntimeError(f"{mat_path.name}: expected shape ({N_TEST_TRIALS},), got {labels.shape}")
    if not set(np.unique(labels).tolist()).issubset({1, 2, 3, 4}):
        raise RuntimeError(f"{mat_path.name}: labels must be in {{1..4}}, got {np.unique(labels)}")
    return labels


def read_predictions(csv_path: Path) -> np.ndarray:
    """Return (288,) predictions in 1..4."""
    if not csv_path.exists():
        raise RuntimeError(f"missing prediction file: {csv_path}")
    rows = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["sample_id", "predicted_label"]:
            raise RuntimeError(f"{csv_path.name}: expected header sample_id,predicted_label, got {reader.fieldnames}")
        for row in reader:
            rows.append((int(row["sample_id"]), int(row["predicted_label"])))
    rows.sort(key=lambda x: x[0])
    if [i for i, _ in rows] != list(range(N_TEST_TRIALS)):
        raise RuntimeError(f"{csv_path.name}: sample_id must be 0..{N_TEST_TRIALS-1} with no gaps")
    preds = np.asarray([p for _, p in rows], dtype=np.int64)
    if not set(preds.tolist()).issubset({1, 2, 3, 4}):
        raise RuntimeError(f"{csv_path.name}: predicted_label must be in {{1..4}}, got {np.unique(preds)}")
    return preds


def per_subject_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    acc = float(accuracy_score(y_true, y_pred))
    kappa = float(cohen_kappa_score(y_true, y_pred, labels=[1, 2, 3, 4]))
    macro_f1 = float(f1_score(y_true, y_pred, labels=[1, 2, 3, 4], average="macro", zero_division=0))
    return acc, kappa, macro_f1


def find_agent_model(run_dir: Path) -> Path:
    """The submitted class file lands at artifacts/EEG_MI/mi_agent_model.py.

    The task's `expected_artifacts` fixes this path; there is no fallback.
    A submission that puts the file elsewhere is treated as missing.
    """
    p = run_dir / "artifacts" / "EEG_MI" / "mi_agent_model.py"
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
    subject_id: int,
    train_gdf: Path,
    test_gdf: Path,
    train_idx: list[int],
    val_idx: list[int],
    out_csv: Path,
    sandbox_dir: Path,
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
    # Optional but important — the child may pull HF cache paths from XDG_*
    # if we don't scrub them, but we DO leak XDG_* would let MNE reach the
    # config dir; leave PATH and HOME only for isolation.
    cmd = [
        sys.executable, "-I", str(script),
        "--model-source", str(sandbox_dir / "mi_agent_model.py"),
        "--subject-id", str(subject_id),
        "--train-gdf", str(train_gdf),
        "--test-gdf", str(test_gdf),
        "--train-idx", ",".join(str(i) for i in train_idx),
        "--val-idx", ",".join(str(i) for i in val_idx),
        "--out", str(out_csv),
    ]
    subprocess.run(cmd, cwd=sandbox_dir, env=child_env, check=True, timeout=CHILD_TIMEOUT_S)


def run_child_docker(
    script: Path,
    subject_id: int,
    train_gdf: Path,
    test_gdf: Path,
    train_idx: list[int],
    val_idx: list[int],
    out_csv: Path,
    sandbox_dir: Path,
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
    name = f"bpb-bci2a-{subject_id}-{uuid.uuid4().hex[:8]}"
    # Runner + agent code + GDFs must be mounted read-only; only out_csv dir is writable.
    out_dir = out_csv.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    train_gdf_dir = train_gdf.parent
    test_gdf_dir = test_gdf.parent
    gpu_args = ["--gpus", "all"] if use_gpu else []
    cmd = [
        docker, "run", "--rm", "--init", "--name", name,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "256",
        *gpu_args,
        "--memory", "12g",
        "--user", _container_user(),
        "--workdir", "/work",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=2g",
        "--env", "HOME=/tmp",
        "--env", "PYTHONHASHSEED=0",
        "--env", "PYTHONNOUSERSITE=1",
        "--mount", _docker_mount(script.parent, "/work/scripts", readonly=True),
        "--mount", _docker_mount(sandbox_dir, "/work/sandbox", readonly=True),
        "--mount", _docker_mount(train_gdf_dir, "/work/train_gdf", readonly=True),
        "--mount", _docker_mount(test_gdf_dir, "/work/test_gdf", readonly=True),
        "--mount", _docker_mount(out_dir, "/work/out"),
        "--entrypoint", "python3",
        image,
        "-I", "/work/scripts/" + script.name,
        "--model-source", "/work/sandbox/mi_agent_model.py",
        "--subject-id", str(subject_id),
        "--train-gdf", "/work/train_gdf/" + train_gdf.name,
        "--test-gdf", "/work/test_gdf/" + test_gdf.name,
        "--train-idx", ",".join(str(i) for i in train_idx),
        "--val-idx", ",".join(str(i) for i in val_idx),
        "--out", "/work/out/" + out_csv.name,
    ]
    docker_env = _docker_client_env()
    try:
        subprocess.run(cmd, env=docker_env, check=True, timeout=CHILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "rm", "-f", name], env=docker_env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise


def run_subject(
    subject_id: int,
    model_source: Path,
    private_dir: Path,
    manifest_entry: dict,
    runner_script: Path,
    isolation: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (y_pred, y_true) each of shape (288,) with labels 1..4."""
    train_gdf = private_dir / "train_gdf" / f"A0{subject_id}T.gdf"
    test_gdf = private_dir / "test_gdf" / f"A0{subject_id}E.gdf"
    if not train_gdf.exists():
        raise RuntimeError(f"missing T-session GDF: {train_gdf}")
    if not test_gdf.exists():
        raise RuntimeError(f"missing E-session GDF: {test_gdf}")

    train_idx = list(manifest_entry["val_split"]["train_trial_indices"])
    val_idx = list(manifest_entry["val_split"]["val_trial_indices"])

    with tempfile.TemporaryDirectory(prefix=f"bci2a-{subject_id}-") as tmp:
        tmp_path = Path(tmp)
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()
        # Copy the submitted model into the sandbox — the child process only
        # sees this copy, never a workspace path.
        shutil.copy2(model_source, sandbox_dir / "mi_agent_model.py")
        out_csv = tmp_path / "pred.csv"

        if isolation == "docker":
            run_child_docker(runner_script, subject_id, train_gdf, test_gdf,
                             train_idx, val_idx, out_csv, sandbox_dir)
        elif isolation == "process":
            run_child_process(runner_script, subject_id, train_gdf, test_gdf,
                              train_idx, val_idx, out_csv, sandbox_dir)
        else:
            raise ValueError(f"unknown BPB_SUBMISSION_ISOLATION: {isolation}")

        y_pred = read_predictions(out_csv)

    y_true = load_true_labels(private_dir, subject_id)
    return y_pred, y_true


def emit_scores(payload: dict) -> None:
    print(SENTINEL_START)
    print(json.dumps(payload, sort_keys=True))
    print(SENTINEL_END)


def oracle_payload() -> dict:
    """Chance-level scores for the Oracle gate (validate 120s sandbox).

    Real training on 9 subjects × 100 epochs takes ~30 min on A10; the
    Oracle only checks that the scorer pipeline can emit a sentinel.
    """
    out = {
        "score": ORACLE_KAPPA,          # kappa clipped to [0,1] → 0.0
        "mean_accuracy": ORACLE_ACC,
        "mean_kappa": ORACLE_KAPPA,
        "mean_macro_f1": ORACLE_F1,
    }
    for s in SUBJECTS:
        out[f"subject_{s}_acc"] = ORACLE_ACC
        out[f"subject_{s}_kappa"] = ORACLE_KAPPA
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
            "no private eval data found (checked BPB_BCI2A_PRIVATE_EVAL_DIR and "
            f"{run_dir}/private_eval)"
        )

    try:
        model_source = find_agent_model(run_dir)
    except Exception as e:
        return _fail(str(e))

    try:
        manifest = load_subjects_manifest(private)
    except Exception as e:
        return _fail(str(e))

    isolation = os.environ.get("BPB_SUBMISSION_ISOLATION", "process")
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1" and isolation != "docker":
        return _fail("official scoring requires BPB_SUBMISSION_ISOLATION=docker")

    runner_script = Path(__file__).with_name("train_and_infer.py")
    if not runner_script.exists():
        return _fail(f"scorer runner missing: {runner_script}")

    per_subject: dict[int, tuple[float, float, float]] = {}
    try:
        for subject_id in SUBJECTS:
            key = str(subject_id)
            if key not in manifest:
                raise RuntimeError(f"manifest missing subject {subject_id}")
            print(f"bciciv-2a: training subject {subject_id} ...", file=sys.stderr, flush=True)
            y_pred, y_true = run_subject(
                subject_id=subject_id,
                model_source=model_source,
                private_dir=private,
                manifest_entry=manifest[key],
                runner_script=runner_script,
                isolation=isolation,
            )
            acc, kappa, macro_f1 = per_subject_metrics(y_true, y_pred)
            per_subject[subject_id] = (acc, kappa, macro_f1)
            print(f"bciciv-2a: subject {subject_id} → acc={acc:.4f} kappa={kappa:.4f} macroF1={macro_f1:.4f}",
                  file=sys.stderr, flush=True)
    except subprocess.CalledProcessError as e:
        return _fail(f"subject training subprocess exited {e.returncode}")
    except subprocess.TimeoutExpired:
        return _fail(f"subject training exceeded {CHILD_TIMEOUT_S//60} min timeout")
    except Exception as e:
        return _fail(str(e))

    accs = np.asarray([per_subject[s][0] for s in SUBJECTS])
    kappas = np.asarray([per_subject[s][1] for s in SUBJECTS])
    f1s = np.asarray([per_subject[s][2] for s in SUBJECTS])
    if not np.isfinite(accs).all() or not np.isfinite(kappas).all() or not np.isfinite(f1s).all():
        return _fail("non-finite per-subject metric")

    mean_kappa = float(kappas.mean())
    # score is the primary leaderboard column: clip kappa to [0,1]. Kappa can
    # go negative for worse-than-chance classifiers; clipping keeps the
    # leaderboard bounded to [0,1] like the other tasks.
    score = max(0.0, min(1.0, mean_kappa))

    out = {
        "score": score,
        "mean_accuracy": float(accs.mean()),
        "mean_kappa": mean_kappa,
        "mean_macro_f1": float(f1s.mean()),
    }
    for s in SUBJECTS:
        acc, kappa, _ = per_subject[s]
        out[f"subject_{s}_acc"] = float(acc)
        out[f"subject_{s}_kappa"] = float(kappa)

    emit_scores(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
