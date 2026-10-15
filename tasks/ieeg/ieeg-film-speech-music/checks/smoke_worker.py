#!/usr/bin/env python3
"""Check the normal isolated model path with one real public Train window."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from safetensors.numpy import save_file

from run import Worker, resolve_image

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-subject", required=True, type=Path)
    parser.add_argument("--image")
    args = parser.parse_args()
    with np.load(args.public_subject / "train.npz", allow_pickle=False) as data:
        window = data["x"][0]
    if window.ndim != 2 or window.shape[1] != 512:
        raise ValueError("The real public input is not a window")
    with tempfile.TemporaryDirectory(prefix="bpb-film-worker-smoke-") as temp:
        stage = Path(temp)
        stage.chmod(0o755)
        submission = stage / "submission"
        submission.mkdir(mode=0o755)
        shutil.copyfile(ROOT / "solution" / "model.py", submission / "model.py")
        (submission / "config.json").write_text(json.dumps({
            "feature_mean": [0.0] * 12, "feature_scale": [1.0] * 12}) + "\n")
        save_file({"linear.weight": np.zeros((1, 12), dtype=np.float32),
                   "linear.bias": np.zeros((1,), dtype=np.float32)},
                  str(submission / "weights.safetensors"))
        for path in submission.iterdir():
            path.chmod(0o644)
        worker = Worker(resolve_image(args.image), submission, window.shape[0])
        try:
            value = worker.predict(window, args.public_subject.name)
        finally:
            worker.close()
    if value != 0.5:
        raise ValueError("The zero-weight model did not return probability 0.5")
    print(json.dumps({"status": "real_train_window_isolated_inference_passed",
                      "channels": window.shape[0], "probability": value}))


if __name__ == "__main__":
    main()
