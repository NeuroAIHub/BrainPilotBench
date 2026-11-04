#!/usr/bin/env python3
"""Explicit Task A preparation, reference and isolated scoring; no downloads."""
import argparse
import json
import os
import sys

from incremental import IncrementalError
from real_brainscore import BackendError
from real_brainscore.common import read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--cache', required=True)
    prepare.add_argument('--output', required=True)
    prepare.add_argument('--layer')
    reference = commands.add_parser('reference')
    reference.add_argument('--inputs', required=True)
    reference.add_argument('--plan', required=True)
    reference.add_argument('--output', required=True)
    submission = commands.add_parser('reference-submission')
    submission.add_argument('--output', required=True)
    submission.add_argument('--control-set', default='word_count+position')
    for name in ('stage', 'workspace', 'evaluate'):
        p = commands.add_parser(name)
        p.add_argument('--inputs', required=True)
        p.add_argument('--output', required=True)
        if name == 'workspace':
            p.add_argument('--contract', required=True)
        if name == 'evaluate':
            p.add_argument('--submission', required=True)
            p.add_argument('--saved-results')
            p.add_argument('--image', default=os.environ.get('BPB_INFERENCE_IMAGE'))
            p.add_argument('--isolation', choices=['docker', 'process'], default='docker')
            p.add_argument('--timeout', type=float, default=900)
            p.add_argument('--cpus', type=float, default=os.environ.get('BPB_ALIGNMENT_WORKER_CPUS', '2'))
            p.add_argument('--memory', default='8g')
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command == 'prepare':
        from incremental.data import prepare
        result = prepare(**args)
    elif command == 'reference':
        from incremental.analysis import run_analysis
        args['plan'] = read_json(args['plan'])
        result = run_analysis(**args)
    elif command == 'reference-submission':
        from incremental.analysis import reference_submission
        result = reference_submission(**args)
    elif command in ('stage', 'workspace'):
        from incremental import staging
        result = getattr(staging, command)(**args)
    else:
        from incremental.evaluation import evaluate
        result = evaluate(**args)
        if result['state'] == 'scored':
            print('>>>>> BPB_SCORES\n' + json.dumps({'analysis_success': result['analysis_success']}) + '\n<<<<< BPB_SCORES')
        else:
            print(json.dumps(result), file=sys.stderr)
            return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (IncrementalError, BackendError, OSError, ImportError) as exc:
        print('incremental task: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(1)
