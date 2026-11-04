"""E: real human schedules with explicit once/replay feedback-only baselines.

The small NumPy network follows the author's linear 12→50→4 architecture,
but uses a separately named deterministic simulation protocol. It does not
claim bitwise reproduction of the author's optimizer/random initialization.
"""
import hashlib

from real_brainscore.common import new_directory, sha256
from . import ExpansionError
from .packet import save

PHASES = ('A1', 'B', 'A2')


def simulate(stimulus, probe, feedback, feedback_present, repeats, seed, learning_rate=0.1):
    import numpy as np
    rng = np.random.default_rng(seed)
    first = rng.normal(0., 0.001, size=(50, 12))
    second = rng.normal(0., 0.001, size=(4, 50))
    result = []
    # State persists across phases. No target/response argument is available here.
    for phase in range(3):
        responses = []
        for _ in range(repeats):
            for i, sid in enumerate(stimulus[phase]):
                part = slice(2 * probe[phase, i], 2 * probe[phase, i] + 2)
                hidden = first[:, sid].copy()
                predicted = second[part] @ hidden
                responses.append(float(np.arctan2(predicted[0], predicted[1])))
                if feedback_present[phase, i]:
                    target = np.asarray([np.sin(feedback[phase, i]), np.cos(feedback[phase, i])])
                    gradient = predicted - target  # MSE over exactly two coordinates.
                    grad_hidden = second[part].T @ gradient
                    second[part] -= learning_rate * np.outer(gradient, hidden)
                    first[:, sid] -= learning_rate * grad_hidden
        result.append(np.asarray(responses)[np.tile(probe[phase] == 1, repeats)])
    return np.stack(result)


def prepare(csv, output):
    import numpy as np
    import pandas as pd
    frame = pd.read_csv(csv)
    frame = frame[frame.task_section.isin(PHASES)].copy()
    selected = []
    # A bounded, deterministic convenience subset, independent of response scores.
    for (study, condition), group in frame.groupby(['study', 'condition'], sort=True):
        selected.extend(sorted(group.participant.unique())[:3])
    ids, conditions, studies, targets, responses, stimuli, probes, feedbacks, masks = [], [], [], [], [], [], [], [], []
    excluded = []
    for participant in selected:
        rows = frame[frame.participant == participant]
        blocks = [rows[rows.task_section == phase].sort_values('index') for phase in PHASES]
        if any(len(b) != 120 or b['index'].duplicated().any() or int((b.feature_idx == 1).sum()) != 60 for b in blocks):
            raise ExpansionError('expected 120 ordered trials and 60 feature-1 probes per phase')
        if any(not np.isfinite(b[['feat_val', 'dial_resp', 'stimID', 'feature_idx']].to_numpy()).all() for b in blocks):
            excluded.append(participant)
            continue
        ids.append(participant)
        conditions.append(str(rows.condition.iloc[0]))
        studies.append(int(rows.study.iloc[0]))
        targets.append(np.stack([b.loc[b.feature_idx == 1, 'feat_val'].to_numpy() for b in blocks]))
        responses.append(np.stack([b.loc[b.feature_idx == 1, 'dial_resp'].to_numpy() for b in blocks]))
        stimuli.append(np.stack([b.stimID.to_numpy(dtype='int64') for b in blocks]))
        probes.append(np.stack([b.feature_idx.to_numpy(dtype='int64') for b in blocks]))
        feedbacks.append(np.stack([b.noisy_feedback_value.fillna(0.).to_numpy() for b in blocks]))
        masks.append(np.stack([b.noisy_feedback_value.notna().to_numpy() for b in blocks]))
    targets, responses, stimuli, probes, feedbacks, masks = map(np.stack, (targets, responses, stimuli, probes, feedbacks, masks))
    if np.any(stimuli < 0) or np.any(stimuli >= 12) or not np.isin(probes, [0, 1]).all():
        raise ExpansionError('invalid stimulus or probe identities')
    arrays = {'targets': targets, 'human_responses': responses, 'stimulus': stimuli,
              'probe': probes, 'feedback': feedbacks, 'feedback_present': masks}
    models = []
    for index, repeats in enumerate((1, 100)):
        simulations = []
        for i, participant in enumerate(ids):
            seed = 2024 + int(hashlib.sha256(participant.encode()).hexdigest()[:8], 16)
            simulations.append(simulate(stimuli[i], probes[i], feedbacks[i], masks[i], repeats, seed))
        arrays['model_%d_responses' % index] = np.stack(simulations)
        models.append({'id': 'linear50_feedback_' + ('once' if repeats == 1 else 'replay100'),
                       'phase_repetitions': repeats, 'state_reset_between_phases': False,
                       'update_without_feedback': False, 'human_feedback_sequence_used': True})
    meta = {'participant_ids': ids, 'conditions': conditions, 'studies': studies, 'phases': list(PHASES),
            'models': models, 'human_phase_repetitions': 1,
            'simulation': {'architecture': [12, 50, 4], 'activation': 'linear', 'bias': False,
                           'init_sd': 0.001, 'learning_rate': 0.1, 'loss': 'MSE of probed sine/cosine coordinates',
                           'order': 'source index, no shuffle; pre-update prediction',
                           'seed': '2024 + first eight SHA256 hex digits of participant ID'},
            'selection': 'first three lexicographic participant IDs per study and mapping condition in the author-processed table',
            'excluded_nonfinite_participants': excluded}
    return save(new_directory(output), 'E', meta, arrays,
                {'source': 'https://github.com/eleanorholton/transfer-interference',
                 'commit': 'dcd451046759ebbbfa2987031a64da8c773e750d', 'csv_sha256': sha256(csv),
                 'simulation': 'derived feedback-only linear-network baseline; not exact author simulation or fitted human parameters',
                 'author_preprocessing': 'uses supplied processed table; no claim of re-running original participant exclusions'})


