"""Locally generated score tables, not biological data or model measurements."""
import argparse
import random
from pathlib import Path
from core import PROFILE, validate_packet, write_json

SCENARIOS = ('peak', 'plateau', 'heterogeneous', 'subject_driven', 'transfer_change',
             'advantage_lost', 'advantage_reversed', 'no_confirmation', 'flat')


def generate(seed=1729, scenario='peak'):
    if scenario not in SCENARIOS:
        raise ValueError('unknown fixture scenario')
    rng = random.Random(seed)
    layers = [f'block-{i}' for i in range(6)]
    subjects = [f'sub-{i}' for i in range(4)]
    blocks = [f'passage-{i}' for i in range(4)]
    normal = [.10, .18, .32, .50, .30, .15]
    base = [.10, .20, .40, .405, .40, .12] if scenario == 'plateau' else [.10] * 6 if scenario == 'flat' else normal
    datasets = {}
    target = None if scenario == 'no_confirmation' else 'confirmation'
    for role in ['development'] + ([target] if target else []):
        rows = []
        role_blocks = blocks if role == 'development' else [f'confirmation-{b}' for b in blocks]
        for si, subject in enumerate(subjects):
            means = base
            if scenario == 'heterogeneous':
                means = [.15, .60, .20, .18, .10, .20] if si < 2 else [.15, .10, .20, .18, .60, .20]
            if scenario == 'subject_driven':
                means = [.10, .95, .15, .10, .10, .10] if si == 0 else [.10, .20, .15, .40, .10, .10]
            if role == target and scenario == 'transfer_change':
                means = [.15, .55, .25, .30, .25, .20]
            if role == target and scenario == 'advantage_lost':
                means = [.10, .12, .15, .30, .20, .295]
            if role == target and scenario == 'advantage_reversed':
                means = [.10, .12, .15, .20, .18, .40]
            for block in role_blocks:
                for li, layer in enumerate(layers):
                    rows.append({'subject': subject, 'block': block, 'layer': layer,
                                 'score': round(means[li] + rng.randint(-3, 3) / 1000, 6)})
        rng.shuffle(rows)
        datasets[role] = {'metric_id': 'synthetic_raw_r', 'subjects': subjects, 'blocks': role_blocks, 'rows': rows}
    packet = {'schema': 'bpb-profile-packet/1', 'synthetic_only': True, 'protocol_id': PROFILE,
              'packet_id': f'fixture-{seed}', 'layers': layers, 'baseline_layer': layers[-1], 'margin': .02,
              'source_id': 'development', 'confirmation_id': target,
              'shift': {'kind': 'new_material' if target else 'none',
                        'description': 'Same synthetic subjects and measurement setup; disjoint material blocks. Not real OOD evidence.' if target else 'No confirmation data supplied.'},
              'datasets': datasets}
    return validate_packet(packet)


def public_context(packet):
    return {k: packet[k] for k in ('schema', 'synthetic_only', 'protocol_id', 'packet_id', 'layers', 'baseline_layer', 'margin', 'source_id', 'confirmation_id', 'shift')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=1729)
    parser.add_argument('--scenario', choices=SCENARIOS, default='peak')
    parser.add_argument('--public-only', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('refusing to overwrite fixture output')
    packet = generate(args.seed, args.scenario)
    write_json(args.output, public_context(packet) if args.public_only else packet)


if __name__ == '__main__':
    main()
