"""Prepare a small model-free analysis packet from the verified Pereira cache."""
from collections import defaultdict
from pathlib import Path

from real_brainscore.common import load_cache, new_directory, read_json, seal, separate_paths, sha256, write_json
from . import PROTOCOL, IncrementalError
from .protocol import make_splits, specification

FILES = {'protocol.json', 'provenance.json', 'stimuli.json', 'neuroids.json', 'splits.json',
         'features.npy', 'brain.npy', 'controls.npy'}


def response_qc(brain, neuroids):
    import numpy as np
    if brain.ndim != 2 or brain.shape[1] != len(neuroids) or not np.isfinite(brain).all():
        raise IncrementalError('invalid response array for quality control')
    keep = np.ptp(brain, axis=0) > 0
    retained = [n for n, valid in zip(neuroids, keep) if valid]
    excluded = [{**n, 'reason': 'constant_full_dataset'} for n, valid in zip(neuroids, keep) if not valid]
    if {n['subject_id'] for n in retained} != {n['subject_id'] for n in neuroids}:
        raise IncrementalError('quality control would remove an entire subject')
    return brain[:, keep], retained, excluded


def controls_from_stimuli(stimuli):
    import numpy as np
    passages = defaultdict(list)
    ids = [s['stimulus_id'] for s in stimuli]
    if len(set(ids)) != len(ids):
        raise IncrementalError('duplicate stimulus identity')
    for i, row in enumerate(stimuli):
        if not row['stimulus'].strip() or type(row['stimulus_num']) is not int:
            raise IncrementalError('missing stimulus text or original sentence order')
        passages[row['passage_label']].append(i)
    controls = np.zeros((len(stimuli), 5), dtype=np.float64)
    for positions in passages.values():
        if (len(positions) != 4 or len({stimuli[i]['story'] for i in positions}) != 1
                or len({stimuli[i]['stimulus_num'] for i in positions}) != 4):
            raise IncrementalError('expected four ordered sentences in each single-story passage')
        for order, i in enumerate(sorted(positions, key=lambda i: stimuli[i]['stimulus_num'])):
            controls[i, 0] = len(stimuli[i]['stimulus'].split())
            controls[i, order + 1] = 1
    return controls


