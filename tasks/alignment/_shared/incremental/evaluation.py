"""Trusted recomputation, bounded output parsing and isolated source replay."""
import json
import math
from pathlib import Path
import tempfile
import zipfile

from execution import AnalysisFailure, Executor, InfrastructureError, snapshot
from real_brainscore.common import new_directory, read_json, separate_paths, write_json
from . import PROTOCOL, IncrementalError
from .analysis import run_analysis
from .data import load_inputs
from .protocol import MODELS, validate_plan

LIMIT = 512 * 1024 * 1024
ATOL, RTOL = 1e-7, 1e-5


def same(left, right):
    if type(right) in (int, float):
        return type(left) in (int, float) and math.isfinite(left) and math.isclose(left, right, abs_tol=ATOL, rel_tol=RTOL)
    if isinstance(right, dict):
        return isinstance(left, dict) and set(left) == set(right) and all(same(left[k], v) for k, v in right.items())
    if isinstance(right, list):
        return isinstance(left, list) and len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def read_predictions(root, shape):
    import numpy as np
    path = Path(root) / 'results/predictions.npz'
    names = {*MODELS, 'stimulus_ids', 'neuroid_ids'}
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(names) or set(archive.namelist()) != {n + '.npy' for n in names}:
            raise IncrementalError('prediction archive members differ')
        if sum(info.file_size for info in archive.infolist()) > LIMIT:
            raise IncrementalError('expanded predictions exceed 512 MiB')
        for name in names:
            with archive.open(name + '.npy') as member:
                version = np.lib.format.read_magic(member)
                if version not in ((1, 0), (2, 0)):
                    raise IncrementalError('unsupported prediction header')
                reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
                dims, _, dtype = reader(member)
                if dtype.hasobject or math.prod(dims) * dtype.itemsize > LIMIT:
                    raise IncrementalError('unsafe prediction dtype or shape')
                if name in MODELS and (dims != shape or dtype != np.dtype('float64')):
                    raise IncrementalError('prediction shape/dtype differs')
                if name not in MODELS and (dtype.kind != 'U' or dims != (shape[0 if name == 'stimulus_ids' else 1],)):
                    raise IncrementalError('invalid prediction IDs')
    with np.load(path, allow_pickle=False) as arrays:
        result = {k: arrays[k] for k in names}
    for name in ('stimulus_ids', 'neuroid_ids'):
        if len(set(result[name])) != len(result[name]):
            raise IncrementalError('duplicate prediction IDs')
    if not all(np.isfinite(result[name]).all() for name in MODELS):
        raise IncrementalError('nonfinite predictions')
    return result


def compare(actual, expected, shape):
    import numpy as np
    errors = []
    try:
        snapshot(actual)
        if sum(p.stat().st_size for p in Path(actual).rglob('*') if p.is_file()) > LIMIT:
            raise IncrementalError('results exceed 512 MiB')
        for rel in ('analysis_plan.json', 'results/summary.json', 'results/folds.json', 'conclusion.json'):
            if not same(read_json(Path(actual) / rel), read_json(Path(expected) / rel)):
                errors.append(rel + ' mismatch')
        ref, got = read_predictions(expected, shape), read_predictions(actual, shape)
        if any(set(ref[k]) != set(got[k]) for k in ('stimulus_ids', 'neuroid_ids')):
            raise IncrementalError('prediction identities differ')
        rows = {sid: i for i, sid in enumerate(got['stimulus_ids'])}
        cols = {nid: i for i, nid in enumerate(got['neuroid_ids'])}
        order = np.ix_([rows[s] for s in ref['stimulus_ids']], [cols[s] for s in ref['neuroid_ids']])
        for name in MODELS:
            if not np.allclose(got[name][order], ref[name], atol=ATOL, rtol=RTOL):
                errors.append(name + ' predictions mismatch')
        report = Path(actual) / 'report.md'
        if not report.is_file() or not 0 < report.stat().st_size <= 2 * 1024 * 1024:
            errors.append('missing or oversized report.md')
    except Exception as exc:
        errors.append(str(exc))
    return {'passed': not errors, 'errors': errors, 'atol': ATOL, 'rtol': RTOL}


def evaluate(inputs, submission, output, image=None, saved_results=None, isolation='docker',
             timeout=900, cpus=2, memory='8g'):
    destination = new_directory(output)
    report = {'schema': 'bpb-incremental-grade/1', 'protocol_id': PROTOCOL,
              'state': 'scoring_failed', 'analysis_success': None, 'isolation': isolation,
              'prose_review': 'not_assessed', 'acceptance': 'experimental-scientific-review-pending'}
    try:
        packet = load_inputs(inputs)
        report['synthetic_only'] = packet['manifest']['synthetic_only']
        source = Path(submission).resolve()
        for other in (source, packet['root']):
            separate_paths(other, destination)
        separate_paths(source, packet['root'])
        try:
            snapshot(source)
            if not (source / 'analyze.py').is_file():
                raise IncrementalError('submission/analyze.py is missing')
            plan = validate_plan(read_json(source / 'plan.json'))
        except Exception as exc:
            raise AnalysisFailure('invalid submission: ' + str(exc)) from exc
        executor = Executor(isolation, timeout=timeout, cpus=cpus, memory=memory, tmpfs='512m')
        if image:
            executor.image = image
        executor.preflight()
        if isolation == 'docker':
            import numpy as np
            probe = executor.admin(['run', '--rm', '--pull=never', '--network=none', '--read-only',
                                    '--entrypoint', 'python', executor.image, '-B', '-c',
                                    'import json,numpy; print(json.dumps({"numpy":numpy.__version__}))'])
            if probe.returncode or json.loads(probe.stdout) != {'numpy': np.__version__}:
                raise InfrastructureError('worker/server NumPy versions differ')
            identity = executor.admin(['image', 'inspect', '--format', '{{.Id}}', executor.image])
            if identity.returncode or not identity.stdout.strip().startswith('sha256:'):
                raise InfrastructureError('local image identity unavailable')
            executor.image = identity.stdout.strip()
            report['image'] = executor.image
        report['worker_limits'] = {'cpus': cpus, 'memory': memory, 'timeout_seconds': timeout}
        with tempfile.TemporaryDirectory(prefix='bpb-incremental-reference-') as temp:
            reference = Path(temp) / 'reference'
            summary = run_analysis(inputs, reference, plan)
            executor.run(source, packet['root'], destination / 'worker-output')
            comparisons = [compare(destination / 'worker-output', reference, packet['brain'].shape)]
            if saved_results is not None:
                comparisons.append(compare(saved_results, reference, packet['brain'].shape))
            report.update(state='scored', analysis_success=int(all(c['passed'] for c in comparisons)),
                          comparisons=comparisons, reference_increment=summary['increment'],
                          inputs_unchanged=True, source_unchanged=True)
    except AnalysisFailure as exc:
        report.update(state='scored', analysis_success=0, error=str(exc))
    except Exception as exc:
        report.update(state='scoring_failed', analysis_success=None, error='%s: %s' % (type(exc).__name__, exc))
    write_json(destination / 'grade.json', report)
    return report
