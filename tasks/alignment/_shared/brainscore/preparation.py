"""Local-only official experiment, feature export and live/cache equivalence check."""
from pathlib import Path
import resource
import tempfile
import time

from real_brainscore.common import new_directory, separate_paths, write_json
from .adapters import align_rows
from .local_sources import benchmark as local_benchmark
from .models import subject
from .official import compute, split_manifest, traced_metric
from .packet import save
from .protocols import specification, fingerprint
from .registry import require
from .runtime import offline, check


class CapturedMetric:
    def __init__(self, original, neural):
        self.original, self.neural = original, neural
        self.calls = []

    def __call__(self, source, target):
        if self.neural:
            raw, records = traced_metric(self.original, source, target)
        else:
            raw, records = self.original(source, target), []
        self.calls.append((source.copy(deep=True), target.copy(deep=True), raw, records))
        return raw


class CapturedSubject:
    def __init__(self, candidate):
        self.candidate, self.calls = candidate, []

    def __getattr__(self, name):
        return getattr(self.candidate, name)

    def digest_text(self, text):
        output = self.candidate.digest_text(text)
        # Keep the returned object: official benchmarks subsequently attach their
        # presentation identities to it, allowing exact context-call bookkeeping.
        self.calls.append({'text': list(text) if not isinstance(text, str) else [text], 'output': output})
        return output


