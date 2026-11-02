"""Descriptive synthetic profile calculations, not neural inference or significance tests."""
import hashlib
import json
import math
import sys
from pathlib import Path

PROFILE = 'synthetic-profile-descriptive-v2'
TASK_ID = 'alignment-profile-synthetic'
VERSION = '0.2'
ANSWER_SCHEMA = 'bpb-profile-answers/2'
MAX_BYTES = 2_000_000
REAL_PROFILE = 'pereira-subject-material-descriptive-v1'
REAL_TASK_ID = 'alignment-pereira2018-profile'
REAL_VERSION = '0.1-server-draft'


def real_packet_module():
    shared = Path(__file__).resolve().parents[3] / 'alignment' / '_shared'
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    from real_brainscore import profile_packet
    return profile_packet


class ContractError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def unique_keys(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ContractError('duplicate JSON key')
        out[key] = value
    return out


def parse_json(text):
    def reject_constant(value):
        raise ContractError('nonfinite JSON')
    try:
        return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_keys)
    except (ValueError, UnicodeError) as exc:
        raise ContractError('invalid JSON') from exc


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ContractError('expected a bounded regular JSON file')
    return parse_json(path.read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def mean(values):
    return math.fsum(values) / len(values)


def validate_packet(packet):
    if isinstance(packet, dict) and packet.get('schema') == 'bpb-real-profile-packet/1':
        try:
            return real_packet_module().validate_real_packet(packet)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
    if not isinstance(packet, dict) or packet.get('schema') != 'bpb-profile-packet/1' or packet.get('synthetic_only') is not True:
        raise ContractError('only synthetic profile packets are supported')
    if packet.get('protocol_id') != PROFILE:
        raise ContractError('unsupported protocol')
    def ids(values, minimum=2, maximum=64):
        return isinstance(values, list) and minimum <= len(values) <= maximum and all(isinstance(v, str) and v for v in values) and len(set(values)) == len(values)
    layers = packet.get('layers')
    if not ids(layers) or packet.get('baseline_layer') != layers[-1] or not finite(packet.get('margin')) or not 0 < packet['margin'] < 1:
        raise ContractError('invalid layers/baseline/margin')
    datasets = packet.get('datasets')
    source, target = packet.get('source_id'), packet.get('confirmation_id')
    if not isinstance(datasets, dict) or not isinstance(source, str) or not (target is None or isinstance(target, str)):
        raise ContractError('invalid dataset roles')
    if set(datasets) != ({source, target} if target else {source}) or target == source:
        raise ContractError('undeclared/duplicate dataset')
    for dataset in datasets.values():
        if not isinstance(dataset, dict) or dataset.get('metric_id') != 'synthetic_raw_r':
            raise ContractError('incompatible metric')
        subjects, blocks = dataset.get('subjects'), dataset.get('blocks')
        if not ids(subjects) or not ids(blocks):
            raise ContractError('invalid subject/block IDs')
        expected = {(s, b, l) for s in subjects for b in blocks for l in layers}
        rows = dataset.get('rows')
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise ContractError('incomplete profile coverage')
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'subject', 'block', 'layer', 'score'}:
                raise ContractError('invalid score row')
            if not all(isinstance(row[k], str) for k in ('subject', 'block', 'layer')):
                raise ContractError('invalid score coordinates')
            key = (row['subject'], row['block'], row['layer'])
            if key not in expected or key in seen or not finite(row['score']) or not -1 <= row['score'] <= 1:
                raise ContractError('invalid/duplicate profile cell')
            seen.add(key)
    shift = packet.get('shift')
    if not isinstance(shift, dict) or shift.get('kind') not in ('none', 'new_material') or not isinstance(shift.get('description'), str):
        raise ContractError('shift must be declared in metadata')
    if target is None and shift['kind'] != 'none':
        raise ContractError('missing confirmation dataset')
    if target is not None:
        if shift['kind'] != 'new_material':
            raise ContractError('confirmation must declare new material')
        if set(datasets[source]['subjects']) != set(datasets[target]['subjects']):
            raise ContractError('material confirmation requires the same subjects')
        if set(datasets[source]['blocks']) & set(datasets[target]['blocks']):
            raise ContractError('development and confirmation material IDs overlap')
    return packet


def load_packet(path):
    return validate_packet(read_json(path))


def profile(packet, dataset_id):
    if packet.get('schema') == 'bpb-real-profile-packet/1':
        return real_packet_module().real_profile(packet, dataset_id)
    dataset = packet['datasets'][dataset_id]
    layers = packet['layers']
    by_subject = {s: {l: mean([r['score'] for r in dataset['rows'] if r['subject'] == s and r['layer'] == l]) for l in layers} for s in dataset['subjects']}
    by_block = {b: {l: mean([r['score'] for r in dataset['rows'] if r['block'] == b and r['layer'] == l]) for l in layers} for b in dataset['blocks']}
    means = {l: mean([by_subject[s][l] for s in dataset['subjects']]) for l in layers}
    return {'dataset_id': dataset_id, 'metric_id': dataset['metric_id'], 'layer_means': means,
            'subject_means': by_subject, 'block_means': by_block,
            'coverage': {'subjects': len(by_subject), 'stimulus_blocks': len(by_block), 'score_cells': len(dataset['rows'])},
            'aggregation': 'mean blocks within subject, then equal-weight mean subjects'}


