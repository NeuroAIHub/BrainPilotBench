"""Isolated single-window film model worker. The trusted host never imports model.py."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import torch
from safetensors.torch import load_file

SUBMISSION = Path("/submission")
MAX_LINE = 8_000_000
Module = torch.nn.Module
Tensor = torch.Tensor
tensor_factory = torch.from_numpy
finite = torch.isfinite
load_state = Module.load_state_dict
equal = torch.equal
inference_mode = torch.inference_mode


def no_constant(value):
    raise ValueError(f"Nonfinite JSON constant: {value}")


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def message():
    line = sys.stdin.buffer.readline(MAX_LINE + 1)
    if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ValueError("Missing or oversized request")
    item = json.loads(line, parse_constant=no_constant, object_pairs_hook=unique)
    if not isinstance(item, dict) or set(item) != {"nonce", "subject_id", "channels", "window_b64"}:
        raise ValueError("Invalid request fields")
    return item


def main():
    torch.set_num_threads(2)
    config = json.loads((SUBMISSION / "config.json").read_text(),
                        parse_constant=no_constant, object_pairs_hook=unique)
    if not isinstance(config, dict):
        raise ValueError("Config must be an object")
    state = load_file(str(SUBMISSION / "weights.safetensors"))
    if sum(t.numel() for t in state.values()) > 10_000_000:
        raise ValueError("Saved state exceeds 10M values")
    if any(t.is_floating_point() and not bool(finite(t).all()) for t in state.values()):
        raise ValueError("Saved state has nonfinite values")
    spec = importlib.util.spec_from_file_location("film_model", SUBMISSION / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    while True:
        item = message()
        channels = item["channels"]
        if (not isinstance(item["nonce"], str) or not isinstance(item["subject_id"], str)
                or type(channels) is not int or not 1 <= channels <= 1024
                or not isinstance(item["window_b64"], str)):
            raise ValueError("Invalid window identity or channel count")
        binary = base64.b64decode(item["window_b64"], validate=True)
        if len(binary) != channels * 512 * 4:
            raise ValueError("Window byte count differs from float32[C,512]")
        array = np.frombuffer(binary, dtype="<f4").reshape(channels, 512).copy()
        if not np.isfinite(array).all():
            raise ValueError("Window has nonfinite values")
        model = module.Model(copy.deepcopy(config))
        if not isinstance(model, Module):
            raise ValueError("Model(config) must be an nn.Module")
        if sum(p.numel() for p in model.parameters()) > 10_000_000:
            raise ValueError("Model exceeds 10M parameters")
        load_state(model, state, strict=True)
        model.eval()
        before = {name: tensor.detach().clone() for name, tensor in model.state_dict().items()}
        with inference_mode():
            prediction = model(tensor_factory(array), item["subject_id"])
        if (not isinstance(prediction, Tensor) or prediction.dtype != torch.float32
                or prediction.ndim != 0 or not bool(finite(prediction).all())):
            raise ValueError("forward must return one finite float32 tensor")
        after = model.state_dict()
        if set(before) != set(after) or any(not equal(before[name], after[name]) for name in before):
            raise ValueError("Registered model state changed during inference")
        value = float(prediction.item())
        if not 0 <= value <= 1 or not math.isfinite(value):
            raise ValueError("forward must return a speech probability in [0,1]")
        sys.stdout.write(json.dumps({"nonce": item["nonce"], "probability": value},
                                    separators=(",", ":"), allow_nan=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
