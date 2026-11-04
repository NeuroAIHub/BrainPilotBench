#!/usr/bin/env python3
"""Explicit Linux-server entry points; --help and import perform no downloads."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import sys

from real_brainscore import COMMIT, REAL_PROFILE, REAL_TASK_ID, REAL_VERSION, BackendError
from real_brainscore.common import read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Inspect installed metadata; does not load models/data')
    resolve = commands.add_parser('resolve-config', help='Resolve immutable Hugging Face revision metadata')
    resolve.add_argument('--config', required=True)
    resolve.add_argument('--output', required=True)
    resolve.add_argument('--revision', default='main')
    resolve.add_argument('--tokenizer-revision')
    resolve.add_argument('--allow-download', action='store_true')
    prepare = commands.add_parser('prepare', help='Fetch real inputs and cache all configured layers on the server')
    prepare.add_argument('--config', required=True)
    prepare.add_argument('--output', required=True)
    prepare.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    prepare.add_argument('--allow-download', action='store_true')
    fixed = commands.add_parser('score-fixed', help='Run pinned official scoring on a verified local cache')
    fixed.add_argument('--cache', required=True)
    fixed.add_argument('--output', required=True)
    fixed.add_argument('--layer')
    fixed.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    fixed.add_argument('--compare-live', action='store_true')
    fixed.add_argument('--allow-download', action='store_true')
    profile = commands.add_parser('build-profile', help='Reserve confirmation materials BEFORE fitting or layer selection')
    profile.add_argument('--cache', required=True)
    profile.add_argument('--output', required=True)
    profile.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    profile.add_argument('--seed', type=int, default=17)
    profile.add_argument('--fraction', type=float, default=.2)
    profile.add_argument('--folds', type=int, default=5)
    profile.add_argument('--margin', type=float, default=.02)
    evaluate = commands.add_parser('evaluate', help='Compare a submitted analyzer in a local Docker image')
    evaluate.add_argument('--cache', required=True)
    evaluate.add_argument('--submission', required=True)
    evaluate.add_argument('--output', required=True)
    evaluate.add_argument('--image', default=os.environ.get('BPB_INFERENCE_IMAGE'))
    evaluate.add_argument('--saved-results')
    evaluate.add_argument('--timeout', type=int, default=900)
    evaluate.add_argument('--memory', default='8g')
    evaluate.add_argument('--cpus', type=float, default=os.environ.get('BPB_ALIGNMENT_WORKER_CPUS', '4'),
                          help='Worker CPU quota; defaults to BPB_ALIGNMENT_WORKER_CPUS or 4')
    for name in ('stage-task1', 'stage-task2'):
        stage = commands.add_parser(name, help='Create an experimental task outside the repository for explicit --tasks use')
        stage.add_argument('--input', required=True, help='Task1 cache directory or Task2 packet.json')
        stage.add_argument('--output', required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command == 'doctor':
        versions = {}
        for package in ('brainscore-language', 'brainscore-core', 'numpy', 'scipy', 'pandas', 'torch', 'transformers', 'scikit-learn'):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        result = {'platform': sys.platform, 'python': sys.version, 'upstream_commit_required': COMMIT,
                  'packages': versions, 'execution_tested': False}
    elif command.startswith('stage-'):
        from real_brainscore.staging import stage_task
        result = stage_task(command[-1], args['input'], args['output'])
    else:
        from real_brainscore import pipeline
        if command == 'resolve-config':
            args['source'] = args.pop('config')
            result = pipeline.resolve_config(**args)
        elif command == 'prepare':
            args['configuration_path'] = args.pop('config')
            result = pipeline.prepare(**args)
        elif command == 'score-fixed':
            result = pipeline.score_fixed(**args)
        elif command == 'build-profile':
            result = pipeline.build_profile(**args)
        else:
            from real_brainscore.evaluation import evaluate
            result = evaluate(**args)
            if result['state'] == 'scored':
                print('>>>>> BPB_SCORES\n' + json.dumps({'analysis_success': result['analysis_success']}) + '\n<<<<< BPB_SCORES')
            else:
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
                return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (BackendError, OSError, ImportError) as exc:
        print('alignment server: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(1)
