"""Owner-only fixed ridge readouts; no submission code runs in the scorer."""
from pathlib import Path

import numpy as np

from expansion.packet import verify
from multiscale.analysis import checked_units, difference, pearson, readout
from real_brainscore.common import read_json, sha256
from . import POSITIONS, PROTOCOL


class Split:
    def __init__(self, path):
        self.items = read_json(path / 'items.json')
        self.units, self.controls, self.y = [np.load(path / f'{name}.npy', allow_pickle=False, mmap_mode='r')
                                            for name in ('units', 'controls', 'responses')]

    def design(self, choice):
        if choice is None:
            return self.controls
        site = self.units[:, choice['layer'], POSITIONS.index(choice['position']), :]
        return np.column_stack((self.controls, site[:, choice['units']]))


def predictions(train, target, choice, per_person):
    x = np.concatenate((train.design(choice), target.design(choice)))
    fit = slice(0, len(train.y))
    test = slice(len(train.y), None)
    # Tuckute predictions are shared across new participants. Pereira fits
    # one readout per participant using only that person's training passages.
    ys = train.y.T if per_person else [train.y.mean(axis=1)]
    if per_person and train.items['subjects'] != target.items['subjects']:
        raise ValueError('Pereira readout and measurement participant axes differ')
    return np.stack([readout(x, y, fit, test)['predictions'] for y in ys], axis=1)


class Packet:
    def __init__(self, root):
        self.root = Path(root).resolve()
        public, _ = verify(self.root / 'public', PROTOCOL + '/public')
        owner, manifest = verify(self.root / 'owner', PROTOCOL + '/owner')
        self.identity = sha256(public / 'manifest.json')
        if manifest['public_sha256'] != self.identity:
            raise ValueError('public and owner packets differ')
        self.owner_identity = sha256(owner / 'manifest.json')
        self.protocol = read_json(public / 'protocol.json')
        self.train = Split(public)
        self.splits = {name: Split(owner / name) for name in ('dev', 'search', 'modify', 'pereira_fit', 'pereira')}

    def choice(self, data):
        if not isinstance(data, dict) or set(data) != {'packet_sha256', 'layer', 'position', 'units'}:
            raise ValueError('expected packet_sha256, layer, position and units')
        if data['packet_sha256'] != self.identity:
            raise ValueError('choice belongs to a different packet or model')
        _, layers, _, width = self.train.units.shape
        return {'packet_sha256': self.identity, **checked_units(data, layers, width)}

    query_choice = choice

    def development_feedback(self, choice):
        return {'dev_delta_r': self.scores('dev', choice)['delta_r']}

    def scores(self, name, choice):
        target = self.splits[name]
        per_person = name == 'pereira'
        train = self.splits['pereira_fit'] if per_person else self.train
        base = predictions(train, target, None, per_person)
        joint = predictions(train, target, choice, per_person) if choice is not None else base
        labels = np.asarray(target.items['conditions'])
        cells, increments = {}, []
        for j, person in enumerate(target.items['subjects']):
            cells[person] = {}
            for condition in sorted(set(labels)):
                mask = labels == condition
                y = target.y[mask, j]
                k = j if per_person else 0
                if np.ptp(y) == 0 or np.ptp(base[mask, k]) == 0:
                    raise ValueError(f'undefined control or brain variance in {name}/{person}/{condition}')
                base_r = pearson(base[mask, k], y)
                joint_r = pearson(joint[mask, k], y) if np.ptp(joint[mask, k]) > 0 else None
                delta = difference(joint_r, base_r)
                cells[person][condition] = {'n': int(mask.sum()), 'control_r': base_r, 'joint_r': joint_r,
                                            'delta_r': delta}
                increments.append(delta)
        return {'delta_r': None if None in increments else float(np.mean(increments)), 'cells': cells}

    def check_controls(self):
        for name in ('dev', 'search', 'modify', 'pereira'):
            self.scores(name, None)

    def results(self, choice):
        return {name: self.scores(name, choice) for name in ('search', 'modify', 'pereira')}
