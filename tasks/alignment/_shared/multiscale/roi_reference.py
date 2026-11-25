"""Public-only, standalone reference policy for five language-region unit groups."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def specific_groups(z, target, count):
    """Allocate distinct units in ROI order by covariance with each region's specific response."""
    specific = target - target.mean(axis=1, keepdims=True)
    specific -= specific.mean(axis=0)
    relevance = z.T @ specific
    occupied = np.zeros(z.shape[1], dtype=bool)
    groups, strengths = [], []
    for col in relevance.T:
        order = np.argsort(-col, kind='stable')
        selected = order[~occupied[order]][:count]
        occupied[selected] = True
        groups.append(selected.tolist())
        strengths.append(col[selected].mean())
    return groups, float(np.mean(strengths))


def select(public, policy='roi_specific'):
    public = Path(public)
    protocol = json.loads((public / 'protocol.json').read_text())
    units = np.load(public / 'units.npy', mmap_mode='r', allow_pickle=False)
    _, layers, positions, width = units.shape
    rois, count = protocol['rois'], protocol['units_per_roi']
    if policy == 'random':
        rng = np.random.default_rng(73)
        layer, pos = int(rng.integers(layers)), int(rng.integers(positions))
        groups = rng.choice(width, len(rois) * count, replace=False).reshape(len(rois), count).tolist()
    elif policy == 'roi_specific':
        target = np.load(public / 'responses.npy', allow_pickle=False).mean(axis=1)
        best = -np.inf
        for block in range(layers):
            for p in range(positions):
                z = units[:, block, p, :].astype('float64')
                z -= z.mean(axis=0)
                scale = z.std(axis=0)
                z /= np.where(scale > 0, scale, 1.)
                proposal, strength = specific_groups(z, target, count)
                if strength > best:
                    best, layer, pos, groups = strength, block, p, proposal
    else:
        raise ValueError('unknown ROI selection policy')
    return {'packet_sha256': hashlib.sha256((public / 'manifest.json').read_bytes()).hexdigest(),
            'groups': {roi: {'layer': layer, 'position': protocol['positions'][pos], 'units': sorted(group)}
                       for roi, group in zip(rois, groups)}, 'predicted_edge_r': 0.0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('public', type=Path)
    parser.add_argument('feedback', help='frozen development transcript, unused by the reference')
    parser.add_argument('--policy', choices=('roi_specific', 'random'), default='roi_specific')
    args = parser.parse_args()
    print(json.dumps(select(args.public, args.policy), allow_nan=False))
