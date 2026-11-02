"""Real profile transport validation. Pure stdlib: MCP needs no Torch/Brain-Score."""
import math
import re

from . import BENCHMARK, COMMIT, REAL_PROFILE, BackendError


def validate_real_packet(packet):
    def require(condition, message):
        if not condition:
            raise BackendError(message)
    def ids(values, minimum=1):
        return isinstance(values, list) and minimum <= len(values) <= 10000 and all(isinstance(x, str) and x for x in values) and len(values) == len(set(values))
    require(isinstance(packet, dict) and packet.get('schema') == 'bpb-real-profile-packet/1' and packet.get('synthetic_only') is False,
            'expected real profile packet')
    require(packet.get('protocol_id') == REAL_PROFILE, 'unsupported real profile protocol')
    layers = packet.get('layers')
    require(ids(layers, 2) and len(layers) <= 128, 'invalid real layer list')
    require(packet.get('baseline_layer') == layers[-1], 'baseline must be the final declared layer')
    margin = packet.get('margin')
    require(type(margin) in (int, float) and math.isfinite(margin) and 0 < margin < 1, 'invalid descriptive margin')
    require(packet.get('source_id') == 'development' and packet.get('confirmation_id') == 'confirmation',
            'real server draft requires development and confirmation data')
    datasets = packet.get('datasets')
    require(isinstance(datasets, dict) and set(datasets) == {'development', 'confirmation'}, 'dataset roles differ')
    for dataset in datasets.values():
        require(isinstance(dataset, dict) and dataset.get('metric_id') == 'subject_median_pooled_pearsonr', 'real metric differs')
        require(ids(dataset.get('subjects'), 2) and ids(dataset.get('blocks')) and ids(dataset.get('stimulus_ids'), 3), 'invalid subject/material/stimulus IDs')
        rows = dataset.get('subject_layer_scores')
        require(isinstance(rows, dict) and set(rows) == set(dataset['subjects']), 'subject coverage differs')
        for row in rows.values():
            require(isinstance(row, dict) and set(row) == set(layers), 'layer coverage differs')
            require(all(type(v) in (int, float) and math.isfinite(v) and -1 <= v <= 1 for v in row.values()), 'invalid Pearson score')
    source, target = datasets['development'], datasets['confirmation']
    require(set(source['subjects']) == set(target['subjects']), 'material replication requires the same subjects')
    require(not set(source['blocks']) & set(target['blocks']), 'story groups overlap')
    require(not set(source['stimulus_ids']) & set(target['stimulus_ids']), 'stimuli overlap')
    require(isinstance(packet.get('shift'), dict) and packet['shift'].get('kind') == 'new_material', 'expected declared new material')
    provenance = packet.get('provenance', {})
    require(provenance.get('upstream_commit') == COMMIT and provenance.get('benchmark_source') == BENCHMARK, 'upstream binding differs')
    require(provenance.get('official_benchmark_equivalence') is False and provenance.get('acceptance') == 'server-validation-pending',
            'real profile is an unaccepted derived protocol, not an official benchmark score')
    require(provenance.get('threshold_status') == 'engineering_only_not_scientifically_calibrated', 'threshold scope missing')
    for key in ('cache_sha256', 'split_sha256'):
        require(isinstance(provenance.get(key), str) and re.fullmatch('[0-9a-f]{64}', provenance[key]), 'missing provenance hash')
    return packet


def real_profile(packet, dataset_id):
    dataset = packet['datasets'][dataset_id]
    by_subject = dataset['subject_layer_scores']
    means = {layer: math.fsum(row[layer] for row in by_subject.values()) / len(by_subject) for layer in packet['layers']}
    return {'dataset_id': dataset_id, 'metric_id': dataset['metric_id'], 'layer_means': means,
            'subject_means': by_subject, 'block_means': {},
            'coverage': {'subjects': len(by_subject), 'stimulus_blocks': len(dataset['blocks']),
                         'stimuli': len(dataset['stimulus_ids']), 'score_cells': len(by_subject) * len(packet['layers'])},
            'aggregation': 'pooled held-out Pearson per neuroid; median within subject; equal mean subjects',
            'official_benchmark_equivalence': False}
