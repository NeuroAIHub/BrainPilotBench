"""L4. Compare condition-dependent coactivation edges of five language ROIs and five MLP groups."""
from itertools import combinations

import numpy as np
import pandas as pd

from expansion.selection import stimulus_id
from real_brainscore.common import sha256
from . import CSV_SHA256, POSITIONS, fingerprint
from .analysis import pearson
from .preparation import Packet
from .roi_reference import specific_groups

ROIS = ['lang_LH_IFGorb', 'lang_LH_IFG', 'lang_LH_MFG', 'lang_LH_AntTemp', 'lang_LH_PostTemp']
EDGES = list(combinations(range(len(ROIS)), 2))


def search_halves(ids, conditions, split_key='L4-split'):
    """Balance D/S in both halves; the default key reproduces the reference-card split."""
    dev, held = [], []
    for condition in ('D', 'S'):
        order = sorted(np.flatnonzero(conditions == condition), key=lambda i: fingerprint([split_key, ids[i]]))
        dev.extend(order[:len(order) // 2])
        held.extend(order[len(order) // 2:])
    return dev, held


def edge_change(activity, condition, runs):
    edges = []
    for name in ('D', 'S'):
        rows = condition == name
        values = activity[rows].astype('float64').copy()
        blocks = runs[rows]
        for block in np.unique(blocks):
            group = blocks == block
            values[group] -= values[group].mean(axis=0)
        corr = np.corrcoef(values.T)
        edges.append(np.asarray([corr[i, j] for i, j in EDGES]))
    if not np.isfinite(edges).all():
        raise ValueError('undefined within-condition coupling')
    return edges[0] - edges[1]


def modules(x, train, target):
    """Give each ROI eight distinct units fitted on baseline sentences and participants only."""
    mu, sd = x[train].mean(axis=0, dtype='float64'), x[train].std(axis=0, dtype='float64')
    z = (x - mu) / np.where(sd > 0, sd, 1.)
    chosen, _ = specific_groups(z[train], target, 8)
    return np.column_stack([z[:, group].mean(axis=1) for group in chosen]), chosen


def network_task(directory, csv_file):
    if sha256(csv_file) != CSV_SHA256:
        raise ValueError('unexpected Tuckute source')
    packet = Packet(directory)
    df = pd.read_csv(csv_file, usecols=['roi', 'target_UID', 'item_id', 'response_target', 'cond', 'session_id', 'run_id'])
    df = df[df.roi.isin(ROIS)].copy()
    df['sid'] = df.item_id.map(stimulus_id)
    wide = df.pivot(index=['target_UID', 'sid'], columns='roi', values='response_target')[ROIS]
    train = packet.split['search']
    train_ids = [packet.meta['ids'][i] for i in train]
    y = np.mean([wide.loc[int(s)].loc[train_ids].to_numpy() for s in packet.meta['train_subjects']], axis=0)
    if not np.isfinite(y).all():
        raise ValueError('nonfinite regional training responses')
    test = np.asarray(packet.split['brain_test'])
    ids = [packet.meta['ids'][i] for i in test]
    trials = df[df.roi == ROIS[0]].set_index(['target_UID', 'sid'])
    cond = trials.loc[797].loc[ids]['cond'].to_numpy()
    dev, held = search_halves(ids, cond)
    cohorts = [('797', dev), ('841', held), ('880', held)]
    observations = []
    for subject, indices in cohorts:
        rows = [ids[i] for i in indices]
        timeline = trials.loc[int(subject)].loc[rows]
        labels = timeline.cond.to_numpy()
        if not np.array_equal(labels, cond[indices]):
            raise ValueError('misaligned experimental conditions')
        runs = (timeline.session_id.astype(str) + '/' + timeline.run_id.astype(str)).to_numpy()
        measured = wide.loc[int(subject)].loc[rows].to_numpy()
        observations.append((test[indices], labels, runs, edge_change(measured, labels, runs)))
    rng = np.random.default_rng(402)
    permutation = rng.permutation(len(ROIS))
    public, private = [], {}
    for layer in range(packet.arrays['units'].shape[1]):
        for p, position in enumerate(POSITIONS):
            signal, unit_ids = modules(packet.arrays['units'][:, layer, p, :], train, y)
            key = f'L{layer}-{position}'
            confirmation = {}
            for (subject, _), (rows, labels, runs, brain) in zip(cohorts, observations):
                predicted = edge_change(signal[rows], labels, runs)
                shuffled = edge_change(signal[rows][:, permutation], labels, runs)
                r = pearson(predicted, brain)
                if subject == '797':
                    public.append({'id': key, 'train_value': r, 'brain_edge_changes': brain.tolist(),
                                   'model_edge_changes': predicted.tolist(), 'unit_groups': unit_ids})
                else:
                    confirmation[subject] = {'r': r, 'permuted_roi_r': pearson(shuffled, brain),
                                             'brain_edge_changes': brain.tolist(), 'model_edge_changes': predicted.tolist()}
            private[key] = {'value': float(np.mean([v['r'] for v in confirmation.values()])), 'participants': confirmation}
    facts = {'source_sha256': CSV_SHA256, 'packet_sha256': packet.digest, 'roi_order': ROIS,
             'edge_order': [[ROIS[i], ROIS[j]] for i, j in EDGES], 'development': '797, 125 D + 125 S',
             'confirmation': '841 and 880, disjoint 125 D + 125 S',
             'module_training': '720 baseline sentences and five separate participants', 'roi_permutation': permutation.tolist()}
    return facts, public, private
