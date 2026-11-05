"""Container-only entrypoint for one RGB sequence and one frozen tracker."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys

import numpy as np


def main() -> None:
    os.umask(0o077)
    with np.load("/input/features.npz", allow_pickle=False) as source:
        if set(source.files) != {"frames"}:
            raise ValueError("feature schema")
        frames = source["frames"]
    if (frames.ndim != 4 or frames.dtype != np.uint8 or frames.shape[-1] != 3
            or not 0 < len(frames) <= 128 or frames.nbytes > 512_000_000 - 4096):
        raise ValueError("RGB feature shape")
    context = {"task_id": "sam2mice-multi-animal-tracking",
               "width": frames.shape[2], "height": frames.shape[1]}
    model_root = Path("/model")
    config = json.loads((model_root / "config.json").read_text())
    spec = importlib.util.spec_from_file_location("tracking_submission", model_root / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("model import")
    module = importlib.util.module_from_spec(spec)
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        spec.loader.exec_module(module)
        model = module.load_model(config, str(model_root / "weights.npz"))
        detections = np.asarray(model.predict(frames, context))
    if (detections.ndim != 2 or detections.shape[1] != 6
            or detections.dtype.kind != "f" or len(detections) > len(frames) * 64
            or not np.isfinite(detections).all()):
        raise ValueError("tracking output shape")
    indices, identities, boxes = detections[:, 0], detections[:, 1], detections[:, 2:]
    if (np.any(indices != np.floor(indices)) or np.any((indices < 0) | (indices >= len(frames)))
            or np.any(identities != np.floor(identities))
            or np.any((identities < 0) | (identities > 2**31 - 1))
            or np.any((boxes < 0) | (boxes > 1))
            or np.any(boxes[:, 2:] <= boxes[:, :2])
            or len(np.unique(detections[:, :2], axis=0)) != len(detections)):
        raise ValueError("tracking output values")
    if len(detections) and np.max(np.bincount(indices.astype(np.int64), minlength=len(frames))) > 64:
        raise ValueError("too many detections in one frame")
    if len(np.unique(identities)) > 1024:
        raise ValueError("too many distinct tracks in one sequence")
    # Serialize validated numeric output before touching the sole writable file.
    # The host reads it only after this container exits successfully.
    encoded = io.BytesIO()
    np.save(encoded, detections.astype(np.float64))
    with os.fdopen(os.open("/output/predictions.npy", os.O_WRONLY | os.O_TRUNC), "wb") as writer:
        writer.write(encoded.getvalue())
        writer.flush()
        os.fsync(writer.fileno())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(2)
