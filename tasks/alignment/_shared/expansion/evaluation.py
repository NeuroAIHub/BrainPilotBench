"""Owner recomputation and isolated submission replay. F hides responses."""
from pathlib import Path
import tempfile
import time

from execution import AnalysisFailure, Executor, InfrastructureError, snapshot
from incremental.evaluation import same
from real_brainscore.common import new_directory, read_json, separate_paths, write_json
from .packet import LIMIT, array, load
from .protocol import validate_plan
from .runner import run


def bounded_output(root):
    root = Path(root)
    paths = list(root.rglob('*'))
    if any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in paths):
        raise AnalysisFailure('nonregular output')
    if sum(p.stat().st_size for p in paths if p.is_file()) > LIMIT:
        raise AnalysisFailure('output exceeds 512 MiB')
    report = root / 'report.md'
    if not report.is_file() or not 0 < report.stat().st_size < 2 * 1024 * 1024:
        raise AnalysisFailure('missing or oversized report')


def compare(actual, expected):
    import numpy as np
    errors = []
    try:
        bounded_output(actual)
        for rel in ('analysis_plan.json', 'results/summary.json', 'conclusion.json'):
            if not same(read_json(Path(actual) / rel), read_json(Path(expected) / rel)):
                errors.append(rel + ' differs')
        wanted = {p.name for p in (Path(expected) / 'results').glob('*.npy')}
        got = {p.name for p in (Path(actual) / 'results').glob('*.npy')}
        if wanted != got:
            errors.append('array inventory differs')
        for name in wanted & got:
            a, b = array(Path(actual) / 'results' / name), array(Path(expected) / 'results' / name)
            equal = a.shape == b.shape and a.dtype == b.dtype
            if equal:
                equal = np.array_equal(a, b) if a.dtype.kind in 'biuU' else np.allclose(a, b, atol=1e-7, rtol=1e-5)
            if not equal:
                errors.append(name + ' differs')
    except Exception as exc:
        errors.append(str(exc))
    return {'passed': not errors, 'errors': errors}


def evaluate(inputs, submission, output, image=None, saved_results=None, isolation='docker',
             timeout=900, cpus=2., memory='8g', hidden=None, ledger=None):
    destination = new_directory(output)
    started = time.monotonic()
    report = {'schema': 'bpb-expansion-grade/1', 'state': 'scoring_failed',
              'analysis_success': None, 'isolation': isolation, 'prose_review': 'not_assessed',
              'acceptance': 'experimental-scientific-review-pending'}
    task = None
    try:
        packet = load(inputs)
        task = packet['task']
        report.update(task=task, protocol_id=packet['protocol']['protocol_id'],
                      synthetic_only=packet['manifest']['synthetic_only'], input_manifest_sha256=packet['manifest_sha256'])
        source = Path(submission).resolve()
        for a, b in ((source, packet['root']), (source, destination), (packet['root'], destination)):
            separate_paths(a, b)
        if task == 'F':
            if not hidden or not ledger:
                raise InfrastructureError('F requires an owner hidden packet and a persistent submission ledger')
            for a in (source, packet['root'], destination):
                separate_paths(a, hidden)
                separate_paths(a, ledger)
            separate_paths(hidden, ledger)
            if saved_results is not None:
                separate_paths(saved_results, hidden)
                separate_paths(saved_results, ledger)
            from .selection import load_hidden
            owner = load_hidden(hidden, packet)
        try:
            source_hashes = snapshot(source)
            if 'analyze.py' not in source_hashes:
                raise ValueError('analyze.py missing')
            plan = validate_plan(task, read_json(source / 'plan.json'), len(packet['metadata'].get('candidates', [])))
        except Exception as exc:
            raise AnalysisFailure('invalid submission: ' + str(exc)) from exc
        executor = Executor(isolation, timeout=timeout, cpus=cpus, memory=memory, tmpfs='512m')
        if image:
            executor.image = image
        executor.preflight()
        if isolation == 'docker':
            import json
            import numpy as np
            probe = executor.admin(['run', '--rm', '--pull=never', '--network=none', '--read-only', '--entrypoint', 'python',
                                    executor.image, '-B', '-c', 'import numpy; print(numpy.__version__)'])
            if probe.returncode or probe.stdout.strip() != np.__version__:
                raise InfrastructureError('owner and worker NumPy versions differ')
            identity = executor.admin(['image', 'inspect', '--format', '{{.Id}}', executor.image])
            if identity.returncode or not identity.stdout.strip().startswith('sha256:'):
                raise InfrastructureError('worker image identity unavailable')
            executor.image = identity.stdout.strip()
            report['image'] = executor.image
        report['worker_limits'] = {'timeout_seconds': timeout, 'cpus': cpus, 'memory': memory}
        worker_started = time.monotonic()
        executor.run(source, packet['root'], destination / 'worker-output')
        report['worker_wall_seconds'] = time.monotonic() - worker_started
        if task == 'F':
            from .selection import grade_selection
            report.update(grade_selection(packet, owner, destination / 'worker-output', saved_results,
                                          plan, source_hashes, ledger))
        else:
            with tempfile.TemporaryDirectory(prefix='bpb-expansion-owner-') as temp:
                expected = Path(temp) / 'reference'
                run(inputs, expected, plan)
                comparisons = [compare(destination / 'worker-output', expected)]
                if saved_results is not None:
                    comparisons.append(compare(saved_results, expected))
                report.update(state='scored', analysis_success=int(all(c['passed'] for c in comparisons)), comparisons=comparisons)
        report.update(inputs_unchanged=True, source_unchanged=True)
    except AnalysisFailure as exc:
        report.update(state='invalid_submission' if task == 'F' else 'scored',
                      analysis_success=None if task == 'F' else 0, error=str(exc))
        if task == 'F':
            report.update(selection_valid=0, selection_effect=None)
    except Exception as exc:
        report.update(state='scoring_failed', error='%s: %s' % (type(exc).__name__, exc))
    report['total_wall_seconds'] = time.monotonic() - started
    write_json(destination / 'grade.json', report)
    return report
