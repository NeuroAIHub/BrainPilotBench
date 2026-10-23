"""Validate submission output identities and finite numbers against trusted outputs."""
import csv
import math
from pathlib import Path
import zipfile
import zlib

import numpy as np
from contract import ContractError, PROTOCOL, SCORE_COLUMNS, read_json, require

MAX_BYTES = 10 * 1024 * 1024


def regular_tree(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'missing output directory')
    total = 0
    for p in root.rglob('*'):
        require(not p.is_symlink(), 'symlink forbidden')
        require(p.is_file() or p.is_dir(), 'special file forbidden')
        if p.is_file():
            total += p.stat().st_size
    require(total <= MAX_BYTES, 'output too large')


def compare(actual, expected):
    actual, expected = Path(actual), Path(expected)
    regular_tree(actual)
    errors, deviations = [], []

    def same(a, b, label):
        if isinstance(b, bool) or b is None or isinstance(b, str):
            require(type(a) is type(b) and a == b, label + ': identity differs')
        elif isinstance(b, (float, int)):
            require(type(a) in (int, float) and math.isfinite(a), label + ': nonfinite/nonnumeric')
            deviations.append(abs(a - b))
            if not math.isclose(a, b, abs_tol=PROTOCOL['comparison']['atol'], rel_tol=PROTOCOL['comparison']['rtol']):
                errors.append(label + ': numeric mismatch')
        elif isinstance(b, dict):
            require(isinstance(a, dict) and a.keys() == b.keys(), label + ': fields differ')
            for key in b:
                same(a[key], b[key], label + '.' + str(key))
        elif isinstance(b, list):
            require(isinstance(a, list) and len(a) == len(b), label + ': shape differs')
            for i, (av, bv) in enumerate(zip(a, b)):
                same(av, bv, f'{label}[{i}]')
        else:
            raise TypeError(type(b))

    def check(fn):
        try:
            fn()
        except (ValueError, OSError, LookupError, TypeError, OverflowError, EOFError, RuntimeError, csv.Error, zipfile.BadZipFile, zlib.error) as exc:
            errors.append(str(exc))

    for rel in ['analysis_config.json', 'results/summary.json']:
        check(lambda rel=rel: same(read_json(actual / rel), read_json(expected / rel), rel))

    def fold_scores():
        def read(path):
            with path.open(newline='') as f:
                reader = csv.DictReader(f)
                require(reader.fieldnames == SCORE_COLUMNS, 'fold score columns')
                rows = list(reader)
            result = {}
            for row in rows:
                key = tuple(row[c] for c in SCORE_COLUMNS[:3])
                require(key not in result, 'duplicate fold score key')
                result[key] = float(row['pearson_r'])
            return result
        same(read(actual / 'results/fold_scores.csv'), read(expected / 'results/fold_scores.csv'), 'fold_scores')

    def predictions():
        def read(root, shapes=None):
            path = root / 'results/predictions.npz'
            with zipfile.ZipFile(path) as z:
                require(set(z.namelist()) == {'values.npy', 'fold_ids.npy', 'stimulus_ids.npy', 'neuroid_ids.npy'}
                        and len(z.namelist()) == 4, 'NPZ members')
                require(sum(i.file_size for i in z.infolist()) <= MAX_BYTES, 'expanded predictions too large')
                header_shapes = {}
                for name in z.namelist():
                    with z.open(name) as f:
                        version = np.lib.format.read_magic(f)
                        require(version in [(1, 0), (2, 0)], 'unsupported NPY format')
                        reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
                        shape, _, dtype = reader(f)
                        require(not dtype.hasobject and math.prod(shape) * dtype.itemsize <= MAX_BYTES, 'unsafe NPY header')
                        header_shapes[name] = shape
                if shapes is not None:
                    require(header_shapes == shapes, 'prediction shape differs')
            with np.load(path, allow_pickle=False) as z:
                require(set(z.files) == {'values', 'fold_ids', 'stimulus_ids', 'neuroid_ids'}, 'prediction fields')
                values, folds, stimuli, units = (z[k] for k in ['values', 'fold_ids', 'stimulus_ids', 'neuroid_ids'])
            require(values.ndim == 2 and values.dtype == np.dtype('float64'), 'prediction dtype/shape')
            require(folds.ndim == stimuli.ndim == units.ndim == 1 and all(a.dtype.kind == 'U' for a in [folds, stimuli, units]), 'prediction ID arrays')
            require(values.shape == (len(stimuli), len(units)) and len(folds) == len(stimuli), 'prediction axes')
            require(np.isfinite(values).all(), 'nonfinite predictions')
            keys = list(zip(folds.tolist(), stimuli.tolist()))
            require(len(set(keys)) == len(keys) and len(set(units.tolist())) == len(units), 'duplicate prediction identity')
            return {(*key, str(unit)): float(values[i, j]) for i, key in enumerate(keys) for j, unit in enumerate(units)}, header_shapes
        reference, shapes = read(expected)
        observed, _ = read(actual, shapes)
        same(observed, reference, 'predictions')

    check(fold_scores)
    check(predictions)
    check(lambda: require((actual / 'report.md').is_file() and bool((actual / 'report.md').read_text().strip()), 'missing/empty report'))
    return {'passed': not errors, 'errors': errors[:20], 'mismatch_count': len(errors), 'max_abs_error': max(deviations) if deviations else None}
