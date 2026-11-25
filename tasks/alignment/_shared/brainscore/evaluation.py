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


def ordered_rows(rows, key, expected_ids, errors, label):
    """Keep valid rows attributable even when a different row is missing or duplicated."""
    indexed = {}
    order = []
    if isinstance(rows, list):
        for row in rows:
            identity = row.get(key) if isinstance(row, dict) else None
            order.append(identity)
            if isinstance(identity, str):
                indexed[identity] = None if identity in indexed else row
    if not isinstance(rows, list) or order != expected_ids:
        errors.append(label + ' identity coverage or order differs')
    return indexed


def check_trace(actual, expected, left, right, actual_files, atol, rtol):
    import numpy as np

    def values(root, name):
        require(isinstance(name, str) and re.fullmatch('[a-zA-Z0-9_.-]+[.]npy', name), 'unsafe trace array filename')
        if root == actual:
            actual_files.add(name)
        return array(root / 'results' / name)

    def positions(observed, wanted):
        require(isinstance(observed, list) and all(isinstance(x, str) for x in observed), 'invalid trace IDs')
        offsets = {value: index for index, value in enumerate(observed)}
        require(len(offsets) == len(observed) and offsets.keys() == set(wanted), 'trace identity coverage differs')
        return [offsets[value] for value in wanted]

    def equal(a, b):
        return a.shape == b.shape and a.dtype.kind == b.dtype.kind and np.allclose(a, b, atol=atol, rtol=rtol, equal_nan=True)

    require(isinstance(left, dict) and set(left) == set(right) and left['case_id'] == right['case_id']
            and left['kind'] == right['kind'], 'trace fields or case identity differ')
    require(isinstance(left['folds'], list) and len(left['folds']) == len(right['folds']), 'fold count differs')
    if right['kind'] == 'neural':
        by_id = {row['id']: row for row in left['folds']}
        require(set(by_id) == {row['id'] for row in right['folds']}, 'fold identity differs')
        for ref in right['folds']:
            row = by_id[ref['id']]
            require(set(row) == set(ref), 'fold fields differ')
            positions(row['train_ids'], ref['train_ids'])
            rows = positions(row['test_ids'], ref['test_ids'])
            columns = positions(row['unit_ids'], ref['unit_ids'])
            require(same(row['alpha'], ref['alpha'], atol, rtol), 'selected alpha differs')
            prediction = values(actual, row['predictions_file'])
            scores = values(actual, row['unit_scores_file'])
            require(prediction.shape == (len(rows), len(columns)) and scores.shape == (len(columns),), 'prediction/metric shape differs')
            require(equal(prediction[np.ix_(rows, columns)], values(expected, ref['predictions_file'])), 'fold predictions differ')
            require(equal(scores[columns], values(expected, ref['unit_scores_file'])), 'unit metrics differ')
    else:
        rows = positions(left['presentation_ids'], right['presentation_ids'])
        columns = positions(left['unit_ids'], right['unit_ids'])
        for field in ('reading_times_file', 'response_valid_file', 'included_file'):
            a, b = values(actual, left[field]), values(expected, right[field])
            if field == 'response_valid_file':
                require(a.shape == (len(rows), len(columns)), 'behavior mask shape differs')
                a = a[np.ix_(rows, columns)]
            else:
                require(a.shape == (len(rows),), 'behavior output shape differs')
                a = a[rows]
            require(equal(a, b), 'behavior values/masks differ: ' + field)


def compare(actual, expected, atol=1e-6, rtol=1e-5):
    actual, expected = Path(actual), Path(expected)
    summary = read_json(expected / 'results/summary.json')
    cases, comparisons = summary.pop('cases'), summary.pop('comparisons')
    conclusion = read_json(expected / 'conclusion.json')
    rankings = {row['benchmark_id']: row for row in conclusion.pop('rankings')}
    traces = {row['case_id']: row for row in read_json(expected / 'results/trace.json')}
    case_ids = [row['id'] for row in cases]
    benchmark_ids = [row['benchmark_id'] for row in comparisons]
    case_passed, comparison_passed = dict.fromkeys(case_ids, False), dict.fromkeys(benchmark_ids, False)
    errors = []

    def submitted(name, default):
        try:
            value = read_json(actual / name)
            require(type(value) is type(default), name + ' has unexpected type')
            return value
        except Exception as exc:
            errors.append(f'{name}: {exc}')
            return default

    try:
        files = snapshot(actual)
        require(sum((actual / name).stat().st_size for name in files) <= LIMIT, 'output exceeds 512 MiB')
        if 'report.md' not in files or not 0 < (actual / 'report.md').stat().st_size <= 2 * 1024 * 1024:
            errors.append('missing or oversized report')
        got = submitted('results/summary.json', {})
        case_rows = ordered_rows(got.pop('cases', None), 'id', case_ids, errors, 'cases')
        compare_rows = ordered_rows(got.pop('comparisons', None), 'benchmark_id', benchmark_ids, errors, 'comparisons')
        summary_ok = same(got, summary, atol, rtol)
        if not summary_ok:
            errors.append('summary metadata differs')
        got = submitted('conclusion.json', {})
        rank_rows = ordered_rows(got.pop('rankings', None), 'benchmark_id', benchmark_ids, errors, 'rankings')
        conclusion_ok = same(got, conclusion, atol, rtol)
        if not conclusion_ok:
            errors.append('conclusion metadata differs')
        trace_rows = ordered_rows(submitted('results/trace.json', []), 'case_id', case_ids, errors, 'traces')
        actual_files = set()
        for case in cases:
            case_id = case['id']
            matches = same(case_rows.get(case_id), case, atol, rtol)
            if not matches:
                errors.append(case_id + ' summary differs')
            try:
                check_trace(actual, expected, trace_rows.get(case_id), traces[case_id], actual_files, atol, rtol)
                case_passed[case_id] = summary_ok and matches
            except Exception as exc:
                errors.append(f'{case_id}: {exc}')
        for comparison in comparisons:
            bid = comparison['benchmark_id']
            matches = same(compare_rows.get(bid), comparison, atol, rtol) and same(rank_rows.get(bid), rankings[bid], atol, rtol)
            comparison_passed[bid] = summary_ok and conclusion_ok and matches
            if not matches:
                errors.append(bid + ' comparison or conclusion ranking differs')
        if {path.name for path in (actual / 'results').glob('*.npy')} != actual_files:
            errors.append('numerical result inventory differs')
    except Exception as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
    return {'passed': not errors, 'errors': errors, 'case_passed': case_passed, 'comparison_passed': comparison_passed,
            'atol': atol, 'rtol': rtol}


