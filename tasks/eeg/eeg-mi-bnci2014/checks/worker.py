"""Untrusted program inference: caller must isolate this process externally."""
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
import torch
from safetensors.torch import load_file

p = argparse.ArgumentParser()
p.add_argument('--submission', required=True)
p.add_argument('--x', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
torch.set_num_threads(2)
d = Path(a.submission)
state = load_file(str(d/'weights.safetensors'))
if not state or sum(t.numel() for t in state.values()) > 10_000_000 or any(not torch.isfinite(t).all() for t in state.values()):
    raise ValueError('Invalid saved numeric state')
spec = importlib.util.spec_from_file_location('submitted_model', d/'model.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
model = module.Model(json.loads((d/'config.json').read_text()))
if not isinstance(model, torch.nn.Module) or sum(t.numel() for t in torch.nn.Module.parameters(model)) > 10_000_000:
    raise ValueError('Invalid model type or parameter count')
torch.nn.Module.load_state_dict(model, state, strict=True)
torch.nn.Module.train(model, False)
x = np.load(a.x, allow_pickle=False)
pred = []
with torch.inference_mode():
    for offset in range(0, len(x), 64):
        pred.append(model(torch.from_numpy(x[offset:offset+64])).cpu().numpy())
after = torch.nn.Module.state_dict(model)
if set(state) != set(after) or any(not torch.equal(v, after[k]) for k,v in state.items()):
    raise ValueError('Registered state changed during inference')
np.save(a.output, np.concatenate(pred), allow_pickle=False)
