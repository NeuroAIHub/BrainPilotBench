"""Trusted parent computes reference outputs, evaluates artifacts and owns BPB_SCORES."""
import argparse
from pathlib import Path
import secrets
import platform
import shutil
import tempfile
import time
import sys

import numpy as np
from compare import compare, regular_tree
from contract import ContractError, REQUIRED, TASK_ID, VERSION, digest, load_packet, read_json, write_json
from execution import AnalysisFailure, Executor, InfrastructureError
from fixtures import generate, variant
from reference import run as reference_run


def prediction_values(output):
    with np.load(Path(output) / 'results/predictions.npz', allow_pickle=False) as z:
        return {(str(f), str(s), str(u)): float(z['values'][i, j])
                for i, (f, s) in enumerate(zip(z['fold_ids'], z['stimulus_ids']))
                for j, u in enumerate(z['neuroid_ids'])}


def evaluate(bundle, executor=None, seed=None):
    bundle = Path(bundle).resolve()
    artifacts = bundle / 'artifacts'
    started = time.monotonic()
    report = {'schema': 'bpb-alignment-score/1', 'synthetic_only': True, 'task_id': TASK_ID,
              'task_version': VERSION, 'status': 'scoring_failed', 'analysis_success': None,
              'checks': [], 'report_interpretation': 'human_review_required'}
    try:
        meta = read_json(bundle / 'meta.json')
        if meta.get('taskId') != TASK_ID or meta.get('taskVersion') != VERSION or not meta.get('agent'):
            raise ContractError('meta.json task/version/agent binding')
        for rel in REQUIRED:
            if not (artifacts / rel).is_file():
                raise ContractError('missing artifact: ' + rel)
        regular_tree(artifacts)
    except (ContractError, OSError, ValueError, TypeError, AttributeError) as exc:
        report.update(status='submission_invalid', error=str(exc))
        return report
    executor = executor or Executor()
    report['isolation'] = executor.mode
    seed = secrets.randbits(32) if seed is None else seed
    report['case_seeds'] = {'public': 1729, 'novel': seed}
    report['provenance'] = {'python': platform.python_version(), 'numpy': np.__version__,
                            'parent_sources': {p.name: digest(p) for p in Path(__file__).parent.glob('*.py')}}
    report['security_boundary'] = 'container' if executor.mode == 'docker' else 'none-trusted-local-only'
    try:
        executor.preflight()
        with tempfile.TemporaryDirectory(prefix='bpb-alignment-parent-') as tmp:
            root = Path(tmp)
            public = generate(root / 'public')
            novel = generate(root / 'novel', seed)
            cases = {'public': public, 'repeat': public,
                     'permuted': variant(public, root / 'permuted', 'permuted'),
                     'novel': novel, 'test-y': variant(novel, root / 'test-y', 'test-y')}
            # Parent validates/generates every oracle before any untrusted worker runs.
            references = {}
            report['input_manifests'] = {}
            for name, inputs in cases.items():
                packet = load_packet(inputs)
                report['input_manifests'][name] = packet['manifest_hash']
                references[name] = root / ('reference-' + name)
                reference_run(inputs, references[name])
                if not compare(references[name], references[name])['passed']:
                    raise InfrastructureError('reference output failed validation')
            public_check = compare(artifacts, references['public'])
            report['checks'].append({'case': 'saved-public', **public_check})
            outputs, valid = {}, {}
            for name, inputs in cases.items():
                # Only source files, one X/Y packet and an empty output directory cross the boundary.
                source = root / ('source-' + name)
                shutil.copytree(artifacts / 'submission', source)
                output = root / ('output-' + name)
                outputs[name] = output
                try:
                    executor.run(source, inputs, output)
                    result = compare(output, references[name])
                except (AnalysisFailure, ContractError, ValueError, OSError) as exc:
                    result = {'passed': False, 'errors': [str(exc)], 'max_abs_error': None}
                valid[name] = result['passed']
                report['checks'].append({'case': name, **result})
            if valid.get('public') and valid.get('repeat'):
                result = compare(outputs['repeat'], outputs['public'])
                report['checks'].append({'case': 'reproducibility', **result})
            if valid.get('novel') and valid.get('test-y'):
                before, after = prediction_values(outputs['novel']), prediction_values(outputs['test-y'])
                delta = max(abs(value - after[key]) for key, value in before.items() if key[0] == 'fold-0')
                report['checks'].append({'case': 'test-y-prediction-invariance', 'passed': delta <= 1e-8,
                                         'max_abs_error': delta, 'errors': [] if delta <= 1e-8 else ['test Y changed predictions']})
            passed = all(check['passed'] for check in report['checks'])
            errors = [c['max_abs_error'] for c in report['checks'] if c['max_abs_error'] is not None]
            report.update(status='scored', outcome='analysis_correct' if passed else 'analysis_failed',
                          analysis_success=int(passed), max_abs_error=max(errors) if errors else None,
                          reference_match_rate=sum(c['passed'] for c in report['checks']) / len(report['checks']))
    except Exception as exc:
        # Worker failures are caught above. Unexpected parent/oracle failures never become an Agent zero.
        report.update(status='scoring_failed', analysis_success=None, error=f'{type(exc).__name__}: {exc}')
    report['elapsed_seconds'] = time.monotonic() - started
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--seed', type=int, help='maintainer replay of a recorded novel fixture seed')
    args = parser.parse_args()
    report = evaluate(args.bundle, seed=args.seed)
    write_json(args.bundle / 'alignment-score.json', report)
    if report['status'] == 'scored':
        print('>>>>> BPB_SCORES')
        print('{"analysis_success": ' + str(report['analysis_success']) + '}')
        print('<<<<< BPB_SCORES')
    else:
        # Do not echo submitted filenames/errors onto the sentinel parsing channel.
        print('alignment evaluator: ' + report['status'], file=sys.stderr)


if __name__ == '__main__':
    main()
