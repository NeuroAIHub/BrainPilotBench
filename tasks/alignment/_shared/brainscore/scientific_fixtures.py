"""Seeded small arrays run through actual upstream metrics, never real data substitutes."""
from pathlib import Path

from .adapters import align_rows
from .bundle import create as create_bundle
from .official import split_manifest
from .packet import save_fixture
from .protocols import specification
from .registry import require
from .runtime import offline, check
from real_brainscore.common import new_directory


def packet(output, registry, benchmark_id, candidate_id):
    import numpy as np
    spec = specification(benchmark_id)
    benchmark = registry['benchmarks'][benchmark_id]
    require(candidate_id in registry['families'][benchmark['family_id']]['candidate_ids'], 'unregistered candidate')
    rng = np.random.default_rng(31)
    n, k, u = 120, 32, 6
    latent = rng.normal(size=(n, k))
    targets = latent @ rng.normal(size=(k, u)) + rng.normal(size=(n, u)) * .3
    noisier = candidate_id in ('alexnet', 'gpt2-small')
    features = latent + rng.normal(size=latent.shape) * (.4 if noisier else .02)
    behavior = spec['readout'] == 'none'
    if behavior:
        features = 20 + latent[:, 0] + rng.normal(size=n) * (.4 if noisier else .02)
        targets = 200 + 10 * latent[:, :1] + rng.normal(size=(n, u))
        targets[7, 2] = np.nan
    ids = ['presentation-%03d' % i for i in range(n)]
    rows = []
    for i, pid in enumerate(ids):
        rows.append({'presentation_id': pid, 'stimulus_id': 'stimulus-%03d' % i,
                     'source_coordinates': {'stimulus': 'synthetic word %d' % i,
                         'story': 'story-%02d' % (i // 10), 'sentence_id': i // 5,
                         'passage_label': 'passage-%02d' % (i // 5), 'passage_index': i % 5,
                         'word': 'word%d' % i, 'word_within_sentence_id': i % 5 + 1,
                         'object_name': 'object-%d' % (i % 3), 'texture_type': 'texture' if i % 2 else 'noise'}})
    units = [{'unit_id': 'unit-%d' % i, 'kind': benchmark['measurement_unit'], 'subject_id': 'subject-%d' % (i if behavior else i // 2),
              'source_coordinates': {'region': spec['region']}} for i in range(u)]
    included = [pid for i, pid in enumerate(ids) if not behavior or i % 5 != 0]
    layer = None if behavior else registry['candidates'][candidate_id]['layer_mapping'][spec['region']]
    metadata = {'presentations': rows, 'units': units, 'candidate_presentation_ids': ids[::-1],
                'candidate_configuration': {'candidate_id': candidate_id, 'layer': None if behavior else layer,
                                            'synthetic_features': True},
                'protocol': {'schema': 'bpb-bs-cache-protocol/1', 'readout': spec['readout'], 'split_group': spec['split_group'],
                             'normalization': spec['normalization'], 'included_presentation_ids': included,
                             'excluded_presentations': {pid: 'official sentence-first word rule on synthetic coordinates' for pid in ids if pid not in included},
                             'folds': [], 'ceiling': .8, 'official_specification': spec}}
    arrays = {'candidate': features[::-1].copy(), 'responses': targets, 'response_valid': np.isfinite(targets)}
    if behavior:
        arrays['candidate_valid'] = np.isfinite(arrays['candidate'])
    provisional = {'manifest': {'benchmark_id': benchmark_id}, 'metadata': metadata,
                   'aligned': {'presentation_ids': ids, 'unit_ids': [r['unit_id'] for r in units],
                               'candidate': features, 'responses': targets, 'response_valid': arrays['response_valid']}}
    metadata['protocol']['folds'] = split_manifest(provisional)
    return save_fixture(output, registry, benchmark_id, candidate_id, metadata, arrays)


def create(output, registry, instance_id):
    require(instance_id in registry['instances'], 'unknown instance')
    instance = registry['instances'][instance_id]
    root = new_directory(output)
    with offline():
        check(registry['families'][instance['family_id']]['ecosystem'], registry['root'])
        paths = []
        for bid in instance['benchmark_ids']:
            for cid in instance['candidate_ids']:
                value = packet(root / ('packet-%02d' % len(paths)), registry, bid, cid)
                paths.append(value['root'])
        bundle = create_bundle(paths, root / 'inputs', instance_id, registry)
    return {'inputs': str(bundle['root']), 'instance_id': instance_id, 'synthetic_only': True}
