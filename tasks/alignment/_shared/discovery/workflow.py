"""Standard preparation, two scalar queries and frozen public-only replay for either level."""
import argparse
import json
from pathlib import Path

from multiscale.analysis import difference
from real_brainscore.common import read_json, write_json
from unit_transfer import MODELS
from unit_transfer.session import freeze_and_replay, record
from unit_transfer.staging import serve_dev, stage_selection_task
from . import reference


def stage(task, packet, destination, actor, reference_check=False):
    model = packet.protocol['model']['id']
    spec = {'id': task.ID + '-' + model, 'domain': 'alignment', 'category': task.CATEGORY,
            'version': '0.1-server-draft', 'created_at': '2026-11-25', 'summary': task.TITLE + ' · ' + model,
            'timeout_min': 30, 'budget_tokens': None, 'requires': {'network': False, 'gpu': False},
            'expected_artifacts': [{'workspace': 'choice.json'}, {'workspace': 'strategy.py'}],
            'evaluation': {'profile': task.PROTOCOL, 'primary_metric': {
                'id': task.METRIC, 'direction': 'maximize', 'unit': task.UNIT}},
            'scoring': {'scorers': [{'kind': 'exec-script', 'script': 'checks/check.sh',
                                     'timeout_min': task.SCORE_MINUTES, 'submission_isolation': 'container'}]}}
    question = (f'在 {model} 上独立探索。' + task.QUESTION +
                '读取 public/protocol.json 了解维度和固定划分。choice.json 同时包含 packet_sha256'
                '（public/manifest.json 文件的 SHA-256）和 predicted_score（揭晓前预测，保留六位小数）。'
                'python query.py choice.json 最多查询两种不同选择，返回 dev_score。预测值不影响查询。'
                '提交 choice.json 与 strategy.py。python strategy.py public feedback.json 应仅用公开包和按顺序排列的'
                '真实回执数组，输出与最终提交相同的 JSON。复跑限 120 秒、2 核、2 GiB。'
                '逐条刺激和原始神经记录在本机处理，对话只返回汇总、候选与回执。')
    cli = Path(__file__).resolve().parents[1] / task.CLI
    example = Path(reference.__file__) if reference_check else None
    return stage_selection_task(packet, destination, actor, spec, question, cli, task.MEASUREMENT, example)


def baselines(packet):
    result = {}
    for policy in ('train_top', 'random'):
        choice = packet.choice(reference.select(packet.root / 'public', policy))
        result[policy] = {'choice': choice, 'scores': packet.scores('test', choice)}
    return result


def grade(packet, actor, choice, code):
    frozen, verified = freeze_and_replay(packet, actor, choice, code)
    pick = frozen['choice']
    scores = packet.scores('test', pick)
    controls = baselines(packet)
    primary = scores[packet.metric]
    scores['prediction_abs_error'] = None if primary is None else abs(primary - pick['predicted_score'])
    scores['gain_over_train_top'] = difference(primary, controls['train_top']['scores'][packet.metric])
    return {'actor': actor, 'model': packet.protocol['model']['id'], 'freeze': frozen, 'replay': verified,
            'results': {'agent': {'choice': pick, 'scores': scores}, **controls}}


def main(task):
    cli = argparse.ArgumentParser(description=task.TITLE)
    commands = cli.add_subparsers(dest='cmd', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--model', choices=MODELS, required=True)
    prep.add_argument('--model-dir', type=Path, required=True)
    prep.add_argument('--batch-size', type=int, default=8)
    prep.add_argument(task.SOURCE_FLAG, dest='source', type=Path, required=True)
    staging = commands.add_parser('stage')
    staging.add_argument('--out', type=Path, required=True)
    staging.add_argument('--reference-check', action='store_true')
    services = [commands.add_parser('serve-dev')]
    if hasattr(task.Packet, 'training_feedback'):
        services.append(commands.add_parser('serve-train', help='exact L3 probes on public sentences'))
    for service in services:
        service.add_argument('--exchange', type=Path, required=True)
        service.add_argument('--once', action='store_true')
    query = commands.add_parser('query')
    fixed = commands.add_parser('baselines')
    final = commands.add_parser('grade')
    final.add_argument('--code', type=Path, required=True)
    final.add_argument('--bench', action='store_true')
    for command in (prep, staging, *services, query, fixed, final):
        command.add_argument('--root', type=Path, required=True)
    for command in (staging, *services, query, final):
        command.add_argument('--actor', required=True)
    for command in (query, final):
        command.add_argument('--choice', type=Path, required=True)
    for command in (fixed, final):
        command.add_argument('--out', type=Path)
    args = cli.parse_args()
    if args.cmd == 'prepare':
        if args.batch_size < 1:
            cli.error('batch size must be positive')
        result = task.prepare(args.source, args.model, args.model_dir, args.root, args.batch_size)
    else:
        packet = task.Packet(args.root)
        if args.cmd == 'stage':
            result = stage(task, packet, args.out, args.actor, args.reference_check)
        elif args.cmd in ('serve-dev', 'serve-train'):
            serve_dev(packet, args.actor, args.exchange, args.once, training=args.cmd == 'serve-train')
            return
        elif args.cmd == 'query':
            result = record(packet, args.actor, read_json(args.choice))
        elif args.cmd == 'baselines':
            result = {'model': packet.protocol['model']['id'], 'results': baselines(packet)}
        else:
            result = grade(packet, args.actor, read_json(args.choice), args.code)
        if args.cmd in ('grade', 'baselines') and args.out:
            write_json(args.out, result)
        if args.cmd == 'grade' and args.bench:
            scores = result['results']['agent']['scores']
            if scores[task.METRIC] is None:
                cli.exit(1, 'undefined primary metric on the fixed test set\n')
            scalars = {k: v for k, v in scores.items() if type(v) in (int, float)}
            print('>>>>> BPB_SCORES\n' + json.dumps(scalars, allow_nan=False) + '\n<<<<< BPB_SCORES')
            return
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
