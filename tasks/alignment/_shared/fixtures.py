"""Generate small local fixtures; no downloads, weights, or model invocation."""
import argparse
import csv
import shutil
from pathlib import Path

import numpy as np
from contract import FILES, MODEL, PROFILE, PROTOCOL, SCHEMA, digest, read_json, write_json


def seal(root):
    write_json(Path(root) / 'manifest.json', {
        'schema': SCHEMA, 'profile': PROFILE, 'synthetic_only': True, 'model': MODEL,
        'source': 'locally-generated-fixture',
        'axes': {'features': ['stimulus', 'feature'], 'responses': ['stimulus', 'neuroid']},
        'files': {rel: {'sha256': digest(Path(root) / rel), 'bytes': (Path(root) / rel).stat().st_size} for rel in FILES}})


def generate(root, seed=1729):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    for sub in ['model', 'brain', 'ceiling']:
        (root / sub).mkdir()
    rng = np.random.default_rng(seed)
    n, d, k = 48, 5, 5
    ids = [f'stim-{i:03}' for i in range(n)]
    # Dyadic values keep the public packet's bytes independent of BLAS rounding.
    x = (rng.integers(-512, 513, size=(n, d)) / 256).astype('float32')
    weights = rng.integers(-16, 17, size=(d, k)) / 16
    noise = rng.integers(-1024, 1025, size=(n, k)) / 512
    y = x @ weights + noise * [1 / 32, 1 / 4, 1, 2, 4]
    xp, yp = rng.permutation(n), rng.permutation(n)
    np.save(root / 'model/features.npy', x[xp])
    np.save(root / 'brain/responses.npy', y[yp].astype('float64'))
    write_json(root / 'model/stimulus_ids.json', [ids[i] for i in xp])
    write_json(root / 'brain/coords.json', {'stimulus_ids': [ids[i] for i in yp],
        'neuroids': [{'neuroid_id': f'unit-{i}', 'subject_id': 'subject-a' if i < 2 else 'subject-b',
                      'region': 'synthetic-language'} for i in range(k)]})
    with (root / 'stimuli.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['stimulus_id', 'text', 'experiment', 'passage_id', 'presentation_order'])
        for i in rng.permutation(n):
            writer.writerow([ids[i], f'Generated stimulus {i}', 'synthetic', f'passage-{i // 4:02}', i])
    group_order = np.random.default_rng(17).permutation(12)
    folds = []
    for fold in range(3):
        groups = set(group_order[fold * 4:(fold + 1) * 4])
        folds.append({'fold_id': f'fold-{fold}', 'train_ids': [ids[i] for i in range(n) if i // 4 not in groups],
                      'test_ids': [ids[i] for i in range(n) if i // 4 in groups]})
    write_json(root / 'folds.json', folds)
    write_json(root / 'protocol.json', PROTOCOL)
    write_json(root / 'ceiling/ceiling.json', {'value': 0.8, 'source': PROTOCOL['ceiling_source']})
    (root / 'DATA_DICTIONARY.md').write_text(
        '# Synthetic packet v1\n\nfeatures.npy: float32 [stimulus, feature]; responses.npy: float64 '
        '[stimulus, neuroid]. Each row is keyed by its own stimulus ID, never by row position. '
        'brain/coords.json contains stimulus_ids and ordered neuroids (neuroid_id, subject_id, region). '
        'stimuli.csv defines presentation_order and passage_id. IDs are unique; no missing or nonfinite values. '
        'folds.json explicitly lists disjoint train/test IDs with no passage overlap and exactly-once test coverage. '
        'Manifest hashes bind all files. These generated arrays are not Pereira data or real model activations.\n')
    seal(root)
    return root


def variant(source, target, mode):
    shutil.copytree(source, target)
    target = Path(target)
    if mode == 'permuted':
        x = np.load(target / 'model/features.npy', allow_pickle=False)
        np.save(target / 'model/features.npy', x[::-1])
        write_json(target / 'model/stimulus_ids.json', read_json(target / 'model/stimulus_ids.json')[::-1])
        y = np.load(target / 'brain/responses.npy', allow_pickle=False)
        np.save(target / 'brain/responses.npy', y[::-1, ::-1])
        coords = read_json(target / 'brain/coords.json')
        coords['stimulus_ids'].reverse(); coords['neuroids'].reverse()
        write_json(target / 'brain/coords.json', coords)
    elif mode == 'test-y':
        y = np.load(target / 'brain/responses.npy', allow_pickle=False)
        coords = read_json(target / 'brain/coords.json')
        test_ids = set(read_json(target / 'folds.json')[0]['test_ids'])
        rows = [i for i, sid in enumerate(coords['stimulus_ids']) if sid in test_ids]
        y[rows] = -3 * y[rows] + 100
        np.save(target / 'brain/responses.npy', y)
    else:
        raise ValueError(mode)
    seal(target)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=1729)
    args = parser.parse_args()
    generate(args.output, args.seed)
