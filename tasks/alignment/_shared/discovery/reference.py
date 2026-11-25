"""Standalone NumPy reference strategies. Only public training inputs are read."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def domain_curves(labels, values):
    return np.stack([values[labels == d].mean(axis=0, dtype='float64') for d in range(9)])


def correlations(curves, human):
    """Nine domains on the first axis, arbitrary unit axes afterwards."""
    x = curves - curves.mean(axis=0)
    y = human - human.mean()
    norm = np.linalg.norm(x, axis=0) * np.linalg.norm(y)
    return np.divide(np.tensordot(y, x, axes=1), norm, out=np.full(norm.shape, np.nan), where=norm > 0)


def cell_mapping(public, spec, random):
    words = json.loads((public / 'words.json').read_text())
    x = np.load(public / 'units.npy', mmap_mode='r', allow_pickle=False)
    curves = domain_curves(np.asarray(words['domains']), x)
    trials = np.load(public / 'trials.npy', allow_pickle=False)
    rates = np.load(public / 'rates.npy', allow_pickle=False)
    result = {}
    rng = np.random.default_rng(73)
    for i, cell in enumerate(spec['cells']):
        mask = trials[:, 0] == i
        r = correlations(curves, domain_curves(trials[mask, 2], rates[mask]))
        layer, unit = np.unravel_index(np.nanargmax(r), r.shape)
        if random:
            unit = rng.integers(x.shape[-1])
        result[cell] = {'layer': int(layer), 'unit': int(unit)}
    return {'mapping': result}


def circuit(public, spec, random):
    rng = np.random.default_rng(73)
    proxy = np.load(public / 'training_gain_proxy.npy', mmap_mode='r', allow_pickle=False)
    k = spec['units_per_path']
    if random:
        pair = int(rng.integers(len(spec['layer_pairs'])))
        head = int(rng.integers(proxy.shape[2]))
        units = rng.choice(proxy.shape[3], k, replace=False)
    else:
        best = -np.inf
        for i in range(len(spec['layer_pairs'])):
            gains = proxy[:, i].mean(axis=0, dtype='float64')
            gains -= gains.mean(axis=0)
            ordered = np.argsort(-gains, axis=1, kind='stable')[:, :k]
            totals = np.take_along_axis(gains, ordered, axis=1).sum(axis=1)
            h = int(np.argmax(totals))
            if totals[h] > best:
                best, pair, head, units = totals[h], i, h, ordered[h]
    sender, receiver = spec['layer_pairs'][pair]
    return {'falsifier': 'An equal or greater mean gain from the other heads contradicts a positive path-specific effect.',
            'path': {'sender_layer': sender, 'head': head, 'receiver_layer': receiver,
                     'units': sorted(map(int, units))}}


def select(public, policy='train_top'):
    public = Path(public)
    spec = json.loads((public / 'protocol.json').read_text())
    if policy not in ('train_top', 'random'):
        raise ValueError('unknown reference policy')
    choose = cell_mapping if 'cells' in spec else circuit
    return {'packet_sha256': hashlib.sha256((public / 'manifest.json').read_bytes()).hexdigest(),
            **choose(public, spec, policy == 'random'), 'predicted_score': 0.0}


if __name__ == '__main__':
    print(json.dumps(select(sys.argv[1]), allow_nan=False))