def scalar(value):
    import numpy as np
    if isinstance(value, np.ndarray):
        return scalar(value.tolist())
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (tuple, list)):
        return [scalar(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def coordinate_rows(assembly, dimension):
    from brainscore_core.supported_data_standards.brainio.assemblies import walk_coords
    rows = [{} for _ in range(assembly.sizes[dimension])]
    for name, dims, values in walk_coords(assembly):
        if dims == (dimension,) and name != dimension:
            for row, value in zip(rows, values):
                row[name] = scalar(value)
    return rows


def export_values(registry, benchmark_id, candidate_id, source, target, configuration, ceiling, calls):
    import numpy as np
    spec = specification(benchmark_id)
    definition = registry['benchmarks'][benchmark_id]
    behavior = spec['readout'] == 'none'
    target = target.transpose('presentation', 'subject' if behavior else 'neuroid')
    rows = coordinate_rows(target, 'presentation')
    ids = [str(value) for value in target['stimulus_id'].values]
    require(len(set(ids)) == len(ids), 'source preprocessing left ambiguous presentations')
    presentations = []
    for pid, original, coords in zip(ids, target['stimulus_id'].values, rows):
        coords['_upstream_stimulus_id'] = scalar(original)
        presentations.append({'presentation_id': pid, 'stimulus_id': str(original), 'source_coordinates': coords})
    dimension = 'subject' if behavior else 'neuroid'
    unit_rows = coordinate_rows(target, dimension)
    unit_ids = target['subject_id' if behavior else 'neuroid_id'].values
    units = []
    for uid, coords in zip(unit_ids, unit_rows):
        sid = next((coords[name] for name in ('subject', 'subject_id', 'subject_UID') if coords.get(name) is not None), None)
        units.append({'unit_id': str(uid), 'kind': definition['measurement_unit'],
                      'subject_id': str(sid) if sid is not None else None, 'source_coordinates': coords})
    if behavior:
        require(len(calls) == 1, 'official reading-times path must be a single context call')
        features = np.asarray(calls[0]['output']['behavior'].values, dtype=np.float32).reshape(-1)
        candidate_ids = ids
    else:
        features = np.asarray(source.transpose('presentation', 'neuroid').values, dtype=np.float32)
        candidate_ids = [str(x) for x in source['stimulus_id'].values]
    responses = np.asarray(target.values, dtype=np.float64)
    included = [row['presentation_id'] for row in presentations if not behavior or row['source_coordinates']['word_within_sentence_id'] != 1]
    metadata = {'presentations': presentations, 'units': units, 'candidate_presentation_ids': candidate_ids,
                'candidate_configuration': configuration,
                'context_calls': [{'text': row['text']} for row in calls],
                'protocol': {'schema': 'bpb-bs-cache-protocol/1', 'readout': spec['readout'], 'split_group': spec['split_group'],
                             'normalization': spec['normalization'], 'included_presentation_ids': included,
                             'excluded_presentations': {pid: 'official sentence-first word exclusion' for pid in ids if pid not in included},
                             'folds': [], 'ceiling': float(ceiling), 'official_specification': spec}}
    arrays = {'candidate': features, 'responses': responses, 'response_valid': np.isfinite(responses)}
    if behavior:
        arrays['candidate_valid'] = np.isfinite(features)
    provisional = {'manifest': {'benchmark_id': benchmark_id}, 'metadata': metadata,
                   'aligned': {'presentation_ids': ids, 'unit_ids': [row['unit_id'] for row in units],
                               'candidate': align_rows(features, candidate_ids, ids), 'responses': responses,
                               'response_valid': arrays['response_valid']}}
    metadata['protocol']['folds'] = split_manifest(provisional)
    return metadata, arrays


def equivalent_records(first, second, atol=1e-6, rtol=1e-5):
    import numpy as np
    if len(first) != len(second):
        return False
    for a, b in zip(first, second):
        if set(a['train_ids']) != set(b['train_ids']) or set(a['test_ids']) != set(b['test_ids']) or set(a['unit_ids']) != set(b['unit_ids']):
            return False
        rows = [b['test_ids'].index(pid) for pid in a['test_ids']]
        cols = [b['unit_ids'].index(uid) for uid in a['unit_ids']]
        if not np.allclose(a['prediction'], b['prediction'][np.ix_(rows, cols)], atol=atol, rtol=rtol, equal_nan=True):
            return False
        if not np.allclose(a['unit_scores'], b['unit_scores'][cols], atol=atol, rtol=rtol, equal_nan=True):
            return False
        if a['alpha'] is not None or b['alpha'] is not None:
            if a['alpha'] is None or b['alpha'] is None or not np.allclose(a['alpha'], b['alpha'], atol=atol, rtol=rtol):
                return False
    return True


def prepare(raw, benchmark_id, candidate_id, output, reference_output, registry, image_digest, model_dir=None):
    import numpy as np
    import re
    spec = specification(benchmark_id)
    require(re.fullmatch('sha256:[0-9a-f]{64}', image_digest or ''), 'immutable worker image digest is required')
    require(image_digest == registry['environments'][spec['ecosystem']]['image_digest'], 'worker image differs from frozen environment')
    for first, second in ((raw, output), (raw, reference_output), (output, reference_output)):
        separate_paths(first, second)
    if model_dir:
        separate_paths(model_dir, output)
        separate_paths(model_dir, reference_output)
    destination = new_directory(reference_output)
    started = time.monotonic()
    with offline():
        runtime = check(spec['ecosystem'], registry['root'])
        with tempfile.TemporaryDirectory(prefix='bpb-bs-local-source-') as temp:
            with local_benchmark(raw, temp, registry, benchmark_id) as (benchmark, audited):
                candidate, config, model_files = subject(registry, benchmark_id, candidate_id, model_dir)
                candidate = CapturedSubject(candidate)
                attribute = '_similarity_metric' if spec['ecosystem'] == 'vision' else 'metric'
                capture = CapturedMetric(getattr(benchmark, attribute), spec['readout'] != 'none')
                setattr(benchmark, attribute, capture)
                live_score = benchmark(candidate)
                require(len(capture.calls) == 1, 'fixed candidate must produce exactly one official metric call')
                source, target, raw_score, live_records = capture.calls[0]
                if spec['readout'] == 'none':
                    target = benchmark.data
                metadata, arrays = export_values(registry, benchmark_id, candidate_id, source, target, config, benchmark.ceiling, candidate.calls)
                if model_files is not None:
                    metadata['candidate_configuration']['local_files'] = model_files['files']
                provenance = {'upstream_commit': runtime['upstream_commit'], 'benchmark_version': spec['benchmark_version'],
                              'source_files': {name: row['sha256'] for name, row in audited['files'].items()},
                              'candidate_configuration_sha256': fingerprint(metadata['candidate_configuration']),
                              'dependency_lock_sha256': registry['environments'][spec['ecosystem']]['dependency_lock_sha256'],
                              'image_digest': image_digest}
                packet = save(output, registry, benchmark_id, candidate_id, metadata, arrays, provenance, synthetic=False)
                cached_score, cached_records = compute(packet)
                passed = (np.isclose(float(live_score), cached_score['normalized'], atol=1e-6, rtol=1e-5)
                          and np.isclose(float(raw_score), cached_score['raw'], atol=1e-6, rtol=1e-5)
                          and equivalent_records(live_records, cached_records))
                verification = {'schema': 'bpb-bs-official-equivalence/1', 'benchmark_id': benchmark_id, 'candidate_id': candidate_id,
                                'synthetic_only': False, 'cache_manifest_sha256': packet['manifest_sha256'], 'passed': bool(passed),
                                'live_normalized': float(live_score), 'cached_score': cached_score,
                                'checks': ['official-constructor', 'live-versus-cached-score', 'fold-predictions', 'unit-metrics', 'selected-alpha'],
                                'tolerances': {'atol': 1e-6, 'rtol': 1e-5, 'status': 'provisional'},
                                'runtime': runtime, 'source_audit': audited, 'image_digest': image_digest,
                                'observed_counts': {'presentations': int(arrays['responses'].shape[0]),
                                                    'measurement_units': int(arrays['responses'].shape[1]),
                                                    'model_features': int(arrays['candidate'].shape[1]) if arrays['candidate'].ndim == 2 else 1,
                                                    'context_calls': len(candidate.calls)},
                                'wall_seconds': time.monotonic() - started, 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
                write_json(destination / 'verification.json', verification)
                require(passed, 'live/cache equivalence failed; inspect owner verification.json')
    return {'inputs': str(packet['root']), 'verification': str(destination / 'verification.json'), 'passed': True}
