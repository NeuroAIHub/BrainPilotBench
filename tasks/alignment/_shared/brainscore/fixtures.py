"""Tiny offline contract fixtures. Never stand in for Brain-Score reference results."""
from .packet import save_fixture


def create(output, registry, adapter):
    import numpy as np
    choices = {'vision-neural': ('MajajHong2015public.IT-pls', 'pixels'),
               'language-neural': ('Pereira2018.384sentences-ridge', 'distilgpt2'),
               'language-behavior': ('Futrell2018-pearsonr', 'distilgpt2')}
    bid, cid = choices[adapter]
    benchmark = registry['benchmarks'][bid]
    ids = ['presentation-%d' % i for i in range(8)]
    presentations = [{'presentation_id': pid, 'stimulus_id': 'stimulus-%d' % i,
                      'source_coordinates': {'story': 'story-%d' % (i // 2), 'word_position': i % 2 + 1}}
                     for i, pid in enumerate(ids)]
    units = [{'unit_id': 'unit-%d' % i, 'kind': benchmark['measurement_unit'], 'subject_id': 'subject-%d' % i,
              'source_coordinates': {'synthetic': True}} for i in range(2)]
    behavior = adapter == 'language-behavior'
    included = ids[1::2] if behavior else ids
    protocol = {'schema': 'bpb-bs-cache-protocol/1', 'readout': benchmark['readout'],
                'split_group': benchmark['split_group'], 'normalization': benchmark['normalization'],
                'included_presentation_ids': included,
                'excluded_presentations': {pid: 'synthetic sentence-first word' for pid in ids[::2]} if behavior else {},
                'folds': [] if behavior else [{'id': 'fixture-fold-0', 'train_ids': ids[:4], 'test_ids': ids[4:]},
                                             {'id': 'fixture-fold-1', 'train_ids': ids[4:], 'test_ids': ids[:4]}],
                'parameters': {'status': 'synthetic-contract-fixture-not-official-splits'}}
    # Deliberately reverse candidate rows to exercise identity-based alignment.
    candidate = np.arange(8., dtype=np.float32) if behavior else np.arange(24., dtype=np.float32).reshape(8, 3)
    responses = np.arange(16., dtype=np.float32).reshape(8, 2)
    responses[3, 1] = np.nan
    arrays = {'candidate': candidate[::-1].copy(), 'responses': responses, 'response_valid': np.isfinite(responses)}
    if behavior:
        arrays['candidate_valid'] = np.ones(8, dtype=bool)
    metadata = {'presentations': presentations, 'units': units, 'candidate_presentation_ids': ids[::-1], 'protocol': protocol}
    return save_fixture(output, registry, bid, cid, metadata, arrays)
