"""MABe candidate entrypoint; executed only inside a restricted container."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


def main() -> None:
    input_path, context_path, model_dir, output_path = map(Path, sys.argv[1:])
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if set(context) != {"task", "mode", "count", "class_count"}:
        raise ValueError("context schema")
    mode, count = context["mode"], context["count"]
    if mode not in ("supervised", "representation") or type(count) is not int or not 1 <= count <= 16:
        raise ValueError("batch mode/count")
    if mode == "supervised" and (count != 1 or context["class_count"] != 4):
        raise ValueError("supervised batch schema")
    if mode == "representation" and context["class_count"] != 6:
        raise ValueError("representation context schema")
    inputs = []
    with np.load(input_path, allow_pickle=False) as source:
        expected = {f"keypoints_{i:03d}" for i in range(count)} | {f"scores_{i:03d}" for i in range(count)}
        if set(source.files) != expected:
            raise ValueError("input must contain only numeric pose features")
        for i in range(count):
            keypoints = source[f"keypoints_{i:03d}"]
            scores = source[f"scores_{i:03d}"]
            if keypoints.shape != (1800, 3, 12, 2) or keypoints.dtype != np.float32:
                raise ValueError("keypoint shape/dtype")
            if mode == "supervised" and (scores.shape != (1800, 3, 12) or scores.dtype != np.float32):
                raise ValueError("supervised confidence shape/dtype")
            if mode == "representation" and (scores.shape != (1800, 0) or scores.dtype != np.float32):
                raise ValueError("representation score placeholder")
            inputs.append((keypoints, scores))
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("mabe_submission", model_dir / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("model import")
    module = importlib.util.module_from_spec(spec)
    results = {}
    with open(os.devnull, "w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        spec.loader.exec_module(module)
        model = module.load_model(config, str(model_dir / "weights.npz"))
        for i, (keypoints, scores) in enumerate(inputs):
            method = model.predict_proba if mode == "supervised" else model.embed
            result = np.asarray(method(keypoints, scores, context))
            if not np.issubdtype(result.dtype, np.floating) or not np.isfinite(result).all():
                raise ValueError("nonfinite or nonfloat model output")
            if mode == "supervised":
                if result.shape != (1800, 4) or np.any((result < 0) | (result > 1)):
                    raise ValueError("invalid four-label probabilities")
            elif result.ndim != 2 or result.shape[0] != 1800 or not 1 <= result.shape[1] <= 128:
                raise ValueError("invalid embedding shape")
            results[f"output_{i:03d}"] = result.astype(np.float32)
    os.umask(0o077)
    with os.fdopen(os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        np.savez(stream, **results)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Candidate tracebacks, stdout, and stderr never reach the scorer.
        sys.exit(2)
