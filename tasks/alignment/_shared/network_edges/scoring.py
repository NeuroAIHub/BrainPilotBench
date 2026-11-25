"""Owner-side evaluation of frozen group-to-region assignments."""
from itertools import permutations
import math
from pathlib import Path

import numpy as np

from expansion.packet import verify
from multiscale import K, POSITIONS
from multiscale.analysis import checked_units, difference, pearson
from multiscale.networks import EDGES, ROIS, edge_change
from multiscale.roi_reference import select
from real_brainscore.common import read_json, sha256
from unit_transfer.session import freeze_and_replay
from . import METRIC, PROTOCOL


# The identity comes first. Relabeling regions only reorders the ten edges.
EDGE_PERMUTATIONS = np.array([
    [EDGES.index(tuple(sorted((order[i], order[j])))) for i, j in EDGES]
    for order in permutations(range(len(ROIS)))
])


class Split:
    def __init__(self, folder, sites):
        items = read_json(folder / 'items.json')
        self.ids, self.texts, self.subjects = (items[k] for k in ('ids', 'texts', 'subjects'))
        self.labels, self.runs = np.asarray(items['conditions']), np.asarray(items['runs'])
        self.units, self.y = (np.load(folder / (k + '.npy'), mmap_mode='r', allow_pickle=False)
                              for k in ('units', 'responses'))
        n, people = len(self.ids), len(self.subjects)
        if (not n or not people or len(self.texts) != n or len(set(self.ids)) != n or
                len(set(self.subjects)) != people or self.units.shape != (n, *sites) or
                self.y.shape != (n, people, len(ROIS)) or self.labels.shape != (n,) or
                self.runs.shape != (n, people) or not np.isfinite(self.y).all()):
            raise ValueError('inconsistent region data, stimulus alignment or model dimensions')

    def channels(self, group):
        site = self.units[:, group['layer'], POSITIONS.index(group['position']), :]
        return site[:, group['units']].astype('float64')


