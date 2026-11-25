"""Two fixed, public-data-only selection policies. Also a runnable strategy example."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def select(public, strategy):
    public = Path(public)
    spec = json.loads((public / 'protocol.json').read_text())
    x = np.load(public / 'units.npy', mmap_mode='r', allow_pickle=False)
    _, layers, positions, width = x.shape
    k = spec['n_units']
    if strategy == 'random':
        rng = np.random.default_rng(73)
        layer, pos = int(rng.integers(layers)), int(rng.integers(positions))
        units = rng.choice(width, k, replace=False)
    elif strategy == 'top8':
        y = np.load(public / 'responses.npy', allow_pickle=False).mean(axis=1)
        y -= y.mean()
        best = -1.
        for block in range(layers):
            for p in range(positions):
                centered = x[:, block, p, :].astype('float64')
                centered -= centered.mean(axis=0)
                denom = np.linalg.norm(centered, axis=0) * np.linalg.norm(y)
                corr = np.divide(np.abs(y @ centered), denom, out=np.zeros(width), where=denom > 0)
                selected = np.argsort(-corr, kind='stable')[:k]
                score = corr[selected].mean()
                if score > best:
                    best, layer, pos, units = score, block, p, selected
    else:
        raise ValueError('unknown reference strategy')
    return {'packet_sha256': hashlib.sha256((public / 'manifest.json').read_bytes()).hexdigest(),
            'layer': layer, 'position': spec['positions'][pos], 'units': sorted(units.tolist())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('public', type=Path)
    parser.add_argument('feedback', type=Path, help='query transcript, unused by the fixed policies')
    parser.add_argument('--strategy', choices=('random', 'top8'), default='top8')
    args = parser.parse_args()
    print(json.dumps(select(args.public, args.strategy), allow_nan=False))
