"""Owner CLI for the fixed-budget multiscale experiment."""
import argparse
import json
import os
from pathlib import Path

# Keep saved and replayed ridge maps deterministic on the same numerical stack.
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '2'

from real_brainscore.common import read_json
from multiscale.preparation import Packet, prepare
from multiscale.session import STAGES, call, observed_conclusion, verify_run


def baseline(packet, model_dir, until):
    actor = 'fixed-top-k'
    overview = call(packet, actor, 'open', {})
    inspected = []
    for i, row in enumerate(overview['sites'][:2], 1):
        choice = {'layer': row['layer'], 'position': row['position'], 'units': row['order_units'],
                  'reason': f'按搜索集标准化原序减乱序激活差排序，检查排名第 {i} 的层与读取位置。'}
        inspected.append(call(packet, actor, 'inspect' + str(i), choice))
    delta = inspected[0]['dev_delta_r']
    forecast = [max(-2., delta - .10), min(2., delta + .10)] if delta is not None else [-.10, .10]
    decision = {**inspected[0]['group'], 'reason': '固定选择训练词序效应排名第一的组合。', 'contrast': 'reverse',
                'hypotheses': [{'explanation': '词序偏好会在新句中复现。', 'activation': 'up'},
                               {'explanation': '偏好来自末词位置，位置匹配后差异接近零。', 'activation': 'flat'}],
                'expected_interaction': 'up', 'expected_delta_r': forecast}
    frozen = call(packet, actor, 'freeze', decision)
    if until == 'freeze':
        return frozen
    measured = call(packet, actor, 'probe', {}, model_dir)
    scored = call(packet, actor, 'score', {})
    call(packet, actor, 'conclude', {**observed_conclusion(measured, scored),
                                    'conclusion': '固定策略按确认阈值和逐人增益自动归纳。'})
    return scored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    prep = commands.add_parser('prepare')
    for name in ('csv', 'model-dir', 'root'):
        prep.add_argument('--' + name, required=True)
    prep.add_argument('--f-inputs')
    prep.add_argument('--f-hidden')
    run = commands.add_parser('call')
    run.add_argument('stage', choices=STAGES)
    run.add_argument('--actor', required=True)
    run.add_argument('--request', type=Path)
    run.add_argument('--model-dir')
    fixed = commands.add_parser('top-k')
    fixed.add_argument('--model-dir', required=True)
    fixed.add_argument('--until', choices=['freeze', 'score'], default='score')
    export = commands.add_parser('export')
    export.add_argument('--actor', required=True)
    export.add_argument('--out', required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--actor', required=True)
    verify.add_argument('--model-dir', required=True)
    replay = commands.add_parser('replay')
    replay.add_argument('--bundle', required=True)
    replay.add_argument('--model-dir', required=True)
    restore = commands.add_parser('restore', help='regenerate the historical replay from compact decision receipts')
    restore.add_argument('--record', required=True)
    restore.add_argument('--model-dir', required=True)
    restore.add_argument('--out', required=True)
    for cmd in (run, fixed, export, verify, replay, restore):
        cmd.add_argument('--root', required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.csv, args.model_dir, args.root, args.f_inputs, args.f_hidden)
    else:
        packet = Packet(args.root)
        if args.action == 'call':
            result = call(packet, args.actor, args.stage, read_json(args.request) if args.request else {}, args.model_dir)
        elif args.action == 'top-k':
            result = baseline(packet, args.model_dir, args.until)
        elif args.action == 'verify':
            result = verify_run(packet, args.actor, args.model_dir)
        elif args.action == 'replay':
            from multiscale.replay import verify_export
            result = verify_export(packet, args.bundle, args.model_dir)
        elif args.action == 'restore':
            from multiscale.replay import restore_replay
            result = restore_replay(packet, args.record, args.model_dir, args.out)
        else:
            from multiscale.replay import export_replay
            result = export_replay(packet, args.actor, args.out)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