class Packet:
    def __init__(self, root):
        self.root = Path(root).resolve()
        public, _ = verify(self.root / 'public', PROTOCOL + '/public')
        owner, manifest = verify(self.root / 'owner', PROTOCOL + '/owner')
        self.identity, self.owner_identity = (sha256(p / 'manifest.json') for p in (public, owner))
        if manifest['public_sha256'] != self.identity:
            raise ValueError('owner packet belongs to a different public packet')
        self.protocol = read_json(public / 'protocol.json')
        p = self.protocol
        if (p['task'] != PROTOCOL or p['rois'] != ROIS or p['positions'] != list(POSITIONS) or
                p['units_per_roi'] != K or p['edges'] != [[ROIS[i], ROIS[j]] for i, j in EDGES]):
            raise ValueError('unexpected network protocol or edge order')
        sites = (p['model']['layers'], len(POSITIONS), p['model']['width'])
        self.train = Split(public, sites)
        self.splits = {name: Split(owner / name, sites) for name in ('dev', 'test')}
        parts = [self.train, *self.splits.values()]
        for key in ('ids', 'texts', 'subjects'):
            values = [item for part in parts for item in getattr(part, key)]
            if len(values) != len(set(values)):
                raise ValueError(f'overlapping or duplicate {key} in network splits')
        if set(self.train.labels) != {'B'}:
            raise ValueError('expected baseline condition in training')
        self.brain = {}
        for name, part in self.splits.items():
            if set(part.labels) != {'D', 'S'} or sum(part.labels == 'D') != sum(part.labels == 'S'):
                raise ValueError('expected balanced drive and suppress conditions')
            vectors = [edge_change(part.y[:, j, :], part.labels, part.runs[:, j])
                       for j in range(len(part.subjects))]
            if any(np.ptp(v) == 0 for v in vectors):
                raise ValueError('undefined human edge pattern')
            self.brain[name] = vectors

    def query_choice(self, data):
        required = {'packet_sha256', 'groups'}
        if not isinstance(data, dict) or set(data) not in (required, required | {'predicted_edge_r'}):
            raise ValueError('expected packet_sha256 and groups, optionally predicted_edge_r')
        if data['packet_sha256'] != self.identity:
            raise ValueError('choice belongs to a different packet or model')
        if not isinstance(data['groups'], dict) or set(data['groups']) != set(ROIS):
            raise ValueError('expected one named group for each of the five regions')
        _, layers, _, width = self.train.units.shape
        groups, occupied = {}, set()
        for roi in ROIS:
            group = data['groups'][roi]
            if not isinstance(group, dict) or set(group) != {'layer', 'position', 'units'}:
                raise ValueError('a group requires layer, position and units')
            group = checked_units(group, layers, width)
            channels = {(group['layer'], u) for u in group['units']}
            if channels & occupied:
                raise ValueError('native units must be distinct across regions, including across read positions')
            occupied.update(channels)
            groups[roi] = group
        return {'packet_sha256': self.identity, 'groups': groups}

    def choice(self, data):
        selection = self.query_choice(data)
        prediction = data.get('predicted_edge_r')
        if type(prediction) not in (int, float) or not -1 <= prediction <= 1 or not math.isfinite(prediction):
            raise ValueError('the final choice requires a finite predicted_edge_r in [-1, 1]')
        return {**selection, 'predicted_edge_r': round(prediction, 6)}

    def scores(self, name, choice, *, include_permutations=False):
        part = self.splits[name]
        signals = []
        for roi in ROIS:
            group = choice['groups'][roi]
            fit = self.train.channels(group)
            sd = fit.std(axis=0)
            z = (part.channels(group) - fit.mean(axis=0)) / np.where(sd > 0, sd, 1.)
            signals.append(z.mean(axis=1))
        signals = np.column_stack(signals)
        participants, nulls = {}, []
        for j, subject in enumerate(part.subjects):
            human = self.brain[name][j]
            try:
                with np.errstate(invalid='ignore', divide='ignore'):
                    model = edge_change(signals, part.labels, part.runs[:, j])
            except ValueError:  # A submitted group can be constant within a condition.
                model = None
            r = pearson(model, human) if model is not None else None
            participants[subject] = {'edge_r': r, 'brain_edge_changes': human.tolist(),
                                     'model_edge_changes': model.tolist() if model is not None else None}
            if include_permutations and r is not None:
                nulls.append([pearson(v, human) for v in model[EDGE_PERMUTATIONS]])
        rs = [row['edge_r'] for row in participants.values()]
        primary = None if None in rs else float(np.mean(rs))
        result = {METRIC: primary, 'participants': participants}
        if include_permutations and primary is not None:
            distribution = np.mean(nulls, axis=0)
            result['roi_permutation'] = {
                'n_labelings': len(distribution), 'mean_shuffled_r': float(distribution[1:].mean()),
                'one_sided_p': float(np.mean(distribution >= primary - 1e-12))}
        return result

    def development_feedback(self, choice):
        return {'dev_edge_r': self.scores('dev', choice)[METRIC]}


def benchmark_rows(packet):
    rows = {}
    for policy in ('roi_specific', 'random'):
        choice = packet.choice(select(packet.root / 'public', policy))
        rows[policy] = {'choice': choice, 'scores': packet.scores('test', choice, include_permutations=True)}
    return rows


def grade(packet, actor, choice, code):
    receipt, verified = freeze_and_replay(packet, actor, choice, code)
    selection = receipt['choice']
    scores = packet.scores('test', selection, include_permutations=True)
    primary = scores[METRIC]
    scores['prediction_abs_error'] = None if primary is None else abs(selection['predicted_edge_r'] - primary)
    references = benchmark_rows(packet)
    scores['gain_over_roi_specific'] = difference(primary, references['roi_specific']['scores'][METRIC])
    return {'model': packet.protocol['model']['id'], 'actor': actor, 'freeze': receipt, 'replay': verified,
            'results': {'agent': {'choice': selection, 'scores': scores}, **references}}
