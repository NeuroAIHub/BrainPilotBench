#!/usr/bin/env python3
"""Brain-Score scale-up registry, task drafts and local cache checks. Never downloads."""
import argparse
import json
import os
import sys

from brainscore import ScaleUpError
from brainscore.registry import ADAPTERS, DEFAULT_ROOT, blockers, load, summary
from real_brainscore import BackendError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default=str(DEFAULT_ROOT))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('validate', help='Validate the planning whitelist; does not mean runnable')
    listing = commands.add_parser('list')
    listing.add_argument('--phase', choices=['P1', 'P2', 'P3', 'P4'])
    preflight = commands.add_parser('preflight', help='Report unresolved real-preparation and acceptance gates')
    preflight.add_argument('--instance')
    preflight.add_argument('--require-ready', action='store_true', help='Exit 2 while any selected instance is blocked')
    draft = commands.add_parser('draft', help='Render contracts/prompts outside Git without registering tasks')
    draft.add_argument('--output', required=True)
    draft.add_argument('--phase', choices=['P1', 'P2', 'P3', 'P4'])
    fixture = commands.add_parser('fixture', help='Generate a tiny synthetic cache-contract example')
    fixture.add_argument('--output', required=True)
    fixture.add_argument('--adapter', choices=sorted(ADAPTERS), default='vision-neural')
    verify = commands.add_parser('verify-packet', help='Local integrity/identity/missingness check, not official equivalence')
    verify.add_argument('--inputs', required=True)
    runtime = commands.add_parser('runtime', help='Check pinned installed software without fetching assets')
    runtime.add_argument('--ecosystem', choices=['vision', 'language'], required=True)
    environment = commands.add_parser('worker-context', help='Export installed software only for an offline Docker build')
    environment.add_argument('--ecosystem', choices=['vision', 'language'], required=True)
    environment.add_argument('--output', required=True)
    environment.add_argument('--base-image', required=True)
    audit = commands.add_parser('audit-sources', help='Check original local files against upstream object locks')
    audit.add_argument('--raw', required=True)
    audit.add_argument('--benchmark', required=True)
    audit.add_argument('--metadata-only', action='store_true')
    prepare = commands.add_parser('prepare', help='Official local-only experiment, cache export and equivalence check')
    prepare.add_argument('--raw', required=True)
    prepare.add_argument('--benchmark', dest='benchmark_id', required=True)
    prepare.add_argument('--candidate', dest='candidate_id', required=True)
    prepare.add_argument('--model-dir')
    prepare.add_argument('--output', required=True)
    prepare.add_argument('--reference-output', required=True)
    prepare.add_argument('--image-digest', required=True)
    model = commands.add_parser('seal-model', help='Validate and copy existing local model/tokenizer assets')
    model.add_argument('--source', required=True)
    model.add_argument('--output', required=True)
    model.add_argument('--candidate', dest='candidate_id', required=True)
    bundle = commands.add_parser('bundle', help='Bind prepared caches to a single explicit instance')
    bundle.add_argument('--packet', dest='packet_paths', action='append', required=True)
    bundle.add_argument('--instance', dest='instance_id', required=True)
    bundle.add_argument('--output', required=True)
    example = commands.add_parser('fixture-instance', help='Run official protocols on synthetic local inputs')
    example.add_argument('--instance', dest='instance_id', required=True)
    example.add_argument('--output', required=True)
    baseline = commands.add_parser('reference-submission', help='Export maintainer-only baseline; never task setup')
    baseline.add_argument('--output', required=True)
    for name in ('reference', 'evaluate', 'stage', 'workspace'):
        command = commands.add_parser(name)
        command.add_argument('--inputs', required=True)
        command.add_argument('--output', required=True)
        if name == 'evaluate':
            command.add_argument('--submission', required=True)
            command.add_argument('--saved-results')
            command.add_argument('--image', default=os.environ.get('BPB_INFERENCE_IMAGE'))
            command.add_argument('--isolation', choices=['docker', 'process'], default='docker')
            command.add_argument('--timeout', type=float, default=900.)
            command.add_argument('--cpus', type=float, default=2.)
            command.add_argument('--memory', default='8g')
        elif name == 'stage':
            command.add_argument('--verification', dest='verification_paths', action='append', default=[])
            command.add_argument('--allow-synthetic', action='store_true')
        elif name == 'workspace':
            command.add_argument('--contract', required=True)
    args = parser.parse_args()
    registry = load(args.registry)
    code = 0
    if args.command == 'validate':
        result = {'registry_valid': True, **summary(registry)}
    elif args.command == 'list':
        result = {'summary': summary(registry), 'instances': [i for i in registry['instances'].values()
                  if args.phase is None or i['phase'] == args.phase]}
    elif args.command == 'preflight':
        selected = list(registry['instances'].values())
        if args.instance:
            if args.instance not in registry['instances']:
                raise ScaleUpError('unknown instance: ' + args.instance)
            selected = [registry['instances'][args.instance]]
        entries = [{'id': i['id'], 'blockers': blockers(registry, i)} for i in selected]
        for entry in entries:
            entry['ready'] = not entry['blockers']
        result = {'summary': summary(registry), 'instances': entries, 'state': 'preparation-pending'}
        code = 2 if args.require_ready and any(not entry['ready'] for entry in entries) else 0
    elif args.command == 'draft':
        from brainscore.templates import draft
        result = draft(registry, args.output, args.phase)
    elif args.command in ('fixture', 'verify-packet'):
        if args.command == 'fixture':
            from brainscore.fixtures import create
            packet = create(args.output, registry, args.adapter)
        else:
            from brainscore.packet import load as load_packet
            packet = load_packet(args.inputs, registry)
        result = {'inputs': str(packet['root']), 'manifest_sha256': packet['manifest_sha256'],
                  'synthetic_only': packet['manifest']['synthetic_only'], 'contract_valid': True,
                  'verification_scope': packet['verification_scope'], 'official_equivalence': packet['official_equivalence']}
    else:
        values = vars(args).copy()
        command = values.pop('command')
        values['registry'] = registry
        if command == 'runtime':
            from brainscore.runtime import check, offline
            with offline():
                result = check(args.ecosystem, registry['root'])
        elif command == 'worker-context':
            from brainscore.environment import export
            result = export(**values)
        elif command == 'audit-sources':
            from brainscore.local_sources import audit
            result = audit(args.raw, registry, args.benchmark, images=not args.metadata_only)
            code = 0 if result['local_objects_complete'] else 2
        elif command == 'prepare':
            from brainscore.preparation import prepare
            result = prepare(**values)
        elif command == 'seal-model':
            from brainscore.models import seal_model
            result = seal_model(**values)
        elif command == 'bundle':
            from brainscore.bundle import create
            value = create(**values)
            result = {'inputs': str(value['root']), 'manifest_sha256': value['manifest_sha256']}
        elif command == 'fixture-instance':
            from brainscore.scientific_fixtures import create
            result = create(**values)
        elif command == 'reference-submission':
            from brainscore.baseline import export
            result = export(**values)
        elif command == 'reference':
            from brainscore.analysis import run
            result = run(**values)
        elif command in ('stage', 'workspace'):
            from brainscore import staging
            result = getattr(staging, command)(**values)
        else:
            from brainscore.evaluation import evaluate
            result = evaluate(**values)
            if result['state'] == 'scored':
                print('>>>>> BPB_SCORES\n' + json.dumps({'analysis_success': result['analysis_success']}) + '\n<<<<< BPB_SCORES')
            else:
                code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ScaleUpError, BackendError, OSError, ImportError, ValueError, TypeError, KeyError) as exc:
        print('brainscore scale-up: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(1)
