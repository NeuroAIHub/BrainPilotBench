"""Audited protocols for the nine pinned official benchmark registrations."""
import hashlib
import json

from .registry import require


def specification(benchmark_id):
    family = benchmark_id.split('.')[0].split('-')[0].replace('public', '')
    vision = family in ('MajajHong2015', 'FreemanZiemba2013')
    behavior = family == 'Futrell2018'
    region = benchmark_id.split('.')[1].split('-')[0] if vision else 'language_system'
    group = {'Pereira2018': 'story', 'Fedorenko2016': 'sentence_id', 'Blank2014': 'story'}.get(family)
    require(family in ('MajajHong2015', 'FreemanZiemba2013', 'Pereira2018', 'Fedorenko2016', 'Blank2014', 'Futrell2018'), 'unsupported official family')
    cv = ({'stratification_coord': 'object_name' if family == 'MajajHong2015' else 'texture_type'} if vision else
          {} if behavior else {'split_coord': group, 'kfold': 'group', 'random_state': 1234,
                               **({'splits': 8} if family == 'Blank2014' else {})})
    return {
        'schema': 'bpb-bs-official-protocol/1', 'benchmark_id': benchmark_id,
        'benchmark_identifier': f'{family}.{region}.public-pls' if vision else benchmark_id,
        'benchmark_version': {'MajajHong2015': 4, 'FreemanZiemba2013': 1, 'Fedorenko2016': 3}.get(family, 1),
        'family': family, 'ecosystem': 'vision' if vision else 'language',
        'metric': 'pls' if vision else 'pearsonr' if behavior else 'ridge_pearsonr',
        'readout': 'pls' if vision else 'none' if behavior else 'ridge',
        'crossvalidation_kwargs': cv, 'split_group': group,
        'splits': 0 if behavior else 8 if family == 'Blank2014' else 10,
        'normalization': 'vision-explained-variance' if vision else 'language-ceiling',
        'aggregation': 'absolute Pearson versus subject-mean reading times' if behavior else 'median neuroids within each split, then mean splits',
        'behavior_raw': 'absolute_r_with_signed_rvalue_retained' if behavior else None,
        'context_group': {'Pereira2018': 'passage_label', 'Fedorenko2016': 'sentence_id', 'Blank2014': 'story'}.get(family),
        'recording_type': None if vision or behavior else 'ECoG' if family == 'Fedorenko2016' else 'fMRI',
        'region': region, 'visual_degrees': (8 if family == 'MajajHong2015' else 4) if vision else None,
        'number_of_trials': (50 if family == 'MajajHong2015' else 20) if vision else None,
        'behavior_context': 'one digest_text call over all words in source order' if behavior else None,
        'solver': {'class': 'PLSRegression', 'n_components': 25, 'scale': False} if vision else
                  None if behavior else {'class': 'RidgeGCVTorch', 'alphas': [.001, .01, .1, 1., 10., 100., 1000.]},
    }


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