def circular_error(response, target):
    import numpy as np
    return np.abs((response - target + np.pi) % (2 * np.pi) - np.pi) * (180. / np.pi)


def trajectory_metrics(errors, window):
    import numpy as np
    if errors.ndim != 3 or errors.shape[1] != 3 or errors.shape[2] < window:
        raise ExpansionError('trajectory shape/window invalid')
    early, late = errors[:, :, :window].mean(axis=2), errors[:, :, -window:].mean(axis=2)
    metrics = np.column_stack([early[:, 0] - early[:, 1], early[:, 1] - late[:, 0], early[:, 2] - late[:, 0], early - late])
    curves = np.stack([v.mean(axis=2) for v in np.array_split(errors, 10, axis=2)], axis=2)
    return metrics, curves


def compute(packet, plan):
    import numpy as np
    a, meta, spec = packet['arrays'], packet['metadata'], packet['protocol']
    n = len(meta['participant_ids'])
    if len(set(meta['participant_ids'])) != n or a['targets'].shape != a['human_responses'].shape or a['targets'].shape[:2] != (n, 3):
        raise ExpansionError('human trajectory identity/shape mismatch')
    names = ['human'] + [m['id'] for m in meta['models']]
    metrics, curves = [], []
    m, c = trajectory_metrics(circular_error(a['human_responses'], a['targets']), plan['window'])
    metrics.append(m); curves.append(c)
    exposure = {}
    for index, model in enumerate(meta['models']):
        repeats = model['phase_repetitions']
        target = np.tile(a['targets'], (1, 1, repeats))
        response = a['model_%d_responses' % index]
        if response.shape != target.shape or type(repeats) is not int or repeats < 1:
            raise ExpansionError('model exposure/shape mismatch')
        m, c = trajectory_metrics(circular_error(response, target), plan['window'])
        metrics.append(m); curves.append(c)
        exposure[model['id']] = {'phase_repetitions': repeats,
                                'feedback_updates_per_participant_phase': (a['feedback_present'].sum(axis=2) * repeats).tolist(),
                                'exposure_matched': repeats == meta['human_phase_repetitions'],
                                'state_preserved': not model['state_reset_between_phases'],
                                'feedback_only_updates': not model['update_without_feedback']}
    metrics, curves = np.stack(metrics), np.stack(curves)
    rng = np.random.default_rng(spec['bootstrap_seed'])
    groups = {}
    conditions = np.asarray(meta['conditions'])
    for condition in sorted(set(conditions)):
        selected = np.flatnonzero(conditions == condition)
        samples = rng.choice(selected, size=(spec['bootstrap_replicates'], len(selected)), replace=True)
        differences = metrics[1:] - metrics[:1]
        draws = differences[:, samples, :].mean(axis=2)
        groups[condition] = {'participants': len(selected), 'means': metrics[:, selected].mean(axis=1).tolist(),
                             'model_minus_human': differences[:, selected].mean(axis=1).tolist(),
                             'paired_participant_percentile_intervals': np.percentile(draws, [2.5, 97.5], axis=1).transpose(1, 2, 0).tolist()}
    summary = {'systems': names, 'window': plan['window'], 'participants': n,
               'metrics': ['initial_phase_difference', 'switch_cost', 'interference', 'learning_A1', 'learning_B', 'learning_A2'],
               'groups': groups, 'exposure': exposure}
    conclusion = {'exposure_matched': {k: v['exposure_matched'] for k, v in exposure.items()},
                  'same_brain_mechanism_established': False, 'consolidation_tested': False,
                  'scope': 'observed_paired_participants_and_derived_linear_baselines',
                  'intervals': 'descriptive_paired_participant_bootstrap_no_population_claim'}
    return summary, {'participant_ids': np.asarray(meta['participant_ids']), 'metrics': metrics, 'curves': curves}, conclusion
