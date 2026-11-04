#!/usr/bin/env python3
"""Explicit B–F preparation, staging, maintainer baselines and isolated grading."""
import argparse
import json
import os
import sys

from expansion import ExpansionError
from real_brainscore import BackendError
from real_brainscore.common import read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('download', 'verify-sources'):
        p = commands.add_parser(name)
        p.add_argument('--raw', required=True)
        p.add_argument('--task', choices=list('CDEF'), required=True)
    conversion = commands.add_parser('convert-eeg2')
    conversion.add_argument('--raw', required=True)
    conversion.add_argument('--output', required=True)
    conversion.add_argument('--image', required=True)
    for task in 'BCDEF':
        p = commands.add_parser('prepare-' + task.lower())
        p.add_argument('--output', required=True)
        if task == 'B':
            p.add_argument('--source', required=True, help='Sealed context-pilot artifact directory')
        elif task == 'C':
            p.add_argument('--raw', required=True, help='Audited local THINGS IT and behavior files')
        elif task == 'D':
            p.add_argument('--converted', required=True, help='Sealed pickle-free EEG2 conversion')
        else:
            p.add_argument('--csv', required=True)
        if task in 'CDF':
            p.add_argument('--cache', required=True, help='Verified existing distilgpt2/Brain-Score cache config')
        if task == 'F':
            p.add_argument('--hidden', required=True, help='Separate owner-only response packet destination')
    reference = commands.add_parser('reference')
    reference.add_argument('--inputs', required=True)
    reference.add_argument('--plan', required=True)
    reference.add_argument('--output', required=True)
    baseline = commands.add_parser('reference-submission')
    baseline.add_argument('--task', choices=list('BCDEF'), required=True)
    baseline.add_argument('--output', required=True)
    for name in ('stage', 'workspace', 'evaluate'):
        p = commands.add_parser(name)
        p.add_argument('--inputs', required=True)
        p.add_argument('--output', required=True)
        if name == 'workspace':
            p.add_argument('--contract', required=True)
        else:
            p.add_argument('--hidden')
            p.add_argument('--ledger')
        if name == 'evaluate':
            p.add_argument('--submission', required=True)
            p.add_argument('--saved-results')
            p.add_argument('--image', default=os.environ.get('BPB_INFERENCE_IMAGE'))
            p.add_argument('--isolation', choices=['docker', 'process'], default='docker')
            p.add_argument('--timeout', type=float, default=900.)
            p.add_argument('--cpus', type=float, default=float(os.environ.get('BPB_ALIGNMENT_WORKER_CPUS', '2')))
            p.add_argument('--memory', default='8g')
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command in ('download', 'verify-sources'):
        from expansion.sources import download, unpack
        result = (download if command == 'download' else unpack)(**args)
    elif command == 'convert-eeg2':
        from expansion.preparation import convert_eeg2
        result = convert_eeg2(**args)
    elif command.startswith('prepare-'):
        import importlib
        from expansion.runner import MODULES
        packet = importlib.import_module('expansion.' + MODULES[command[-1].upper()]).prepare(**args)
        result = {'inputs': str(packet['root']), 'manifest_sha256': packet['manifest_sha256']} if 'root' in packet else packet
    elif command in ('reference', 'reference-submission'):
        from expansion.runner import reference_submission, run
        if command == 'reference':
            args['plan'] = read_json(args['plan'])
            result = run(**args)
        else:
            result = reference_submission(**args)
    elif command in ('stage', 'workspace'):
        from expansion import staging
        result = getattr(staging, command)(**args)
    else:
        from expansion.evaluation import evaluate
        result = evaluate(**args)
        if result['state'] != 'scored':
            print(json.dumps(result, ensure_ascii=False, allow_nan=False), file=sys.stderr)
            return 1
        scores = ({'selection_effect': result['selection_effect'], 'selection_valid': result['selection_valid']}
                  if result['task'] == 'F' else {'analysis_success': result['analysis_success']})
        print('>>>>> BPB_SCORES\n' + json.dumps(scores, allow_nan=False) + '\n<<<<< BPB_SCORES')
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ExpansionError, BackendError, OSError, ImportError) as exc:
        print('expansion task: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(1)
