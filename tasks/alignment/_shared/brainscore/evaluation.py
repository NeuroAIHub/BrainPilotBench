"""Trusted comparison, functional controls and isolated submission replay."""
import json
import math
from pathlib import Path
import re
import tempfile
import time

from execution import AnalysisFailure, Executor, InfrastructureError, snapshot
from real_brainscore.common import new_directory, read_json, separate_paths, write_json
from .analysis import run
from .bundle import create as create_bundle, load
from .packet import LIMIT, array, save
from .runtime import check, offline
from .registry import require


def same(left, right, atol, rtol):
    if type(right) in (int, float):
        return type(left) in (int, float) and math.isfinite(left) and math.isclose(left, right, abs_tol=atol, rel_tol=rtol)
    if isinstance(right, dict):
        return isinstance(left, dict) and left.keys() == right.keys() and all(same(left[k], v, atol, rtol) for k, v in right.items())
    if isinstance(right, list):
        return isinstance(left, list) and len(left) == len(right) and all(same(a, b, atol, rtol) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def compare(actual, expected, atol=1e-6, rtol=1e-5):
    import numpy as np
    errors = []
    actual, expected = Path(actual), Path(expected)
    try:
        files = snapshot(actual)
        require(sum((actual / name).stat().st_size for name in files) <= LIMIT, 'output exceeds 512 MiB')
        require('report.md' in files and 0 < (actual / 'report.md').stat().st_size <= 2 * 1024 * 1024, 'missing or oversized report')
        for name in ('results/summary.json', 'conclusion.json'):
            if not same(read_json(actual / name), read_json(expected / name), atol, rtol):
                errors.append(name + ' differs')
        got, wanted = read_json(actual / 'results/trace.json'), read_json(expected / 'results/trace.json')
        require(isinstance(got, list) and len(got) == len(wanted), 'trace case count differs')
        actual_files = set()
        def values(root, name):
            require(isinstance(name, str) and re.fullmatch('[a-zA-Z0-9_.-]+[.]npy', name), 'unsafe trace array filename')
            if root == actual:
                actual_files.add(name)
            return array(root / 'results' / name)
        def ids(left, right):
            require(isinstance(left, list) and all(isinstance(x, str) for x in left) and len(set(left)) == len(left)
                    and set(left) == set(right), 'trace identity coverage differs')
            return [left.index(value) for value in right]
        def equal(a, b):
            return a.shape == b.shape and a.dtype.kind == b.dtype.kind and np.allclose(a, b, atol=atol, rtol=rtol, equal_nan=True)
        for left, right in zip(got, wanted):
            require(left['case_id'] == right['case_id'] and left['kind'] == right['kind'], 'trace case identity differs')
            require(len(left['folds']) == len(right['folds']), 'fold count differs')
            if right['kind'] == 'neural':
                require(set(left) == set(right), 'trace fields differ')
                by_id = {row['id']: row for row in left['folds']}
                require(len(by_id) == len(left['folds']) and set(by_id) == {r['id'] for r in right['folds']}, 'fold identity differs')
                for ref in right['folds']:
                    row = by_id[ref['id']]
                    require(set(row) == set(ref), 'fold fields differ')
                    ids(row['train_ids'], ref['train_ids'])
                    rows, columns = ids(row['test_ids'], ref['test_ids']), ids(row['unit_ids'], ref['unit_ids'])
                    require(same(row['alpha'], ref['alpha'], atol, rtol), 'selected alpha differs')
                    prediction = values(actual, row['predictions_file'])
                    scores = values(actual, row['unit_scores_file'])
                    require(prediction.shape == (len(rows), len(columns)) and scores.shape == (len(columns),), 'prediction/metric shape differs')
                    require(equal(prediction[np.ix_(rows, columns)], values(expected, ref['predictions_file'])), 'fold predictions differ')
                    require(equal(scores[columns], values(expected, ref['unit_scores_file'])), 'unit metrics differ')
            else:
                require(set(left) == set(right), 'behavior trace fields differ')
                rows, columns = ids(left['presentation_ids'], right['presentation_ids']), ids(left['unit_ids'], right['unit_ids'])
                for field in ('reading_times_file', 'response_valid_file', 'included_file'):
                    a, b = values(actual, left[field]), values(expected, right[field])
                    if field == 'response_valid_file':
                        require(a.shape == (len(rows), len(columns)), 'behavior mask shape differs')
                        a = a[np.ix_(rows, columns)]
                    else:
                        require(a.shape == (len(rows),), 'behavior output shape differs')
                        a = a[rows]
                    require(equal(a, b), 'behavior values/masks differ: ' + field)
        declared = {p.name for p in (actual / 'results').glob('*.npy')}
        require(declared == actual_files, 'numerical result inventory differs')
    except Exception as exc:
        errors.append('%s: %s' % (type(exc).__name__, exc))
    return {'passed': not errors, 'errors': errors, 'atol': atol, 'rtol': rtol}


def control_inputs(bundle, output, registry):
    """Perturb held-out targets (neural) or model outputs (behavior), never tune choices."""
    import copy
    import numpy as np
    root = new_directory(output)
    paths = []
    selected_benchmark = bundle['packets'][0]['manifest']['benchmark_id']
    for i, packet in enumerate(bundle['packets']):
        arrays, metadata = dict(packet['arrays']), copy.deepcopy(packet['metadata'])
        if packet['manifest']['benchmark_id'] == selected_benchmark:
            if metadata['protocol']['readout'] == 'none':
                arrays['candidate'] = arrays['candidate'].copy()
                included = set(metadata['protocol']['included_presentation_ids'])
                positions = [j for j, pid in enumerate(metadata['candidate_presentation_ids']) if pid in included]
                arrays['candidate'][positions] = np.roll(arrays['candidate'][positions], 1)
                metadata['functional_control'] = 'rotate-included-model-reading-times'
            else:
                arrays['responses'] = arrays['responses'].copy()
                test = set(metadata['protocol']['folds'][0]['test_ids'])
                positions = [j for j, row in enumerate(metadata['presentations']) if row['presentation_id'] in test]
                rng = np.random.default_rng(730)
                arrays['responses'][positions] += rng.normal(size=arrays['responses'][positions].shape) * .31
                metadata['functional_control'] = 'perturb-first-fold-test-targets-only'
        value = save(root / ('packet-%02d' % i), registry, packet['manifest']['benchmark_id'], packet['manifest']['candidate_id'],
                     metadata, arrays, packet['provenance'], synthetic=packet['manifest']['synthetic_only'])
        paths.append(value['root'])
    return create_bundle(paths, root / 'inputs', bundle['instance']['id'], registry)


def probe_image(executor, ecosystem, expected):
    """Probe dependencies without installing the owner solver or mounting references."""
    code = ('import hashlib,importlib,importlib.metadata,json; from pathlib import Path; '
            'm=importlib.import_module(' + repr('brainscore_' + ecosystem) + '); root=Path(m.__file__).parent; '
            'h=hashlib.sha256(); '
            '[h.update((p.relative_to(root).as_posix()+":"+hashlib.sha256(p.read_bytes()).hexdigest()+"\\n").encode()) '
            'for p in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in (".py",".json"))]; '
            'print(json.dumps({"package_tree_sha256":h.hexdigest(),"packages":{n:importlib.metadata.version(n) for n in '
            + repr(list(expected['packages'])) + '}}))')
    identity = executor.admin(['image', 'inspect', '--format', '{{.Id}}', executor.image])
    require(identity.returncode == 0 and identity.stdout.strip().startswith('sha256:'), 'worker image identity unavailable')
    executor.image = identity.stdout.strip()
    probe = executor.admin(['run', '--rm', '--pull=never', '--network=none', '--read-only', '--entrypoint', 'python', executor.image, '-B', '-c', code])
    if probe.returncode:
        raise InfrastructureError('worker dependency probe failed')
    observed = json.loads(probe.stdout)
    if observed != {key: expected[key] for key in ('package_tree_sha256', 'packages')}:
        raise InfrastructureError('worker and owner numerical packages/upstream code differ')


def evaluate(inputs, submission, output, registry, image=None, saved_results=None, isolation='docker', timeout=900., cpus=2., memory='8g'):
    root = new_directory(output)
    report = {'schema': 'bpb-bs-grade/1', 'state': 'scoring_failed', 'analysis_success': None,
              'isolation': isolation, 'prose_review': 'not_assessed', 'acceptance': 'experimental-data-and-agent-validation-pending'}
    started = time.monotonic()
    try:
        bundle = load(inputs, registry)
        source = Path(submission).resolve()
        for a, b in ((inputs, source), (inputs, root), (source, root)):
            separate_paths(a, b)
        if saved_results:
            separate_paths(saved_results, root)
        report.update(instance_id=bundle['instance']['id'], synthetic_only=bundle['manifest']['synthetic_only'],
                      input_manifest_sha256=bundle['manifest_sha256'])
        ecosystem = registry['families'][bundle['instance']['family_id']]['ecosystem']
        with offline():
            runtime = check(ecosystem, registry['root'])
        executor = Executor(isolation, timeout=timeout, cpus=cpus, memory=memory, tmpfs='512m')
        if image:
            executor.image = image
        executor.preflight()
        if isolation == 'docker':
            probe_image(executor, ecosystem, runtime)
            if executor.image != registry['environments'][ecosystem]['image_digest']:
                raise InfrastructureError('worker image differs from the frozen registry image')
        report.update(image=executor.image if isolation == 'docker' else None,
                      worker_limits={'timeout_seconds': timeout, 'cpus': cpus, 'memory': memory})
        try:
            require('analyze.py' in snapshot(source), 'missing submission/analyze.py')
        except Exception as exc:
            raise AnalysisFailure(str(exc)) from exc
        with tempfile.TemporaryDirectory(prefix='bpb-bs-owner-') as temp:
            owner = Path(temp)
            reference = owner / 'reference'
            run(inputs, reference, registry)
            executor.run(source, bundle['root'], root / 'worker-output')
            comparisons = [{'kind': 'rerun', **compare(root / 'worker-output', reference)}]
            if saved_results:
                comparisons.append({'kind': 'saved', **compare(saved_results, reference)})
            # A second input prevents replaying fixed answers with a rewritten input hash.
            altered = control_inputs(bundle, owner / 'control', registry)
            control_reference = owner / 'control-reference'
            run(altered['root'], control_reference, registry)
            executor.run(source, altered['root'], root / 'control-output')
            comparisons.append({'kind': 'functional-control', **compare(root / 'control-output', control_reference)})
            report.update(state='scored', analysis_success=int(all(c['passed'] for c in comparisons)), comparisons=comparisons,
                          inputs_unchanged=True, source_unchanged=True)
    except AnalysisFailure as exc:
        report.update(state='scored', analysis_success=0, error=str(exc))
    except Exception as exc:
        report.update(state='scoring_failed', analysis_success=None, error='%s: %s' % (type(exc).__name__, exc))
    report['wall_seconds'] = time.monotonic() - started
    write_json(root / 'grade.json', report)
    return report
