#!/usr/bin/env python3
"""Container worker: see only one causal prefix at a time, never target labels."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, choices=(0, 1, 2), required=True)
    args = parser.parse_args()
    folder = Path("/artifact") / f"seed-{args.seed}"
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    weights = json.loads((folder / "weights.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("candidate_model", folder / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load model")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    model = None
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("op") == "new_participant":
            with contextlib.redirect_stdout(io.StringIO()):
                model = module.Model(config, weights)
            sys.stdout.write('{"ready":true}\n')
            sys.stdout.flush()
            continue
        operation = request.get("op")
        if operation not in ("predict", "predict_byte") or model is None:
            raise ValueError("Invalid worker protocol")
        prefix = request.get("prefix")
        if type(prefix) is not str or not prefix.endswith("<<"):
            raise ValueError("Invalid causal prefix")
        if operation == "predict_byte":
            history = request.get("response_prefix_bytes")
            if type(history) is not list or len(history) > 4096 or any(type(b) is not int or not 0 <= b <= 255 for b in history):
                raise ValueError("Invalid prior response bytes")
            with contextlib.redirect_stdout(io.StringIO()):
                probabilities = model.predict_next(prefix, bytes(history))
            response = {"response_id": request["response_id"], "step": request["step"],
                        "probabilities": probabilities}
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                probabilities = model.predict(prefix)
            response = {"response_id": request["response_id"], "probabilities": probabilities}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
