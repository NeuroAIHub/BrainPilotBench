"""Public, versioned analysis choices and deterministic story-group folds."""
from . import PROTOCOL, IncrementalError

CONTROL_SETS = ('word_count', 'position', 'word_count+position')
MODELS = ('control', 'model', 'joint')


def specification():
    return {
        'protocol_id': PROTOCOL,
        'outer_folds': 5, 'inner_folds': 3, 'split_seed': 41,
        'alphas': [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0, 1000000.0],
        'bootstrap_seed': 73, 'bootstrap_replicates': 1000,
        'bootstrap_percentiles': [2.5, 97.5],
        'control_sets': list(CONTROL_SETS),
        'word_count': 'len(stimulus.split()); whitespace-delimited words, not model tokens or measured speech rate',
        'position': 'one-hot 1..4 sentence order in each passage, established from original stimulus_num',
        'response_qc': 'owner excludes exactly constant response columns across the supplied dataset before fitting; records all excluded IDs; no prediction-based filtering',
        'preprocessing': 'feature mean and population SD fitted on each training partition; zero SD replaced by 1; intercept unpenalized',
        'alpha_selection': 'shared alpha per readout; maximize pooled inner OOF R2 with each inner training mean as baseline; equal subjects, equal neuroids within subject; smallest alpha wins exact ties',
        'metric': 'R2=1-sum(OOF squared errors)/sum((Y_test-outer_train_mean)**2), per neuroid; mean neuroids within subject, then equal mean subjects',
        'increment': 'joint R2 minus control R2; no clipping or ceiling normalization',
        'uncertainty': 'paired story-block percentile bootstrap of fixed OOF errors and baselines; descriptive, conditional on fitted predictions; does not include refitting uncertainty',
        'inference_scope': 'observed_subjects_heldout_story_groups',
        'official_benchmark_equivalence': False,
        'acceptance': 'experimental-scientific-review-pending',
    }


def validate_plan(plan):
    if (not isinstance(plan, dict) or set(plan) != {'protocol_id', 'control_set', 'rationale'}
            or plan['protocol_id'] != PROTOCOL or plan['control_set'] not in CONTROL_SETS
            or not isinstance(plan['rationale'], str) or not plan['rationale'].strip()
            or len(plan['rationale']) > 4000):
        raise IncrementalError('plan requires protocol_id, an allowed control_set and a nonempty rationale (<=4000 characters)')
    return plan


def group_folds(groups, count, seed):
    import numpy as np
    groups = np.asarray(groups, dtype=str)
    names = np.asarray(sorted(set(groups)))
    if len(names) < count or count < 2:
        raise IncrementalError('not enough distinct story groups for folds')
    names = np.random.default_rng(seed).permutation(names)
    result = []
    for part in np.array_split(names, count):
        test = np.flatnonzero(np.isin(groups, part))
        train = np.flatnonzero(~np.isin(groups, part))
        result.append((train, test))
    return result


def make_splits(stimuli):
    import numpy as np
    spec = specification()
    ids = np.asarray([s['stimulus_id'] for s in stimuli])
    groups = np.asarray([s['story'] for s in stimuli])
    result = []
    for number, (train, test) in enumerate(group_folds(groups, spec['outer_folds'], spec['split_seed'])):
        inner = [{'train_ids': ids[train[a]].tolist(), 'test_ids': ids[train[b]].tolist()}
                 for a, b in group_folds(groups[train], spec['inner_folds'], spec['split_seed'] + number + 1)]
        result.append({'fold_id': 'fold-%d' % number, 'train_ids': ids[train].tolist(),
                       'test_ids': ids[test].tolist(), 'inner': inner})
    return result


def expected_conclusion(summary):
    low, high = summary['increment']['descriptive_interval']
    direction = 'positive_interval' if low > 0 else 'negative_interval' if high < 0 else 'interval_includes_zero'
    return {
        'protocol_id': PROTOCOL, 'control_set': summary['control_set'],
        'interval_result': direction, 'scope': 'observed_subjects_heldout_story_groups',
        'uncertainty': 'conditional_on_fitted_oof_predictions',
        'causal_effect_established': False, 'all_confounders_ruled_out': False,
        'new_subject_generalization_tested': False, 'equivalence_established': False,
    }
