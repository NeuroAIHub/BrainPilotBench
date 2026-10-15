"""Untrusted-side offline inference. Only one subject's input is mounted."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import torch
from safetensors.torch import load_file

MODULE, TENSOR = torch.nn.Module, torch.Tensor
LOAD, TRAIN = MODULE.load_state_dict, MODULE.train
CLONE, DETACH, EQUAL = TENSOR.clone, TENSOR.detach, torch.equal
FINITE, INFERENCE = torch.isfinite, torch.inference_mode


def snapshot(model):
    saved, active = {}, set()
    count = 0

    def visit(current, prefix):
        nonlocal count
        if not isinstance(current, MODULE) or id(current) in active:
            raise ValueError("invalid module registry")
        active.add(id(current))
        internals = object.__getattribute__(current, "__dict__")
        for key in ("_parameters", "_buffers"):
            entries = internals.get(key)
            if not isinstance(entries, dict):
                raise ValueError("invalid registered tensor dictionary")
            for name, tensor in entries.items():
                if tensor is None:
                    continue
                if not isinstance(name, str) or not isinstance(tensor, TENSOR) or prefix + name in saved:
                    raise ValueError("invalid registered tensor")
                count += tensor.numel()
                if count > 10_000_000:
                    raise ValueError("registered numeric state exceeds 10M elements")
                saved[prefix + name] = CLONE(DETACH(tensor))
        children = internals.get("_modules")
        if not isinstance(children, dict):
            raise ValueError("invalid child registry")
        for name, child in children.items():
            if child is not None:
                visit(child, prefix + name + ".")
        active.remove(id(current))

    visit(model, "")
    return saved


def main():
    torch.set_num_threads(2)
    subject = sys.argv[1]
    channels = {"sub1": 62, "sub2": 48, "sub3": 64}[subject]
    submitted = Path("/submission")
    config = json.loads((submitted / "config.json").read_text())
    state = load_file(str(submitted / "weights.safetensors"))
    if not state or sum(t.numel() for t in state.values()) > 10_000_000:
        raise ValueError("persisted numeric state exceeds limit")
    spec = importlib.util.spec_from_file_location("submitted_bci_model", submitted / "model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.Model(config)
    if not isinstance(model, MODULE):
        raise ValueError("Model must be torch.nn.Module")
    snapshot(model)
    LOAD(model, state, strict=True)
    TRAIN(model, False)
    frozen = snapshot(model)
    if not set(state).issubset(frozen) or any(not EQUAL(state[k], frozen[k]) for k in state):
        raise ValueError("loaded state mismatch")
    x = np.load("/input.npy", allow_pickle=False)
    if x.dtype != np.int32 or x.ndim != 2 or x.shape[1] != channels or len(x) not in (79000, 200000):
        raise ValueError("invalid input interval")
    with INFERENCE():
        prediction = model(torch.tensor(x, dtype=torch.float32), subject_id=subject)
    if (not isinstance(prediction, TENSOR) or prediction.dtype != torch.float32 or
            tuple(prediction.shape) != (len(x), 5) or not bool(FINITE(prediction).all())):
        raise ValueError("forward must return finite float32[T,5]")
    after = snapshot(model)
    if set(after) != set(frozen) or any(not EQUAL(after[k], frozen[k]) for k in frozen):
        raise ValueError("registered state changed during inference")
    np.save(sys.stdout.buffer, prediction.detach().cpu().numpy(), allow_pickle=False)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
