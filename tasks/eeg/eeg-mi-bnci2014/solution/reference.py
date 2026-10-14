"""Fixed CPU ridge reference. Fits train only; no validation-guided selection."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
import torch
from safetensors.torch import save_file
from model import Model

p = argparse.ArgumentParser()
p.add_argument('--data', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
torch.set_num_threads(2)
out = Path(a.output)
with np.load(Path(a.data)/'train.npz', allow_pickle=False) as data:
    x, y = torch.tensor(data['x']), torch.tensor(data['y'], dtype=torch.long)
if x.shape != (2880, 22, 480) or y.shape != (2880,):
    raise ValueError('Unexpected frozen train shape')
for seed in range(3):
    torch.manual_seed(seed)
    model = Model({})
    features = torch.cat([model.features(b) for b in x.split(128)]).double()
    model.mean.copy_(features.mean(0))
    model.scale.copy_(features.std(0, correction=0).clamp_min(1e-6))
    z = (features - model.mean.double()) / model.scale.double()
    z = torch.cat([z, torch.ones(len(z), 1)], dim=1)
    targets = torch.nn.functional.one_hot(y, 4).double()
    # One fixed regularization coefficient; identical seeds are expected for this solver.
    model.coef.copy_(torch.linalg.solve(z.T @ z + torch.eye(254) * 10, z.T @ targets))
    d = out/'submission'/f'seed-{seed}'
    d.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__).with_name('model.py'), d/'model.py')
    (d/'config.json').write_text(json.dumps({'seed': seed, 'ridge': 10, 'fit': 'train-only'}))
    save_file(model.state_dict(), str(d/'weights.safetensors'))
(out/'report.md').write_text('# Fixed reference\n\nTrain-only log-variance/correlation ridge classifier; no validation tuning. Three deterministic saved states are one reference submission, not three Agent episodes. Public validation only.\n')
hashes = {str(f.relative_to(out)): hashlib.file_digest(f.open('rb'), 'sha256').hexdigest() for f in sorted((out/'submission').rglob('*')) if f.is_file()}
(out.parent/'reference-freeze.json').write_text(json.dumps(hashes, indent=2)+'\n')
print(json.dumps({'train_samples': len(x), 'seeds': [0,1,2], 'private_test': False}))
