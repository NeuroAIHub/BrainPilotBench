"""Load and infer a submitted EEG model inside an external Docker sandbox.

Never import this module in the trusted scoring parent. The worker sees only
one seed's three required files, the x-only validation array and an output dir.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file

MAX_ELEMENTS = 10_000_000


def no_constant(text: str):
    raise ValueError(f"nonfinite JSON constant in config: {text}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--x", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--channels", required=True, type=int)
    parser.add_argument("--time-points", required=True, type=int)
    parser.add_argument("--outputs", required=True, type=int)
    parser.add_argument("--kind", choices=("classification", "regression"), required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    submitted = Path(args.submission)
    config = json.loads((submitted / "config.json").read_text(encoding="utf-8"), parse_constant=no_constant)
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    state = load_file(str(submitted / "weights.safetensors"))
    if not state or sum(t.numel() for t in state.values()) > MAX_ELEMENTS:
        raise ValueError("persisted numerical state exceeds the 10M-element limit")
    if any(t.is_floating_point() and not torch.isfinite(t).all() for t in state.values()):
        raise ValueError("persisted state contains nonfinite values")
    spec = importlib.util.spec_from_file_location("submitted_eeg_model", submitted / "model.py")
    if spec is None or spec.loader is None:
        raise ValueError("model.py cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.Model(config)
    if not isinstance(model, torch.nn.Module):
        raise ValueError("Model(config) must return a torch.nn.Module")
    if sum(p.numel() for p in torch.nn.Module.parameters(model)) > MAX_ELEMENTS:
        raise ValueError("model parameters exceed the 10M-element limit")
    torch.nn.Module.load_state_dict(model, state, strict=True)
    torch.nn.Module.train(model, False)
    x = np.load(args.x, mmap_mode="r", allow_pickle=False)
    if (x.ndim != 3 or tuple(x.shape[1:]) != (args.channels, args.time_points)
            or x.dtype not in (np.dtype("float32"), np.dtype("float64"))):
        raise ValueError("validation input shape or dtype differs from the frozen task")
    predictions = []
    with torch.inference_mode():
        for offset in range(0, len(x), 64):
            batch = np.array(x[offset:offset + 64], dtype=np.float32, copy=True)
            if not np.isfinite(batch).all():
                raise ValueError("validation input contains nonfinite values")
            output = model(torch.from_numpy(batch))
            if (not isinstance(output, torch.Tensor) or
                    tuple(output.shape) != (len(batch), args.outputs) or
                    not torch.isfinite(output).all()):
                raise ValueError("model output shape or values are invalid")
            if args.kind == "classification":
                if ((output < -1e-6).any() or (output > 1 + 1e-6).any() or
                        not torch.allclose(output.sum(-1), torch.ones(len(batch)), atol=1e-4, rtol=1e-4)):
                    raise ValueError("classification output must be normalized probabilities")
            predictions.append(output.detach().cpu().numpy().astype(np.float32, copy=False))
    after = torch.nn.Module.state_dict(model)
    if set(state) != set(after) or any(not torch.equal(t, after[name]) for name, t in state.items()):
        raise ValueError("registered model state changed during inference")
    np.save(args.output, np.concatenate(predictions, axis=0), allow_pickle=False)


if __name__ == "__main__":
    main()