def comparison(packet, layer_a, layer_b):
    p = profile(packet, packet['source_id'])
    differences = {s: values[layer_a] - values[layer_b] for s, values in p['subject_means'].items()}
    return {'dataset_id': packet['source_id'], 'layer_a': layer_a, 'layer_b': layer_b,
            'mean_difference': mean(list(differences.values())), 'subject_differences': differences,
            'min_subject_difference': min(differences.values()), 'max_subject_difference': max(differences.values()),
            'inference': 'descriptive_only_no_significance_or_equivalence_test'}


def top_layers(values, margin=0):
    maximum = max(values.values())
    return [layer for layer, value in values.items() if maximum - value <= margin + 1e-12]


def stability(packet, layer):
    """Within-sample subject consistency and removal sensitivity, not held-out-subject CV."""
    p = profile(packet, packet['source_id'])
    groups = p['subject_means']
    highest = {subject: top_layers(values) for subject, values in groups.items()}
    near = {subject: top_layers(values, packet['margin']) for subject, values in groups.items()}
    gaps = {subject: max(values.values()) - values[layer] for subject, values in groups.items()}
    removals = {}
    for omitted in groups:
        values = {candidate: mean([scores[candidate] for subject, scores in groups.items() if subject != omitted])
                  for candidate in packet['layers']}
        removals[omitted] = {'highest_layers': top_layers(values),
                             'near_top_layers': top_layers(values, packet['margin']),
                             'selected_layer_gap_to_best': max(values.values()) - values[layer]}
    return {'dataset_id': packet['source_id'], 'layer': layer,
            'subject_highest_layers': highest, 'subject_near_top': near, 'subject_gap_to_best': gaps,
            'subject_agreement': mean([float(layer in layers) for layers in near.values()]),
            'leave_one_subject_out': removals,
            'scope': ['observed_subjects'], 'independent_sample_size': None}


def transfer(packet, selected):
    target = packet['confirmation_id']
    baseline = packet['baseline_layer']
    source_values = profile(packet, packet['source_id'])['layer_means']
    source_difference = source_values[selected] - source_values[baseline]
    result = {'status': 'not_evaluated', 'selected_layer': selected, 'baseline_layer': baseline,
              'source_dataset_id': packet['source_id'], 'target_dataset_id': target,
              'declared_shift': packet['shift']['kind'], 'source_difference': source_difference,
              'target_score': None, 'target_baseline_score': None, 'target_difference': None,
              'difference_change': None, 'target_gap_to_best': None, 'scope': 'not_evaluated'}
    if target is None:
        return result
    values = profile(packet, target)['layer_means']
    difference = values[selected] - values[baseline]
    return {**result, 'status': 'evaluated', 'target_score': values[selected],
            'target_baseline_score': values[baseline], 'target_difference': difference,
            'difference_change': difference - source_difference,
            'target_gap_to_best': max(values.values()) - values[selected], 'target_layer_means': values,
            'scope': 'same_subjects_new_material'}


def expected_answers(packet, selected):
    """Maintainer fixture policy. It makes no population-level significance claims."""
    p = profile(packet, packet['source_id'])
    values = p['layer_means']
    top, near = top_layers(values), top_layers(values, packet['margin'])
    span = max(values.values()) - min(values.values())
    positions = [packet['layers'].index(l) for l in near]
    shape = 'flat' if span <= packet['margin'] else ('single_peak' if len(near) == 1 else
            'plateau' if max(positions) - min(positions) + 1 == len(positions) else 'multiple_high_regions')
    c = comparison(packet, top[0], packet['baseline_layer'])
    differences = list(c['subject_differences'].values())
    evidence = ('consistent_advantage' if min(differences) > packet['margin'] else
                'mixed' if min(differences) < -packet['margin'] and max(differences) > packet['margin'] else
                'no_consistent_advantage')
    st = stability(packet, top[0])
    t = transfer(packet, selected)
    influential = [subject for subject, removal in st['leave_one_subject_out'].items()
                   if removal['selected_layer_gap_to_best'] > packet['margin'] + 1e-12]
    advantage = ('not_evaluated' if t['status'] == 'not_evaluated' else
                 'no_development_advantage' if t['source_difference'] <= packet['margin'] + 1e-12 else
                 'advantage_retained' if t['target_difference'] > packet['margin'] + 1e-12 else
                 'advantage_reversed' if t['target_difference'] < -packet['margin'] - 1e-12 else
                 'advantage_not_retained')
    return {
        'q1': {'dataset_id': packet['source_id'], 'layer_means': values, 'highest_layers': top,
               'near_top_layers': near, 'range': span, 'shape': shape},
        'q2': {'dataset_id': packet['source_id'], 'compared_layer': top[0], 'baseline_layer': packet['baseline_layer'],
               'mean_difference': c['mean_difference'], 'subject_differences': c['subject_differences'],
               'evidence_state': evidence, 'claim_strength': 'descriptive_only'},
        'q3': {'dataset_id': packet['source_id'], 'compared_layer': top[0],
               'subject_highest_layers': st['subject_highest_layers'], 'subject_near_top': st['subject_near_top'],
               'subject_gap_to_best': st['subject_gap_to_best'], 'subject_agreement': st['subject_agreement'],
               'leave_one_subject_out': st['leave_one_subject_out'],
               'representativeness': 'broadly_representative' if st['subject_agreement'] >= .75 else 'heterogeneous',
               'influential_subjects': influential, 'leave_one_out_sensitive': bool(influential),
               'scope': st['scope']},
        'q4': {k: v for k, v in t.items() if k != 'target_layer_means'} | {
            'advantage_conclusion': advantage,
            'near_optimality': 'not_evaluated' if t['status'] == 'not_evaluated' else
            'retained_near_optimal' if t['target_gap_to_best'] <= packet['margin'] + 1e-12 else 'not_retained'}
    }
