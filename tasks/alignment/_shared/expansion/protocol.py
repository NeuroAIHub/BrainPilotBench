"""Frozen scientific contracts. A protocol change requires a new identifier."""
from incremental.protocol import specification as ridge_specification
from . import TASKS, ExpansionError


def specification(task):
    ridge = {key: value for key, value in ridge_specification().items()
             if key not in ('control_sets', 'word_count', 'position', 'increment')}
    common = {'protocol_id': TASKS[task][1], 'acceptance': 'experimental-scientific-review-pending',
              'official_benchmark_equivalence': False,
              'prose_quality_graded': False, 'analysis_dtype': 'float64'}
    details = {
        'B': {**ridge,
              'conditions': ['sentence_only', 'normal_prefix', 'reversed_prefix'],
              'contrasts': 'normal_prefix R2 minus sentence_only R2; normal_prefix R2 minus reversed_prefix R2',
              'selection': 'positions 3/4; equal normal/reversed tokenizer counts; common targets; no future text',
              'interpretation': 'model-only short-history intervention; human responses unchanged; no causal brain or long-memory claim'},
        'C': {'neural_metric': 'mean-subject Spearman RSA of correlation-distance RDMs; within each concept-disjoint partition',
              'behavior_metric': 'mean negative log likelihood of chosen similar pair in held-out triplets',
              'temperature_grid': [0.01, 0.1, 1., 10., 100.],
              'behavior_readout': 'softmax(-cosine_distance/temperature); temperature fit on training triplets only; smallest tie',
              'split_seed': 41, 'partitions': ['train', 'discovery', 'confirmation'],
              'inference': 'paired concept-delete-one jackknife; descriptive standard error; no independent-pair assumption',
              'interpretation': 'fixed candidates, observed cohorts; concept-matched exemplar proxy; no within-person brain-behavior correlation'},
        'D': {'metric': 'mean-subject Spearman RSA against fixed candidate RDMs at every supplied time',
              'partitions': ['discovery', 'confirmation'], 'split_seed': 41,
              'window_width_ms': 50., 'window_start_grid_ms': [0., 50., 100., 150., 200., 250., 300.],
              'selection': 'maximize discovery signed candidate difference averaged over window, earliest tie; confirmation never selects window',
              'permutations': 499, 'permutation_seed': 73,
              'multiplicity': 'confirmation stimulus-label permutation, max absolute RSA over all candidates and times; plus selected-window difference permutation',
              'interpretation': 'stimulus-label correspondence in observed subjects; static model layers are not time; no exact onset or shared-mechanism claim'},
        'E': {'windows': [20, 40], 'error': 'absolute circular error in degrees, wrapped to [-180,180)',
              'trials': 'all finite feature-1 responses, including no-feedback probes; feedback availability controls learning, not response inclusion',
              'transfer': 'mean error first W feature-1 trials of A1 minus first W feature-1 trials of B; descriptive initial-phase difference',
              'switch_cost': 'mean error first W feature-1 trials of B minus last W feature-1 trials of A1',
              'interference': 'mean error first W feature-1 trials of A2 minus last W feature-1 trials of A1',
              'learning': 'first W minus last W feature-1 errors within each phase; windows may overlap and are not independent samples',
              'curve_bins': 10, 'aggregation': 'trials within participant/phase; equal paired participants within mapping condition',
              'bootstrap_replicates': 1000, 'bootstrap_seed': 73,
              'interpretation': 'descriptive human-model trajectory agreement; exposure audit mandatory; no neural mechanism or consolidation inference'},
        'F': {'selection_per_group': 10, 'allowed_submissions': 1,
              'prediction': 'one finite predicted response per candidate; selected groups need not equal a reference ranking',
              'metric': 'equal-mean held-out-subject (mean drive minus mean suppress), using supplied author-normalized response units',
              'constraints': '10 unique IDs per group, disjoint groups, common measured pool; identical per-group length-bin counts',
              'length_bins_words': [0, 10, 15, 20, 1000000],
              'random_baseline_replicates': 1000, 'random_seed': 73,
              'fixed_predictor': 'train-only standardized ridge alpha=100; equal mean training subjects; balanced top/bottom within length bins',
              'interpretation': 'offline selection from publicly measured sentences; no new human experiment; public-label contamination possible'},
    }
    return {**details[task], **common}


def default_plan(task):
    plan = {'protocol_id': TASKS[task][1], 'rationale': 'Implement the declared comparison and audit its interpretation.'}
    if task == 'E':
        plan['window'] = 20
    if task in ('C', 'D'):
        plan['candidate_pair'] = [0, 1]
    return plan


def validate_plan(task, plan, candidates=None):
    expected = set(default_plan(task))
    if (not isinstance(plan, dict) or set(plan) != expected or plan.get('protocol_id') != TASKS[task][1]
            or not isinstance(plan.get('rationale'), str) or not 0 < len(plan['rationale'].strip()) <= 4000):
        raise ExpansionError('invalid analysis plan')
    if task == 'E' and (type(plan['window']) is not int or plan['window'] not in specification(task)['windows']):
        raise ExpansionError('window must be 20 or 40')
    if task in ('C', 'D'):
        pair = plan['candidate_pair']
        if (not isinstance(pair, list) or len(pair) != 2 or any(type(i) is not int or i < 0 for i in pair)
                or pair[0] == pair[1] or (candidates is not None and max(pair) >= candidates)):
            raise ExpansionError('candidate_pair must identify two distinct supplied candidates')
    return plan
