"""One fixed Ridge fit on small H1 Train files and the final held-in Valid date.

Scientific smoke only: one of five Train dates, one Valid date (both same-day
sets), no Test, no hyperparameter search, no Agent. Spike binning follows the
MIT-licensed FALCON dataloaders.py at source SHA 770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

import numpy as np
from pynwb import NWBHDF5IO

import prepare


SHARED = Path(__file__).resolve().parent.parent / "_shared"
sys.path.insert(0, str(SHARED))
from metrics import regression  # noqa: E402


TRAIN_ID = "782b6fad-2679-4174-a88f-ad58589fe283"
VALID_IDS = ("18389588-85a6-4df8-a99b-48e3cfc9c9d8", "04e815ce-b86e-43f2-891f-9bba135857ca")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fit_ridge(neural: np.ndarray, target: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fixed alpha=1 multivariate Ridge with a fitted intercept.

    Einsum avoids the spurious floating-point status warnings emitted by the
    local macOS BLAS on finite matrix products. No validation information enters
    the centering, coefficients, or parameter choice.
    """
    x = neural[valid].astype(np.float64)
    y = target[valid]
    if len(x) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Invalid Ridge training inputs")
    x_mean, y_mean = x.mean(axis=0), y.mean(axis=0)
    x_centered, y_centered = x - x_mean, y - y_mean
    gram = np.einsum("ni,nj->ij", x_centered, x_centered)
    rhs = np.einsum("ni,nk->ik", x_centered, y_centered)
    coef = np.linalg.solve(gram + np.eye(x.shape[1]), rhs)
    intercept = y_mean - np.einsum("i,ij->j", x_mean, coef)
    if not np.isfinite(coef).all() or not np.isfinite(intercept).all():
        raise ValueError("Non-finite Ridge parameters")
    return coef, intercept


def load_h1(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        nwb = io.read()
        units = nwb.units.to_dataframe()
        target = np.asarray(nwb.acquisition["OpenLoopKinematicsVelocity"].data[:], dtype=np.float64)
        valid = np.asarray(nwb.acquisition["eval_mask"].data[:], dtype=bool)
        clock = nwb.acquisition["OpenLoopKinematics"]
        if len(units) != 176 or target.shape[1] != 7 or valid.shape != (len(target),):
            raise ValueError("H1 native shape or mask changed")
        # Upstream load_nwb: bin timestamps are offset + index * rate; this
        # public H1 asset declares rate=0.02s. Spike counts use the preceding
        # 20ms interval and cannot access future neural observations.
        if not np.isclose(clock.rate, 0.02):
            raise ValueError(f"Unexpected H1 timestamp step: {clock.rate}")
        timestamps = clock.offset + np.arange(len(target)) * clock.rate
        edges = np.concatenate(([timestamps[0] - 0.02], timestamps))
        neural = np.empty((len(target), len(units)), dtype=np.uint8)
        for column, (_, unit) in enumerate(units.iterrows()):
            counts, _ = np.histogram(unit.spike_times, bins=edges)
            if np.any(counts > 255):
                raise ValueError("Spike bin exceeds upstream uint8 representation")
            neural[:, column] = counts.astype(np.uint8)
        return neural, target, valid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    root = prepare.safe_destination(args.dest) / "public"
    manifest = prepare.load_manifest()
    assets = {a["asset_id"]: a for a in prepare.select(manifest, "falcon-h1-reach-grasp", "public", [])}
    required = [assets[asset_id] for asset_id in (TRAIN_ID, *VALID_IDS)]
    if [a["role"] for a in required] != ["train", "valid", "valid"]:
        raise ValueError("Reference asset roles changed")
    if len({a["session_date"] for a in required[1:]}) != 1:
        raise ValueError("Valid sets must share one date")
    loaded = []
    for asset in required:
        path = prepare.file_path(root, asset)
        prepare.verify_one(path, asset)
        loaded.append(load_h1(path))
    train_neural, train_target, train_mask = loaded[0]
    coef, intercept = fit_ridge(train_neural, train_target, train_mask)
    valid_runs = []
    for neural, target, mask in loaded[1:]:
        if not np.isfinite(neural).all() or not np.isfinite(target[mask]).all():
            raise ValueError("Non-finite Valid inputs or targets")
        prediction = np.einsum("ni,ij->nj", neural.astype(np.float64), coef) + intercept
        if prediction.shape != target.shape or not np.isfinite(prediction).all():
            raise ValueError("Invalid Ridge prediction")
        valid_runs.append((prediction, target, mask))
    date = required[1]["session_date"]
    result = regression({date: valid_runs})
    artifact_root = prepare.safe_destination(args.dest) / "reference"
    artifact_dir = artifact_root / f"h1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    model_path = artifact_dir / "model_parameters.npz"
    prediction_path = artifact_dir / "valid_predictions.npz"
    np.savez_compressed(model_path, coef=coef, intercept=intercept, alpha=np.float64(1.0))
    np.savez_compressed(prediction_path, **{f"set_{i+1}": run[0] for i, run in enumerate(valid_runs)})
    receipt = {
        "schema": "bpb-intracortical-reference-receipt/1",
        "task": "falcon-h1-reach-grasp",
        "profile": manifest["profile"],
        "upstream_source_sha": manifest["upstream_source_sha"],
        "manifest_sha256": sha256_file(prepare.MANIFEST),
        "reference_code_sha256": sha256_file(Path(__file__)),
        "metric_code_sha256": sha256_file(SHARED / "metrics.py"),
        "scientific_dependencies": {name: version(name) for name in ("numpy", "scikit-learn", "pynwb")},
        "reference_only": True,
        "model": "closed-form Ridge(alpha=1.0), fixed before validation; causal 20ms spike bins",
        "train_asset_ids": [TRAIN_ID],
        "valid_asset_ids": list(VALID_IDS),
        "train_assets": 1,
        "train_dates_of_5": 1,
        "train_valid_timesteps": int(train_mask.sum()),
        "valid_assets": 2,
        "valid_dates": 1,
        "valid_valid_timesteps": result["valid_timesteps"][date],
        "valid_r2": result["mean"],
        "test_accessed": False,
        "official_falcon_score": False,
        "formal_agent_result": False,
        "model_path": str(model_path),
        "model_sha256": sha256_file(model_path),
        "prediction_path": str(prediction_path),
        "prediction_sha256": sha256_file(prediction_path),
    }
    receipt_path = artifact_dir / "receipt.json"
    with receipt_path.open("x") as output:
        json.dump(receipt, output, sort_keys=True, indent=2)
        output.write("\n")
    print(json.dumps({"receipt": str(receipt_path), "valid_r2": receipt["valid_r2"],
                      "reference_only": True, "test_accessed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
