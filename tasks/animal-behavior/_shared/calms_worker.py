"""Untrusted-container entrypoint. Its input contains no ground truth."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


def main() -> None:
    input_path, context_path, model_path, output_path = map(Path, sys.argv[1:])
    with np.load(input_path, allow_pickle=False) as source:
        if set(source.files) != {"keypoints", "scores"}:
            raise ValueError("feature schema")
        keypoints, scores = source["keypoints"], source["scores"]
    if keypoints.ndim != 4 or keypoints.shape[1:] != (2, 2, 7):
        raise ValueError("keypoint shape")
    if scores.shape != (len(keypoints), 2, 7):
        raise ValueError("score shape")
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if set(context) != {"task", "group", "class_count"}:
        raise ValueError("context schema")
    config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("calms_submission", model_path / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("model import")
    module = importlib.util.module_from_spec(spec)
    # Candidate printouts never enter the trusted JSON or numeric result channel.
    with open(os.devnull, "w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        spec.loader.exec_module(module)
        model = module.load_model(config, str(model_path / "weights.npz"))
        probabilities = np.asarray(model.predict_proba(keypoints, scores, context))
    if probabilities.shape != (len(keypoints), context["class_count"]):
        raise ValueError("prediction shape")
    if not np.issubdtype(probabilities.dtype, np.floating):
        raise ValueError("prediction dtype")
    if not np.isfinite(probabilities).all() or np.any((probabilities < 0) | (probabilities > 1)):
        raise ValueError("prediction values")
    if not np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-5):
        raise ValueError("prediction normalization")
    os.umask(0o077)
    with os.fdopen(os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        np.save(stream, probabilities.astype(np.float32))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Do not expose model tracebacks or contents of private features.
        sys.exit(2)
