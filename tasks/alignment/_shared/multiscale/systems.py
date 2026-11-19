"""L5. A nine-system model of whole-brain reorganization and avoidance in ToPS Study 3."""
from pathlib import Path

import numpy as np
from scipy.io import loadmat

from real_brainscore.common import sha256
from . import fingerprint
from .analysis import pearson, readout

STUDY_HASH = '17ca43dbc6ec53f9d9a1ae7b5ad234160d1dfee96dc5d83c714dd4cf87ae7366'
ATLAS_HASH = 'cf7191fd35b08c079acc78bd03813afa9f2e7774cc0f2181f8e242382022514d'


def edge_order(root):
    lower, upper = np.tril_indices(279, -1), np.triu_indices(279, 1)
    evidence = {}
    for condition in ('CAPS', 'REST'):
        example = root / 'example_participant'
        ts = np.loadtxt(example / 'ROI' / f'example_ROI_mean_timeseries_task-{condition}.mat')
        fc = loadmat(example / 'FC' / f'example_dFC_binned_task-{condition}.mat')['dfc_binned_dat'].mean(axis=1)
        static = np.corrcoef(ts.T)
        evidence[condition] = [pearson(static[idx], fc) for idx in (lower, upper)]
    if any(lo < .7 or lo - hi < .5 for lo, hi in evidence.values()):
        raise ValueError('atlas edge order not verified against public example')
    return lower, evidence


def graph_features(fc, atlas, edges):
    """Summarize positive Fisher-z weights in a symmetric, nine-node system graph."""
    a, b = atlas[edges[0]], atlas[edges[1]]
    left, right = np.minimum(a, b), np.maximum(a, b)
    block = left * 9 + right
    unique, inverse = np.unique(block, return_inverse=True)
    counts = np.bincount(inverse)
    if len(unique) != 45 or not np.isfinite(fc).all():
        raise ValueError('expected finite FC in 45 network-pair blocks')
    z = np.arctanh(np.clip(fc, 0, 1 - 1e-7))
    means = np.stack([np.bincount(inverse, weights=row, minlength=len(unique)) / counts for row in z])
    graph = np.zeros((len(fc), 9, 9))
    graph[:, unique // 9, unique % 9] = means
    graph[:, unique % 9, unique // 9] = means
    total = z.mean(axis=1, keepdims=True)
    within = graph.diagonal(axis1=1, axis2=2)
    between = (graph.sum(axis=2) - within) / 8
    segregation = (within - between) / np.maximum(within, 1e-8)
    transition = graph / np.maximum(graph.sum(axis=2, keepdims=True), 1e-8)
    returning = (transition @ transition).diagonal(axis1=1, axis2=2)
    return {'mean_connectivity': total, 'system_segregation': np.column_stack((total, segregation)),
            'two_step_return': np.column_stack((total, returning)), 'network_blocks': np.column_stack((total, means))}


def systems_task(directory):
    root = Path(directory)
    study_file = root / 'whole_participants/FC_and_pain/study3_train.mat'
    atlas_file = root / 'atlas/cluster_Fan_Net_r279.mat'
    if sha256(study_file) != STUDY_HASH or sha256(atlas_file) != ATLAS_HASH:
        raise ValueError('ToPS public Study3 or Fan atlas differs')
    edges, audit = edge_order(root)
    atlas_data = loadmat(atlas_file, variable_names=['cluster_Fan_Net'], simplify_cells=True)['cluster_Fan_Net']
    atlas = atlas_data['dat'][:, 11].astype(int) - 1  # updated nine-system assignment in author atlas
    node_names = atlas_data['descrip'][11, 1].tolist()
    study = loadmat(study_file, variable_names=['Study3'], simplify_cells=True)['Study3']
    rng = np.random.default_rng(510)
    scrambled = rng.permutation(atlas)
    feats, controls, ratings = {}, {}, {}
    for cond in ('CAPS', 'REST'):
        fc = np.stack([v.T for v in study['dfc_5bin_dat'][cond]]).reshape(-1, len(edges[0]))
        feats[cond] = graph_features(fc, atlas, edges)
        controls[cond] = graph_features(fc, scrambled, edges)
        ratings[cond] = np.stack(study['pain_5bin_dat'][cond])
    target = ratings['CAPS'] - ratings['REST']
    if target.shape != (48, 5) or not np.isfinite(target).all():
        raise ValueError('unexpected paired avoidance-rating axes')
    subjects = sorted(range(len(target)), key=lambda i: fingerprint(['L5-person', i]))
    fit, dev, held = subjects[:28], subjects[28:36], subjects[36:]
    def bins(persons):
        return (np.asarray(persons)[:, None] * 5 + np.arange(5)).ravel()
    public, private = [], {}
    for name in feats['CAPS']:
        x = feats['CAPS'][name] - feats['REST'][name]
        shuffled_x = controls['CAPS'][name] - controls['REST'][name]
        reports = []
        for persons in (dev, held):
            rows = bins(persons)
            model = readout(x, target.ravel(), bins(fit), rows)
            pred = np.asarray(model['predictions']).reshape(len(persons), 5)
            # Permute ROI network membership, preserve graph weights and the frozen readout.
            counter = (shuffled_x[rows] @ model['weights'] + model['intercept']).reshape(len(persons), 5)
            truth = target[persons].mean(axis=1)
            reports.append({'r': pearson(pred.mean(axis=1), truth), 'permuted_atlas_r': pearson(counter.mean(axis=1), truth),
                            'binwise_mean_forecast': pred.mean(axis=0).tolist(),
                            'binwise_mean_observed': target[persons].mean(axis=0).tolist(),
                            'n_participants': len(persons)})
        public.append({'id': name, 'train_value': reports[0]['r'], 'development': reports[0],
                       'features': x.shape[1]})
        private[name] = {'value': reports[1]['r'], **reports[1]}
    facts = {'study_sha256': STUDY_HASH, 'atlas_sha256': ATLAS_HASH, 'systems': node_names, 'roi_count': 279,
             'edge_count': len(edges[0]), 'ordering_lower_vs_upper_row_major': audit, 'participants_fit_dev_held': [28, 8, 12],
             'conditions': ['CAPS', 'REST'], 'target': 'CAPS minus REST future-avoidance rating, five paired bins',
             'readout': 'train-only standardized ridge, alpha 100; Pearson r across participant mean changes',
             'control': 'fixed permutation of 279 ROI system memberships, preserving network sizes and all FC values'}
    return facts, public, private
