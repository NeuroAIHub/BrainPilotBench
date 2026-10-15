"""Create one low-information B1 spectrogram mean from two real Train motifs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from safetensors.numpy import save_file


TASK = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-data-dir", required=True, type=Path)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.public_data_dir.resolve()
    contract = json.loads((TASK / "contract.json").read_text())
    manifest_path = root / "train/manifest.json"
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != contract["derived_manifests"]["train"]["sha256"]:
        raise ValueError("Train manifest differs from contract")
    run = json.loads(manifest_path.read_text())["runs"][0]
    info = run["files"]["y.npy"]
    target = manifest_path.parent / info["path"]
    if target.stat().st_size != info["bytes"] or hashlib.sha256(target.read_bytes()).hexdigest() != info["sha256"]:
        raise ValueError("Train spectrogram differs from contract")
    y = np.load(target, mmap_mode="r", allow_pickle=False)
    if y.shape != (run["trials"], 880, 158) or len(y) < 2 or y.dtype != np.float64:
        raise ValueError("Train file lacks two native motifs")
    template = np.asarray(np.mean(y[:2], axis=0), dtype=np.float32)
    if not np.isfinite(template).all() or np.ptp(template) <= 0:
        raise ValueError("Train template is nonfinite or constant")
    submission = args.artifacts_dir / "submission"
    submission.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(TASK / "solution/model.py", submission / "model.py")
    (submission / "config.json").write_text(json.dumps({"schema": "bpb-b1-two-train-motifs-reference/1",
                                                         "motifs_used": 2}, sort_keys=True) + "\n")
    save_file({"template": np.ascontiguousarray(template)}, str(submission / "weights.safetensors"))
    print(json.dumps({"submission": str(submission), "train_run": run["id"],
                      "train_motifs_used": 2, "valid_labels_read": False,
                      "test_data_read": False, "model_executed_on_host": False}, sort_keys=True))


if __name__ == "__main__":
    main()
