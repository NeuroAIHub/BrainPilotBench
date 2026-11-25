"""Prepare or run the Tuckute to Pereira L2 unit-selection pilot."""
import argparse
import json
import os
from pathlib import Path

os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '2'

from real_brainscore.common import read_json, write_json
from unit_transfer import MODELS
from unit_transfer.scoring import Packet
from unit_transfer.session import benchmark_rows, grade, record
from unit_transfer.staging import serve_dev, stage


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest='cmd', required=True)
    prep = commands.add_parser('prepare', help='build a packet from local weights and the original Tuckute/Pereira files')
    prep.add_argument('--csv', required=True)
    prep.add_argument('--pereira', required=True)
    prep.add_argument('--model', choices=MODELS, required=True)
    prep.add_argument('--model-dir', required=True)
    prep.add_argument('--batch-size', type=int, default=16)
    staged = commands.add_parser('stage', help='generate an experimental bp-bench task for one assigned actor')
    staged.add_argument('--out', required=True)
    staged.add_argument('--reference-check', action='store_true', help='include the Oracle/NOP check for a dedicated validation actor')
    serve = commands.add_parser('serve-dev', help='serve only development queries for the assigned actor')
    serve.add_argument('--exchange', required=True)
    serve.add_argument('--once', action='store_true')
    query = commands.add_parser('query', help='operator relay of a development request')
    fixed = commands.add_parser('baselines', help='score the two public-data-only policies')
    final = commands.add_parser('grade', help='freeze the strategy and score the agent and both controls')
    final.add_argument('--code', type=Path, required=True)
    final.add_argument('--bench', action='store_true')
    for p in (query, final):
        p.add_argument('--choice', type=Path, required=True)
    for p in (staged, serve, query, final):
        p.add_argument('--actor', required=True)
    for p in (prep, staged, serve, query, fixed, final):
        p.add_argument('--root', required=True)
    for p in (fixed, final):
        p.add_argument('--out', type=Path)
    args = cli.parse_args()
    if args.cmd == 'prepare':
        from unit_transfer.data import prepare
        result = prepare(args.csv, args.pereira, args.model, args.model_dir, args.root, args.batch_size)
    else:
        packet = Packet(args.root)
        if args.cmd == 'stage':
            result = stage(packet, args.out, args.actor, args.reference_check)
        elif args.cmd == 'serve-dev':
            serve_dev(packet, args.actor, args.exchange, args.once)
            return
        elif args.cmd == 'query':
            result = record(packet, args.actor, read_json(args.choice))
        elif args.cmd == 'baselines':
            result = {'model': packet.protocol['model']['id'], 'results': benchmark_rows(packet)}
        else:
            result = grade(packet, args.actor, read_json(args.choice), args.code)
        if args.cmd in ('baselines', 'grade') and args.out:
            write_json(args.out, result)
        if args.cmd == 'grade' and args.bench:
            scores = {name + '_delta_r': v['delta_r'] for name, v in result['results']['agent']['scores'].items()
                      if v['delta_r'] is not None}
            if 'search_delta_r' not in scores:
                cli.exit(1, 'undefined primary metric: constant joint prediction in a search cell\n')
            print('>>>>> BPB_SCORES\n' + json.dumps(scores, allow_nan=False) + '\n<<<<< BPB_SCORES')
            return
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
