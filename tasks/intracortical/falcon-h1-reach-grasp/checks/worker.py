"""Untrusted-side H1 inference worker. Never import this in the scoring parent."""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import torch
from safetensors.torch import load_file

MAX_ELEMENTS = 10_000_000
MAX_LINE = 16_384
# Keep references before submitted model.py executes. Its module top level may
# replace attributes on torch.nn.Module or torch itself.
TORCH_MODULE = torch.nn.Module
TORCH_TENSOR = torch.Tensor
LOAD_STATE = TORCH_MODULE.load_state_dict
TRAIN = TORCH_MODULE.train
TENSOR_DETACH = TORCH_TENSOR.detach
TENSOR_CLONE = TORCH_TENSOR.clone
TORCH_EQUAL = torch.equal
TORCH_FINITE = torch.isfinite
TORCH_TENSOR_FACTORY = torch.tensor
TORCH_FLOAT32 = torch.float32
INFERENCE_MODE = torch.inference_mode


def reject_constant(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


def reject_duplicate(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def finite_tree(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite_tree(x) for x in value)
    if isinstance(value, dict):
        return all(finite_tree(x) for x in value.values())
    return value is None or isinstance(value, (str, int, bool))


def read_message():
    line = sys.stdin.buffer.readline(MAX_LINE + 1)
    if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ValueError("missing or oversized protocol message")
    message = json.loads(line, parse_constant=reject_constant, object_pairs_hook=reject_duplicate)
    if not isinstance(message, dict) or not isinstance(message.get("nonce"), str):
        raise ValueError("invalid protocol message")
    return message


def reply(nonce, kind, **fields):
    sys.stdout.write(json.dumps({"nonce": nonce, "kind": kind, **fields}, allow_nan=False,
                                separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    torch.set_num_threads(2)
    submitted = Path("/submission")
    config = json.loads((submitted / "config.json").read_text(encoding="utf-8"),
                        parse_constant=reject_constant, object_pairs_hook=reject_duplicate)
    if not isinstance(config, dict) or not finite_tree(config):
        raise ValueError("config must be a finite JSON object")
    state = load_file(str(submitted / "weights.safetensors"))
    if not state or sum(t.numel() for t in state.values()) > MAX_ELEMENTS:
        raise ValueError("saved numeric state exceeds 10M elements")
    if any(not (t.dtype.is_floating_point or t.dtype in
                (torch.uint8, torch.int8, torch.int16, torch.int32, torch.int64, torch.bool))
           or (t.is_floating_point() and not bool(TORCH_FINITE(t).all())) for t in state.values()):
        raise ValueError("saved state contains unsupported or nonfinite values")
    spec = importlib.util.spec_from_file_location("submitted_h1_model", submitted / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("model.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.Model(config)
    if not isinstance(model, TORCH_MODULE):
        raise ValueError("Model(config) must return torch.nn.Module")

    def registered_snapshot():
        tensors = {}
        parameter_elements = 0
        active_modules = set()

        def walk(current, prefix):
            nonlocal parameter_elements
            if not isinstance(current, TORCH_MODULE) or id(current) in active_modules:
                raise ValueError("invalid or cyclic module registry")
            active_modules.add(id(current))
            internals = object.__getattribute__(current, "__dict__")
            for registry_name in ("_parameters", "_buffers"):
                registry = internals.get(registry_name)
                if not isinstance(registry, dict):
                    raise ValueError("invalid registered tensor registry")
                for name, tensor in registry.items():
                    if tensor is None:
                        continue
                    if not isinstance(name, str) or not isinstance(tensor, TORCH_TENSOR):
                        raise ValueError("invalid registered tensor")
                    key = prefix + name
                    if key in tensors:
                        raise ValueError("duplicate registered tensor name")
                    if registry_name == "_parameters":
                        parameter_elements += math.prod(tuple(tensor.shape))
                    tensors[key] = TENSOR_CLONE(TENSOR_DETACH(tensor))
            children = internals.get("_modules")
            if not isinstance(children, dict):
                raise ValueError("invalid child module registry")
            for name, child in children.items():
                if child is not None:
                    if not isinstance(name, str):
                        raise ValueError("invalid child module name")
                    walk(child, prefix + name + ".")
            active_modules.remove(id(current))

        walk(model, "")
        return tensors, parameter_elements

    _, parameter_count = registered_snapshot()
    if parameter_count > MAX_ELEMENTS:
        raise ValueError("model parameters exceed 10M elements")
    LOAD_STATE(model, state, strict=True)
    TRAIN(model, False)
    frozen, parameter_count = registered_snapshot()
    if parameter_count > MAX_ELEMENTS or not set(state).issubset(frozen) or any(
            not TORCH_EQUAL(state[name], frozen[name]) for name in state):
        raise ValueError("loaded registered state differs from persisted state")

    def verify_state():
        current, count = registered_snapshot()
        if count > MAX_ELEMENTS:
            raise ValueError("model parameters exceed 10M elements")
        if set(current) != set(frozen) or any(
                not TORCH_EQUAL(current[name], tensor) for name, tensor in frozen.items()):
            raise ValueError("registered state changed during inference")

    while True:
        message = read_message()
        nonce, kind = message["nonce"], message.get("kind")
        if kind == "reset" and set(message) == {"nonce", "kind"}:
            with INFERENCE_MODE():
                if model.reset() is not None:
                    raise ValueError("reset must return None")
            verify_state()
            reply(nonce, "reset")
        elif kind == "step" and set(message) == {"nonce", "kind", "x", "trial_start"}:
            values = message["x"]
            if (not isinstance(values, list) or len(values) != 176 or
                    any(type(v) not in (float, int) or not math.isfinite(v) for v in values) or
                    type(message["trial_start"]) is not bool):
                raise ValueError("step requires finite 176-channel input and trial_start")
            x = TORCH_TENSOR_FACTORY(values, dtype=TORCH_FLOAT32)
            with INFERENCE_MODE():
                prediction = model(x, trial_start=message["trial_start"])
            if (not isinstance(prediction, TORCH_TENSOR) or
                    tuple(prediction.shape) != (7,) or prediction.dtype != TORCH_FLOAT32 or
                    not bool(TORCH_FINITE(prediction).all())):
                raise ValueError("forward must return finite float32[7]")
            verify_state()
            reply(nonce, "step", prediction=prediction.detach().cpu().tolist())
        elif kind == "end" and set(message) == {"nonce", "kind"}:
            verify_state()
            reply(nonce, "end")
            return
        else:
            raise ValueError("invalid protocol kind or fields")


if __name__ == "__main__":
    main()
