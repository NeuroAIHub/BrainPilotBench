"""Build a fixed three-file reference using Train only, without importing its model."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import numpy as np
from safetensors.numpy import save_file

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "env"))
from common import read_role, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.is_symlink() or (args.output.exists() and (
            not args.output.is_dir() or any(args.output.iterdir()))):
        raise ValueError("reference output must be new or empty")
    manifest, subjects = read_role(args.public_data / "train", "train")
    state = {}
    for record, arrays in subjects:
        x, y = arrays["x.npy"], arrays["y.npy"]
        windows = x.reshape(-1, 100, x.shape[1]).astype(np.float64)
        windows -= windows.mean(axis=1, keepdims=True)
        features = np.log1p(np.mean(windows * windows, axis=1))
        target = y.reshape(-1, 100, 5).mean(axis=1)
        mean, std, target_mean = features.mean(axis=0), features.std(axis=0), target.mean(axis=0)
        std[std == 0] = 1
        z = (features - mean) / std
        gram = np.einsum("ni,nj->ij", z, z) + np.eye(z.shape[1])
        cross = np.einsum("ni,nj->ij", z, target - target_mean)
        weights = np.linalg.solve(gram, cross)
        for key, value in (("mean", mean), ("std", std), ("target_mean", target_mean), ("weights", weights)):
            if not np.isfinite(value).all():
                raise ValueError("nonfinite fitted reference state")
            state[f"heads.{record['subject']}.{key}"] = np.ascontiguousarray(value)
    submission = args.output / "submission"
    submission.mkdir(parents=True)
    shutil.copyfile(TASK / "examples/model.py", submission / "model.py")
    (submission / "config.json").write_text(json.dumps({"reference": "fixed-100ms-ridge-v1", "ridge_alpha": 1.0}) + "\n")
    save_file(state, str(submission / "weights.safetensors"))
    receipt = {"scope": "Train-only fixed engineering reference; not an Agent run",
               "train_manifest_sha256": sha256(args.public_data / "train/manifest.json"),
               "submission_sha256": {name: sha256(submission / name) for name in ("model.py", "config.json", "weights.safetensors")}}
    (args.output / "training-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
