#!/usr/bin/env python3
"""tops-fmri external evaluator.

Contract with the agent submission:
  python3 artifacts/scripts/apply_signature.py \
    --eval-features-dir <feature_dir> \
    --model-dir artifacts/models \
    --out-dir <prediction_dir>

The agent script sees only feature matrices. This evaluator keeps labels
private, runs the submitted signature, computes Study4 Pearson r + Study5 AUC,
and emits a flat {str:number} JSON between BPB_SCORES sentinels.

Failure modes (missing artifact / private data / bad CSV / non-finite output)
print to stderr and exit 0 without printing the sentinels — the BPB exec
scorer then reports unscored (never 0), which is what we want.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

STUDY4_CONDITIONS = ["SBP_SP", "SBP_REST", "CBP_SP", "CBP_REST"]
STUDY5_SITES = ["JP", "UK"]

SENTINEL_START = ">>>>> BPB_SCORES"
SENTINEL_END = "<<<<< BPB_SCORES"


def _fail(msg: str) -> int:
    """Print to stderr, return 0 → BPB scorer sees no sentinel → unscored."""
    print(f"tops-fmri evaluator: {msg}", file=sys.stderr)
    return 0


def read_predictions(path: Path, group_col: str, expected_groups: list[str]) -> dict[str, np.ndarray]:
    if not path.exists():
        raise ValueError(f"missing prediction file: {path.name}")
    out: dict[str, list[tuple[int, float]]] = {g: [] for g in expected_groups}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        required = {group_col, "sample_id", "signature_response"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"{path.name} must contain columns: {sorted(required)}")
        for row in reader:
            group = row[group_col]
            if group not in out:
                raise ValueError(f"unexpected {group_col} in {path.name}: {group}")
            sample_id = int(row["sample_id"])
            response = float(row["signature_response"])
            if not math.isfinite(response):
                raise ValueError(f"non-finite signature_response in {path.name}")
            out[group].append((sample_id, response))
    arrays: dict[str, np.ndarray] = {}
    for group, rows in out.items():
        rows_sorted = sorted(rows, key=lambda x: x[0])
        if [i for i, _ in rows_sorted] != list(range(len(rows_sorted))):
            raise ValueError(f"{path.name}:{group} sample_id must be 0..n-1 with no gaps")
        arrays[group] = np.asarray([v for _, v in rows_sorted], dtype=float)
    return arrays


def pearson_r(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]; y = y[mask]
    if x.size < 3:
        raise ValueError("Pearson r requires at least 3 finite samples")
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def auc_score(scores: np.ndarray, labels: np.ndarray) -> float:
    mask = np.isfinite(scores) & np.isfinite(labels)
    scores = scores[mask]
    labels = labels[mask].astype(int)
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    if pos.size == 0 or neg.size == 0:
        raise ValueError("AUC requires at least one positive and one negative sample")
    wins = (pos[:, None] > neg[None, :]).sum()
    ties = (pos[:, None] == neg[None, :]).sum()
    return float((wins + 0.5 * ties) / (pos.size * neg.size))


def copy_feature_inputs(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for name in ["study4_features.npz", "study5_features.npz"]:
        shutil.copy2(src / name, dst / name)


def run_agent_inference(run_dir: Path, features_dir: Path, pred_dir: Path, sandbox_dir: Path) -> None:
    submitted_script = run_dir / "artifacts" / "scripts" / "apply_signature.py"
    submitted_models = run_dir / "artifacts" / "models"
    if not submitted_script.exists():
        raise ValueError("missing artifacts/scripts/apply_signature.py")
    if not submitted_models.exists():
        raise ValueError("missing artifacts/models")

    # The submitted program is untrusted. Give it only copied code/models and
    # held-out features in a temporary execution root. In particular, do not
    # pass the evaluator label directory, its environment variable, HF tokens,
    # proxy credentials, or the submission bundle itself.
    script_dir = sandbox_dir / "scripts"
    model_dir = sandbox_dir / "models"
    home_dir = sandbox_dir / "home"
    tmp_dir = sandbox_dir / "tmp"
    script_dir.mkdir(parents=True)
    home_dir.mkdir()
    tmp_dir.mkdir()
    shutil.copy2(submitted_script, script_dir / "apply_signature.py")
    shutil.copytree(submitted_models, model_dir)
    script = script_dir / "apply_signature.py"
    agent_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home_dir),
        "TMPDIR": str(tmp_dir),
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
    }
    cmd = [
        sys.executable, "-I",
        str(script),
        "--eval-features-dir", str(features_dir),
        "--model-dir", str(model_dir),
        "--out-dir", str(pred_dir),
    ]
    subprocess.run(cmd, cwd=sandbox_dir, env=agent_env, check=True, timeout=120)


def resolve_private_dir(run_dir: Path) -> Path | None:
    """查找顺序 —— env var → runDir/private_eval (Oracle) → 空."""
    env = os.environ.get("BPB_TOPS_PRIVATE_EVAL_DIR")
    if env:
        p = Path(env)
        if (p / "features").exists() and (p / "labels").exists():
            return p
    local = run_dir / "private_eval"
    if (local / "features").exists() and (local / "labels").exists():
        return local
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return _fail("usage: evaluate_external.py <run_dir>")
    run_dir = Path(argv[1]).resolve()

    private = resolve_private_dir(run_dir)
    if private is None:
        return _fail(
            "no private eval data found (checked BPB_TOPS_PRIVATE_EVAL_DIR and "
            f"{run_dir}/private_eval)"
        )

    source_features = private / "features"
    labels_dir = private / "labels"

    try:
        with tempfile.TemporaryDirectory(prefix="tops-eval-") as tmp:
            tmp_path = Path(tmp)
            features_dir = tmp_path / "features"
            pred_dir = tmp_path / "predictions"
            sandbox_dir = tmp_path / "agent-sandbox"
            pred_dir.mkdir()
            sandbox_dir.mkdir()
            copy_feature_inputs(source_features, features_dir)
            run_agent_inference(run_dir, features_dir, pred_dir, sandbox_dir)

            study4_pred = read_predictions(pred_dir / "study4_predictions.csv", "condition", STUDY4_CONDITIONS)
            study5_pred = read_predictions(pred_dir / "study5_predictions.csv", "site", STUDY5_SITES)

            study4_labels = np.load(labels_dir / "study4_labels.npz")
            study5_labels = np.load(labels_dir / "study5_labels.npz")

            study4_rs: dict[str, float] = {}
            for condition in STUDY4_CONDITIONS:
                y = study4_labels[condition].astype(float).reshape(-1)
                pred = study4_pred[condition]
                if pred.shape[0] != y.shape[0]:
                    raise ValueError(f"Study4 {condition}: expected {y.shape[0]} predictions, got {pred.shape[0]}")
                study4_rs[condition] = pearson_r(pred, y)

            study5_aucs: dict[str, float] = {}
            for site in STUDY5_SITES:
                y = study5_labels[site].astype(int).reshape(-1)
                pred = study5_pred[site]
                if pred.shape[0] != y.shape[0]:
                    raise ValueError(f"Study5 {site}: expected {y.shape[0]} predictions, got {pred.shape[0]}")
                study5_aucs[site] = auc_score(pred, y)
    except subprocess.CalledProcessError as e:
        return _fail(f"apply_signature.py failed: exit {e.returncode}")
    except subprocess.TimeoutExpired:
        return _fail("apply_signature.py timed out (>120s)")
    except Exception as e:
        return _fail(str(e))

    study4_score = float(np.mean([max(0.0, min(1.0, study4_rs[c])) for c in STUDY4_CONDITIONS]))
    study5_score = float(np.mean([max(0.0, min(1.0, study5_aucs[s])) for s in STUDY5_SITES]))
    score = 0.5 * study4_score + 0.5 * study5_score

    # BPB exec scorer 要求扁平 {str:number}——r/auc 的负值也是有效数字,直接透传;score 与
    # study{4,5}_score 已 clip 到 [0,1](聚合已抹平方向),leaderboard 主排序看 score。
    out = {
        "score": score,
        "study4_score": study4_score,
        "study5_score": study5_score,
        "study4_SBP_SP_r": study4_rs["SBP_SP"],
        "study4_SBP_REST_r": study4_rs["SBP_REST"],
        "study4_CBP_SP_r": study4_rs["CBP_SP"],
        "study4_CBP_REST_r": study4_rs["CBP_REST"],
        "study5_JP_auc": study5_aucs["JP"],
        "study5_UK_auc": study5_aucs["UK"],
    }
    print(SENTINEL_START)
    print(json.dumps(out, sort_keys=True))
    print(SENTINEL_END)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
