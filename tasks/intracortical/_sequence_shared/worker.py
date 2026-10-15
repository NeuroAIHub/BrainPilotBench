"""Untrusted-side H2/B1 worker. The scoring parent never imports submitted code."""

from __future__ import annotations

import base64
from io import BytesIO
import importlib.util
import json
import math
from pathlib import Path
import sys
import zlib

import numpy as np
import torch
from safetensors.torch import load_file


MODULE = torch.nn.Module
TENSOR = torch.Tensor
LOAD_STATE = MODULE.load_state_dict
TRAIN = MODULE.train
DETACH = TENSOR.detach
CLONE = TENSOR.clone
EQUAL = torch.equal
FINITE = torch.isfinite
TORCH_TENSOR = torch.tensor
TORCH_F32 = torch.float32
INFERENCE_MODE = torch.inference_mode
MAX_ELEMENTS = 10_000_000
MAX_LINE = 16_384


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


def read_message():
    line = sys.stdin.buffer.readline(MAX_LINE + 1)
    if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ValueError("missing or oversized protocol message")
    message = json.loads(line, object_pairs_hook=unique, parse_constant=reject_constant)
    if not isinstance(message, dict) or not isinstance(message.get("nonce"), str):
        raise ValueError("invalid protocol message")
    return message


def reply(nonce, kind, **fields):
    sys.stdout.write(json.dumps({"nonce": nonce, "kind": kind, **fields},
                                allow_nan=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def snapshot(model):
    tensors = {}
    parameter_elements = 0
    registered_elements = 0
    active = set()

    def walk(current, prefix):
        nonlocal parameter_elements, registered_elements
        if not isinstance(current, MODULE) or id(current) in active:
            raise ValueError("invalid or cyclic module registry")
        active.add(id(current))
        internals = object.__getattribute__(current, "__dict__")
        for field in ("_parameters", "_buffers"):
            registry = internals.get(field)
            if not isinstance(registry, dict):
                raise ValueError("invalid registered tensor registry")
            for name, tensor in registry.items():
                if tensor is None:
                    continue
                if not isinstance(name, str) or not isinstance(tensor, TENSOR):
                    raise ValueError("invalid registered tensor")
                key = prefix + name
                if key in tensors:
                    raise ValueError("duplicate registered tensor")
                registered_elements += math.prod(tuple(tensor.shape))
                if registered_elements > MAX_ELEMENTS:
                    raise ValueError("registered numeric state exceeds 10M elements")
                if field == "_parameters":
                    parameter_elements += math.prod(tuple(tensor.shape))
                tensors[key] = CLONE(DETACH(tensor))
        children = internals.get("_modules")
        if not isinstance(children, dict):
            raise ValueError("invalid child module registry")
        for name, child in children.items():
            if child is not None:
                if not isinstance(name, str):
                    raise ValueError("invalid child module name")
                walk(child, prefix + name + ".")
        active.remove(id(current))

    walk(model, "")
    return tensors, parameter_elements, registered_elements


def main():
    task = sys.argv[1]
    if task not in ("h2", "b1"):
        raise ValueError("unknown sequence task")
    torch.set_num_threads(2)
    submission = Path("/submission")
    config = json.loads((submission / "config.json").read_text(), object_pairs_hook=unique,
                        parse_constant=reject_constant)
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    state = load_file(str(submission / "weights.safetensors"))
    if not state or sum(t.numel() for t in state.values()) > MAX_ELEMENTS or any(
            t.is_floating_point() and not bool(FINITE(t).all()) for t in state.values()):
        raise ValueError("saved state exceeds 10M elements or is nonfinite")
    spec = importlib.util.spec_from_file_location(f"submitted_{task}_model", submission / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("model.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.Model(config)
    if not isinstance(model, MODULE):
        raise ValueError("Model(config) must return torch.nn.Module")
    _, count, _ = snapshot(model)
    if count > MAX_ELEMENTS:
        raise ValueError("registered parameters exceed 10M elements")
    LOAD_STATE(model, state, strict=True)
    TRAIN(model, False)
    frozen, count, _ = snapshot(model)
    if count > MAX_ELEMENTS or not set(state).issubset(frozen) or any(
            not EQUAL(state[name], frozen[name]) for name in state):
        raise ValueError("loaded state differs from submitted state")

    def verify_state():
        current, count, _ = snapshot(model)
        if count > MAX_ELEMENTS or set(current) != set(frozen) or any(
                not EQUAL(value, frozen[name]) for name, value in current.items()):
            raise ValueError("registered model state changed during inference")

    while True:
        message = read_message()
        nonce, kind = message["nonce"], message.get("kind")
        if kind == "reset" and task == "h2" and set(message) == {"nonce", "kind"}:
            with INFERENCE_MODE():
                result = model.reset()
            if result is not None:
                raise ValueError("reset must return None")
            verify_state()
            reply(nonce, kind)
        elif kind == "observe" and task == "h2" and set(message) == {"nonce", "kind", "x", "trial_start"}:
            values = message["x"]
            if (not isinstance(values, list) or len(values) != 192 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or
                    type(message["trial_start"]) is not bool):
                raise ValueError("observe requires one finite float32[192] bin")
            x = TORCH_TENSOR(values, dtype=TORCH_F32)
            with INFERENCE_MODE():
                result = model.observe(x, trial_start=message["trial_start"])
            if result is not None:
                raise ValueError("observe must return None")
            verify_state()
            reply(nonce, kind)
        elif kind == "finish" and task == "h2" and set(message) == {"nonce", "kind"}:
            with INFERENCE_MODE():
                prediction = model.finish_trial()
            if not isinstance(prediction, str) or len(prediction.encode("utf-8")) > 2048:
                raise ValueError("finish_trial must return a bounded string")
            verify_state()
            reply(nonce, kind, prediction=prediction)
        elif kind == "predict" and task == "b1" and set(message) == {"nonce", "kind"}:
            # Only this complete motif is mounted; no future motifs, labels, or masks.
            neural = np.load("/input.npy", allow_pickle=False)
            if neural.shape != (27000, 85) or neural.dtype != np.uint8:
                raise ValueError("B1 motif input shape differs")
            x = TORCH_TENSOR(neural.astype(np.float32, copy=False), dtype=TORCH_F32)
            with INFERENCE_MODE():
                prediction = model(x)
            if (not isinstance(prediction, TENSOR) or tuple(prediction.shape) != (880, 158) or
                    prediction.dtype != TORCH_F32 or not bool(FINITE(prediction).all())):
                raise ValueError("B1 forward must return finite float32[880,158]")
            verify_state()
            buffer = BytesIO()
            np.save(buffer, DETACH(prediction).cpu().numpy(), allow_pickle=False)
            encoded = base64.b64encode(zlib.compress(buffer.getvalue(), level=1)).decode("ascii")
            if len(encoded) > 1_100_000:
                raise ValueError("B1 output exceeds bounded protocol")
            reply(nonce, kind, prediction_zlib_npy_b64=encoded)
        elif kind == "end" and set(message) == {"nonce", "kind"}:
            verify_state()
            reply(nonce, kind)
            return
        else:
            raise ValueError("invalid protocol kind or fields")


if __name__ == "__main__":
    main()
