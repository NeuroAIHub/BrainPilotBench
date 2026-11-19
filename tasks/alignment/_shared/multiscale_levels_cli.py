"""Prepare, run, stage and grade one independent multiscale task."""
import argparse
import json
import os

os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '2'

from multiscale.breadth import CARDS, grade, prepare_card, public_packet, reference, stage
from real_brainscore.common import read_json, write_json


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest='cmd', required=True)
    get = commands.add_parser('fetch-unit')
    get.add_argument('--jamali-dir', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--level', type=int, choices=CARDS, required=True)
    for key in ('jamali-dir', 'model-dir', 'language-root', 'tops-dir'):
        prep.add_argument('--' + key)
    prep.add_argument('--csv', dest='csv_file')
    staged = commands.add_parser('stage')
    staged.add_argument('--out', required=True)
    staged.add_argument('--actor', required=True)
    staged.add_argument('--reference-check', action='store_true',
                        help='include the Oracle/NOP check in a dedicated maintainer task root')
    ref = commands.add_parser('reference')
    ref.add_argument('--out', required=True)
    score = commands.add_parser('grade')
    score.add_argument('--actor', required=True)
    score.add_argument('--answer', required=True)
    score.add_argument('--bench', action='store_true')
    for p in (prep, staged, ref, score):
        p.add_argument('--root', required=True)
    args = cli.parse_args()
    if args.cmd == 'fetch-unit':
        from multiscale.single_cell import fetch
        result = fetch(args.jamali_dir)
    elif args.cmd == 'prepare':
        result = prepare_card(args.level, args.root, vars(args))
    elif args.cmd == 'stage':
        result = stage(args.root, args.out, args.actor, args.reference_check)
    elif args.cmd == 'reference':
        public, _ = public_packet(args.root)
        result = reference(public)
        write_json(args.out, result)
    else:
        result = grade(args.root, args.actor, read_json(args.answer))
        if args.bench:
            print('>>>>> BPB_SCORES\n' + json.dumps(result['scores'], allow_nan=False) + '\n<<<<< BPB_SCORES')
            return
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