def control_inputs(bundle, output, registry, benchmark_id):
    """Perturb one benchmark, keeping its candidates paired and all other caches intact."""
    import copy
    import numpy as np
    require(benchmark_id in bundle['instance']['benchmark_ids'], 'unknown control benchmark')
    root = new_directory(output)
    paths = []
    for i, packet in enumerate(bundle['packets']):
        if packet['manifest']['benchmark_id'] != benchmark_id:
            paths.append(packet['root'])
            continue
        arrays, metadata = dict(packet['arrays']), copy.deepcopy(packet['metadata'])
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
        value = save(root / ('packet-%02d' % i), registry, benchmark_id, packet['manifest']['candidate_id'],
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
    report = {'schema': 'bpb-bs-grade/2', 'state': 'scoring_failed', 'analysis_success': None,
              'subtask_scores': {}, 'comparison_scores': {},
              'isolation': isolation, 'prose_review': 'not_assessed', 'acceptance': 'experimental-data-and-agent-validation-pending'}
    started = time.monotonic()
    try:
        bundle = load(inputs, registry)
        instance = bundle['instance']
        subtask_ids = instance.get('subtask_ids', [instance['id']])
        comparison_ids = instance['benchmark_ids'] if instance['template'] == 't2-compare' else []
        report['subtask_scores'] = dict.fromkeys(subtask_ids)
        report['comparison_scores'] = dict.fromkeys(comparison_ids)
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

        def replay(input_dir, worker_output, reference):
            try:
                executor.run(source, input_dir, worker_output)
            except AnalysisFailure as exc:
                # Process-mode inputs are writable. A failed local run may have changed them.
                if isolation != 'docker':
                    raise
                return {'passed': False, 'worker_failed': True, 'errors': [str(exc)], 'case_passed': {}, 'comparison_passed': {}}
            return compare(worker_output, reference)

        with tempfile.TemporaryDirectory(prefix='bpb-bs-owner-') as temp:
            owner = Path(temp)
            reference = owner / 'reference'
            run(inputs, reference, registry)
            comparisons = [{'kind': 'rerun', **replay(bundle['root'], root / 'worker-output', reference)}]
            if saved_results:
                comparisons.append({'kind': 'saved', **compare(saved_results, reference)})
            for index, bid in enumerate(instance['benchmark_ids']):
                with tempfile.TemporaryDirectory(dir=owner) as temp_control:
                    control_dir = Path(temp_control)
                    altered = control_inputs(bundle, control_dir / 'control', registry, bid)
                    control_reference = control_dir / 'reference'
                    run(altered['root'], control_reference, registry)
                    output_dir = root / ('control-output' if index == 0 else f'control-{index}-output')
                    comparisons.append({'kind': 'functional-control', 'benchmark_id': bid,
                                        **replay(altered['root'], output_dir, control_reference)})

            def component_score(field, key, benchmark):
                checks = [row for row in comparisons if row.get('benchmark_id', benchmark) == benchmark]
                return int(all(row[field].get(key, False) for row in checks))

            case_ids = {(p['manifest']['benchmark_id'], p['manifest']['candidate_id']): f'case-{i:02d}'
                        for i, p in enumerate(bundle['packets'])}
            for subtask_id in subtask_ids:
                subtask = registry['subtasks'][subtask_id]
                bid, cid = subtask['benchmark_ids'][0], subtask['candidate_ids'][0]
                report['subtask_scores'][subtask_id] = component_score('case_passed', case_ids[bid, cid], bid)
            for bid in comparison_ids:
                report['comparison_scores'][bid] = component_score('comparison_passed', bid, bid)
            report.update(state='scored', analysis_success=int(all(c['passed'] for c in comparisons)), comparisons=comparisons)
            if not any(check.get('worker_failed') for check in comparisons):
                report.update(inputs_unchanged=True, source_unchanged=True)
    except AnalysisFailure as exc:
        report.update(state='scored', analysis_success=0, error=str(exc))
        for field in ('subtask_scores', 'comparison_scores'):
            report[field] = dict.fromkeys(report[field], 0)
    except Exception as exc:
        report.update(state='scoring_failed', analysis_success=None, error='%s: %s' % (type(exc).__name__, exc))
        for field in ('subtask_scores', 'comparison_scores'):
            report[field] = dict.fromkeys(report[field])
    report['wall_seconds'] = time.monotonic() - started
    write_json(root / 'grade.json', report)
    return report
