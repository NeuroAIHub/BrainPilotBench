"""Frozen synthetic-only packet/output contract. Never an official Brain-Score adapter."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

SCHEMA = 'bpb-alignment-synthetic/1'
TASK_ID = 'alignment-synthetic'
VERSION = '0.1'
PROFILE = 'synthetic-ridge-v1'
MODEL = {'id': 'synthetic-linear-generator', 'revision': '1', 'layer': 'fixed.features',
         'tokenizer_revision': 'not-applicable', 'pooling': 'not-applicable',
         'context': 'generated-independent-vectors', 'dtype': 'float32'}
PROTOCOL = {
    'schema': SCHEMA, 'id': PROFILE, 'backend': 'synthetic_numpy', 'scientific_equivalence': False,
    'model': MODEL, 'experiment': 'synthetic', 'region': 'synthetic-language',
    'missing_values': 'reject', 'excluded_neuroids': [],
    'split': {'kind': 'explicit-group-kfold', 'group': 'passage_id', 'folds': 3,
              'seed': 17, 'test_coverage': 'exactly-once'},
    'fit': {'method': 'ridge', 'alpha': 0.7, 'alpha_selection': 'fixed-no-search',
            'intercept': True, 'center': 'training-only', 'scale': False, 'pca': False},
    'metric': 'pearson-r-per-fold-neuroid', 'constant_correlation': 0.0,
    'aggregation': 'median-neuroids-within-subject-then-mean-subjects-then-mean-folds',
    'normalization': 'raw-divided-by-ceiling', 'clip': False,
    'ceiling_source': 'synthetic-constant-not-biological',
    'comparison': {'atol': 1e-8, 'rtol': 1e-7},
}
FILES = ['stimuli.csv', 'model/features.npy', 'model/stimulus_ids.json',
         'brain/responses.npy', 'brain/coords.json', 'protocol.json', 'folds.json',
         'ceiling/ceiling.json', 'DATA_DICTIONARY.md']
REQUIRED = ['submission/analyze.py', 'analysis_config.json', 'results/summary.json',
            'results/fold_scores.csv', 'results/predictions.npz', 'report.md']
SCORE_COLUMNS = ['fold_id', 'subject_id', 'neuroid_id', 'pearson_r']


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def read_json(path):
    def invalid(value):
        raise ContractError('non-finite JSON: ' + value)
    return json.loads(Path(path).read_text(), parse_constant=invalid)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_ids(values, label):
    require(isinstance(values, list) and len(values) > 0, label + ': empty IDs')
    require(all(isinstance(v, str) and v for v in values), label + ': invalid ID')
    require(len(values) == len(set(values)), label + ': duplicate IDs')


def load_packet(root):
    root = Path(root)
    manifest = read_json(root / 'manifest.json')
    require(set(manifest) == {'schema', 'profile', 'synthetic_only', 'source', 'model', 'axes', 'files'}, 'manifest fields')
    require(manifest['source'] == 'locally-generated-fixture', 'manifest source')
    require(manifest['schema'] == SCHEMA and manifest['profile'] == PROFILE, 'unsupported schema/profile')
    require(manifest['synthetic_only'] is True, 'real data cannot use synthetic backend')
    require(manifest['model'] == MODEL, 'model binding differs')
    require(set(manifest['files']) == set(FILES), 'manifest file inventory differs')
    for rel, info in manifest['files'].items():
        path = root / rel
        require(path.is_file() and not path.is_symlink(), 'missing/nonregular input: ' + rel)
        require(info == {'sha256': digest(path), 'bytes': path.stat().st_size}, 'input hash mismatch: ' + rel)
    require(read_json(root / 'protocol.json') == PROTOCOL, 'unsupported protocol (no backend fallback)')
    with (root / 'stimuli.csv').open(newline='') as f:
        reader = csv.DictReader(f)
        require(reader.fieldnames == ['stimulus_id', 'text', 'experiment', 'passage_id', 'presentation_order'], 'stimulus columns')
        stimuli = list(reader)
    ids = [s['stimulus_id'] for s in stimuli]
    unique_ids(ids, 'stimuli')
    order = [int(s['presentation_order']) for s in stimuli]
    require(set(order) == set(range(len(ids))), 'presentation order must be a permutation')
    require(all(s['experiment'] == 'synthetic' and s['passage_id'] for s in stimuli), 'experiment/group')
    stimuli.sort(key=lambda s: int(s['presentation_order']))
    ids = [s['stimulus_id'] for s in stimuli]
    xids = read_json(root / 'model/stimulus_ids.json')
    coords = read_json(root / 'brain/coords.json')
    require(set(coords) == {'stimulus_ids', 'neuroids'}, 'coordinate fields')
    yids = coords['stimulus_ids']
    units = coords['neuroids']
    uids = [u['neuroid_id'] for u in units]
    for values, label in [(xids, 'model'), (yids, 'brain'), (uids, 'neuroids')]:
        unique_ids(values, label)
    require(set(ids) == set(xids) == set(yids), 'stimulus coverage differs')
    require(all(set(u) == {'neuroid_id', 'subject_id', 'region'} for u in units), 'neuroid fields')
    require(all(u['subject_id'] and u['region'] == PROTOCOL['region'] for u in units), 'neuroid metadata')
    x = np.load(root / 'model/features.npy', allow_pickle=False)
    y = np.load(root / 'brain/responses.npy', allow_pickle=False)
    require(manifest['axes'] == {'features': ['stimulus', 'feature'], 'responses': ['stimulus', 'neuroid']}, 'axes differ')
    require(x.ndim == 2 and x.shape[0] == len(ids) and x.shape[1] > 0 and x.dtype == np.dtype('float32'), 'feature shape/dtype')
    require(y.shape == (len(ids), len(units)) and y.dtype == np.dtype('float64'), 'response shape/dtype')
    require(np.isfinite(x).all() and np.isfinite(y).all(), 'non-finite input')
    xi, yi = {v: i for i, v in enumerate(xids)}, {v: i for i, v in enumerate(yids)}
    ui = sorted(range(len(units)), key=lambda i: units[i]['neuroid_id'])
    x = x[[xi[v] for v in ids]].astype(np.float64)
    y = y[[yi[v] for v in ids]][:, ui]
    units = [units[i] for i in ui]
    folds = read_json(root / 'folds.json')
    require(isinstance(folds, list) and len(folds) == PROTOCOL['split']['folds'], 'fold count')
    unique_ids([f['fold_id'] for f in folds], 'folds')
    require([f['fold_id'] for f in folds] == ['fold-0', 'fold-1', 'fold-2'], 'fold order')
    groups = {s['stimulus_id']: s['passage_id'] for s in stimuli}
    coverage = []
    for fold in folds:
        require(set(fold) == {'fold_id', 'train_ids', 'test_ids'}, 'fold fields')
        train, test = fold['train_ids'], fold['test_ids']
        unique_ids(train, 'train'); unique_ids(test, 'test')
        require(set(train).isdisjoint(test) and set(train) | set(test) == set(ids), 'fold partition')
        require({groups[s] for s in train}.isdisjoint({groups[s] for s in test}), 'group leakage')
        require(len(train) >= 3 and len(test) >= 3, 'fold too small')
        coverage.extend(test)
    require(sorted(coverage) == sorted(ids), 'test coverage not exactly once')
    ceiling = read_json(root / 'ceiling/ceiling.json')
    require(ceiling == {'value': 0.8, 'source': PROTOCOL['ceiling_source']}, 'synthetic ceiling differs')
    return {'root': root, 'manifest_hash': digest(root / 'manifest.json'), 'ids': ids,
            'x': x, 'y': y, 'units': units, 'folds': folds, 'ceiling': ceiling['value']}


def config(packet):
    return {'schema': SCHEMA, 'task_id': TASK_ID, 'task_version': VERSION,
            'protocol_id': PROFILE, 'backend': 'synthetic_numpy', 'model': MODEL,
            'input_manifest_sha256': packet['manifest_hash']}


def correlations(pred, truth):
    a, b = pred - pred.mean(0), truth - truth.mean(0)
    denom = np.sqrt((a * a).sum(0) * (b * b).sum(0))
    return np.divide((a * b).sum(0), denom, out=np.zeros_like(denom), where=denom != 0)


def aggregate(scores, units):
    subjects = sorted({u['subject_id'] for u in units})
    subject_values = [np.median(scores[:, [i for i, u in enumerate(units) if u['subject_id'] == s]], axis=1)
                      for s in subjects]
    return float(np.mean(np.stack(subject_values, axis=1)))


def write_outputs(packet, output, predictions, scores):
    output = Path(output)
    (output / 'results').mkdir(parents=True, exist_ok=True)
    write_json(output / 'analysis_config.json', config(packet))
    raw = aggregate(scores, packet['units'])
    write_json(output / 'results/summary.json', {
        **config(packet), 'synthetic_only': True, 'raw_score': raw, 'normalized_score': raw / packet['ceiling'],
        'ceiling': packet['ceiling'], 'coverage': {'stimuli': len(packet['ids']), 'neuroids': len(packet['units']),
                                                'folds': len(packet['folds']), 'prediction_rows': sum(map(len, predictions))}})
    with (output / 'results/fold_scores.csv').open('w', newline='') as f:
        writer = csv.writer(f); writer.writerow(SCORE_COLUMNS)
        for fold, values in zip(packet['folds'], scores):
            for unit, value in zip(packet['units'], values):
                writer.writerow([fold['fold_id'], unit['subject_id'], unit['neuroid_id'], float(value)])
    np.savez(output / 'results/predictions.npz', values=np.concatenate(predictions),
             fold_ids=np.array([f['fold_id'] for f in packet['folds'] for _ in f['test_ids']]),
             stimulus_ids=np.array([s for f in packet['folds'] for s in f['test_ids']]),
             neuroid_ids=np.array([u['neuroid_id'] for u in packet['units']]))
    (output / 'report.md').write_text(
        f'# Synthetic workflow check\n\nProtocol: {PROFILE}. Fixed ridge alpha 0.7; training-only centering; '
        'explicit passage-group folds. Median neuroids within subject, then mean subjects and folds.\n\n'
        f'Raw score: {raw:.10g}; normalized score: {raw / packet["ceiling"]:.10g}; '
        'synthetic ceiling: 0.8 (no clipping). IDs, groups and finite inputs were checked.\n\n'
        'Synthetic only. No biological interpretation, official Brain-Score equivalence or mechanism equivalence.\n')