def prepare(cache, output, layer=None):
    import numpy as np
    import xarray as xr
    root, _, configuration = load_cache(cache)
    separate_paths(root, output)
    layer = layer or configuration['task1_layer']
    if layer not in configuration['layers']:
        raise IncrementalError('requested layer is not cached')
    stimuli = read_json(root / 'stimuli.json')
    with xr.open_dataset(root / 'brain.nc') as ds:
        if ds['data'].dims != ('presentation', 'neuroid'):
            raise IncrementalError('brain array dimensions differ')
        brain = np.asarray(ds['data'].values, dtype=np.float64)
        if list(ds['stimulus_id'].values.astype(str)) != [s['stimulus_id'] for s in stimuli]:
            raise IncrementalError('stimulus identities differ between X metadata and brain data')
        for key in ('stimulus', 'story', 'passage_label'):
            if list(ds[key].values.astype(str)) != [s[key] for s in stimuli]:
                raise IncrementalError('stimulus metadata mismatch: ' + key)
        for row, num in zip(stimuli, ds['stimulus_num'].values):
            if not np.isfinite(num) or int(num) != num:
                raise IncrementalError('invalid original stimulus number')
            row['stimulus_num'] = int(num)
        neuroids = [{'neuroid_id': str(unit), 'subject_id': str(subject)}
                    for unit, subject in zip(ds['neuroid_id'].values, ds['subject'].values)]
    features = np.load(root / ('features/layer-%03d.npy' % configuration['layers'].index(layer)), allow_pickle=False)
    controls = controls_from_stimuli(stimuli)
    if len(stimuli) != 384 or not np.isfinite(brain).all() or not np.isfinite(features).all():
        raise IncrementalError('expected finite Pereira384 inputs')
    original_neuroids = len(neuroids)
    brain, neuroids, excluded = response_qc(brain, neuroids)
    destination = new_directory(output)
    for name, value in [('features', features), ('brain', brain), ('controls', controls)]:
        np.save(destination / (name + '.npy'), value, allow_pickle=False)
    write_json(destination / 'stimuli.json', stimuli)
    write_json(destination / 'neuroids.json', neuroids)
    write_json(destination / 'protocol.json', specification())
    write_json(destination / 'splits.json', make_splits(stimuli))
    write_json(destination / 'provenance.json', {
        'source_cache_sha256': sha256(root / 'manifest.json'), 'upstream_commit': configuration['upstream_commit'],
        'benchmark_source': configuration['benchmark'], 'model': configuration['model'], 'layer': layer,
        'control_columns': ['word_count', 'position_1', 'position_2', 'position_3', 'position_4'],
        'control_derivation': 'original stimulus_num within passage; passage_index is NOT sentence position',
        'response_qc': {'original_neuroids': original_neuroids, 'retained_neuroids': len(neuroids), 'excluded': excluded,
                        'scope': 'fixed target-set QC on supplied responses; not a training-fitted feature transformation'},
        'prior_exposure': 'source data have already been inspected during Task1/Task2 integration; not a new prospective confirmation cohort',
        'official_benchmark_equivalence': False,
    })
    seal(destination, {'schema': 'bpb-incremental-inputs/1', 'protocol_id': PROTOCOL,
                       'synthetic_only': False, 'acceptance': 'experimental-scientific-review-pending'})
    load_inputs(destination)
    return {'inputs': str(destination), 'stimuli': len(stimuli), 'neuroids': len(neuroids),
            'subjects': len({n['subject_id'] for n in neuroids}), 'layer': layer,
            'excluded_constant_neuroids': len(excluded),
            'manifest_sha256': sha256(destination / 'manifest.json')}


def load_inputs(root):
    import numpy as np
    root = Path(root).resolve()
    manifest = read_json(root / 'manifest.json')
    if (manifest.get('schema') != 'bpb-incremental-inputs/1' or manifest.get('protocol_id') != PROTOCOL
            or type(manifest.get('synthetic_only')) is not bool or set(manifest.get('files', {})) != FILES):
        raise IncrementalError('invalid incremental input manifest')
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise IncrementalError('nonregular input member')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != FILES | {'manifest.json'}:
        raise IncrementalError('input inventory differs')
    for rel in FILES:
        path = root / rel
        if manifest['files'][rel] != {'bytes': path.stat().st_size, 'sha256': sha256(path)}:
            raise IncrementalError('input content hash differs: ' + rel)
    protocol = read_json(root / 'protocol.json')
    if protocol != specification():
        raise IncrementalError('unsupported protocol; version changes must be explicit')
    stimuli, neuroids = read_json(root / 'stimuli.json'), read_json(root / 'neuroids.json')
    splits = read_json(root / 'splits.json')
    if splits != make_splits(stimuli):
        raise IncrementalError('story folds differ from frozen protocol')
    x, y, c = [np.load(root / (name + '.npy'), allow_pickle=False) for name in ('features', 'brain', 'controls')]
    if (x.ndim != 2 or x.shape[0] != len(stimuli) or x.shape[1] < 1
            or y.shape != (len(stimuli), len(neuroids)) or y.ndim != 2
            or len({n['neuroid_id'] for n in neuroids}) != len(neuroids)
            or not neuroids or any(not n['subject_id'] for n in neuroids)
            or np.any(np.ptp(y, axis=0) == 0)
            or not all(np.isfinite(a).all() for a in (x, y, c))
            or not np.array_equal(c, controls_from_stimuli(stimuli))):
        raise IncrementalError('invalid arrays, identities or derived controls')
    return {'root': root, 'manifest': manifest, 'manifest_sha256': sha256(root / 'manifest.json'),
            'protocol': protocol, 'stimuli': stimuli, 'neuroids': neuroids, 'splits': splits,
            'features': np.asarray(x, dtype=np.float64), 'brain': y, 'controls': c}
