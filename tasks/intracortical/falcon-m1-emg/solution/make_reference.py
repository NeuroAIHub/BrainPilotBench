"""Build one fixed M1 Ridge submission from a single public Train run.

Uses only m1-train-0002 (the first small real Train reference asset). It never
loads Valid labels or Test data, chooses no hyperparameters using scores, and
does not run model.py on the host. The generated artifact is a reference only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from safetensors.numpy import save_file


TASK_DIR = Path(__file__).resolve().parent.parent
TRAIN_ID = "m1-train-0001"
TRAIN_SOURCE_ASSET_ID = "13163b3c-95b7-4b0e-8181-72d7bd658e0b"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_verified(path: Path, info: dict) -> np.ndarray:
    if path.stat().st_size != info["bytes"] or digest(path) != info["sha256"]:
        raise ValueError(f"Frozen public Train array differs: {path.name}")
    array = np.load(path, allow_pickle=False)
    if list(array.shape) != info["shape"] or array.dtype.name != info["dtype"]:
        raise ValueError(f"Train array shape/dtype differs: {path.name}")
    return array


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-data-dir", required=True, type=Path)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    args = parser.parse_args()
    public_root = args.public_data_dir.resolve()
    artifacts_root = args.artifacts_dir.resolve()
    contract = json.loads((TASK_DIR / "contract.json").read_text())
    train_manifest_path = public_root / "train/manifest.json"
    binding = contract["derived_manifests"]["train"]
    if train_manifest_path.stat().st_size != binding["bytes"] or digest(train_manifest_path) != binding["sha256"]:
        raise ValueError("Train manifest differs from tracked M1 contract")
    manifest = json.loads(train_manifest_path.read_text())
    if manifest["schema"] != "bpb-falcon-regression-data/1" or manifest["role"] != "train":
        raise ValueError("Unexpected Train manifest")
    matches = [run for run in manifest["runs"] if run["id"] == TRAIN_ID]
    if len(matches) != 1:
        raise ValueError("Fixed reference Train run absent")
    run = matches[0]
    source_binding = next((item for item in contract["exported_runs"] if item["id"] == TRAIN_ID), None)
    if source_binding is None or source_binding["source_asset_id"] != TRAIN_SOURCE_ASSET_ID:
        raise ValueError("Fixed Train source asset changed")
    arrays = {}
    for name in ("x.npy", "y.npy", "mask.npy"):
        info = run["files"][name]
        relative = Path(info["path"])
        path = (train_manifest_path.parent / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(train_manifest_path.parent.resolve()):
            raise ValueError("Unsafe Train array path")
        arrays[name] = load_verified(path, info)
    x = arrays["x.npy"][arrays["mask.npy"]].astype(np.float64)
    y = arrays["y.npy"][arrays["mask.npy"]]
    if x.shape[1] != 64 or y.shape[1] != 16 or len(x) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Invalid fixed Ridge Train data")
    x_mean, y_mean = x.mean(axis=0), y.mean(axis=0)
    x_centered, y_centered = x - x_mean, y - y_mean
    gram = np.einsum("ni,nj->ij", x_centered, x_centered)
    rhs = np.einsum("ni,nk->ik", x_centered, y_centered)
    coef = np.linalg.solve(gram + np.eye(64), rhs)
    intercept = y_mean - np.einsum("i,ij->j", x_mean, coef)
    if not np.isfinite(coef).all() or not np.isfinite(intercept).all():
        raise ValueError("Non-finite Ridge parameters")
    submission = artifacts_root / "submission"
    submission.mkdir(parents=True, exist_ok=False)
    model_path = submission / "model.py"
    shutil.copyfile(TASK_DIR / "solution/model.py", model_path)
    config_path = submission / "config.json"
    with config_path.open("x") as output:
        json.dump({"schema": "bpb-m1-reference-config/1", "channels": 64, "outputs": 16,
                   "method": "fixed single-run Ridge alpha=1.0", "uses_trial_start": False}, output, sort_keys=True)
        output.write("\n")
    weights_path = submission / "weights.safetensors"
    save_file({"linear.weight": np.ascontiguousarray(coef.T, dtype=np.float32),
               "linear.bias": np.ascontiguousarray(intercept, dtype=np.float32)}, str(weights_path))
    receipt_path = artifacts_root / "m1-reference-submission.json"
    with receipt_path.open("x") as output:
        json.dump({"schema": "bpb-m1-reference-submission/1", "created_utc": datetime.now(timezone.utc).isoformat(),
                   "train_run": TRAIN_ID, "train_source_asset_id": TRAIN_SOURCE_ASSET_ID,
                   "train_valid_timesteps": int(len(x)), "valid_labels_read": False,
                   "test_data_read": False, "model_executed_on_host": False,
                   "submission": {name: {"sha256": digest(submission / name), "bytes": (submission / name).stat().st_size}
                                  for name in ("model.py", "config.json", "weights.safetensors")}},
                  output, sort_keys=True, indent=2)
        output.write("\n")
    print(json.dumps({"submission": str(submission), "receipt": str(receipt_path),
                      "train_run": TRAIN_ID, "valid_labels_read": False,
                      "test_data_read": False}, sort_keys=True))


if __name__ == "__main__":
    main()
