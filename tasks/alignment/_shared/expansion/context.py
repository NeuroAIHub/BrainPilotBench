"""B: sealed pilot features become an independently runnable analysis task."""
from real_brainscore.common import new_directory, read_json, separate_paths, sha256
from incremental.protocol import make_splits
from . import ExpansionError
from .packet import array, save, verify


def prepare(source, output):
    from context_pilot import CONDITIONS, matched_rows
    source, manifest = verify(source, 'bpb-context-pilot-artifacts/1')
    if manifest.get('synthetic_only') is not False:
        raise ExpansionError('real context pilot required')
    separate_paths(source, output)
    rows = read_json(source / 'contexts.json')
    stimuli = read_json(source / 'stimuli.json')
    if [r['stimulus_id'] for r in rows] != [r['stimulus_id'] for r in stimuli]:
        raise ExpansionError('context identities differ')
    # Check the sealed extraction's target and reversal identities. Complete
    # history ordering was established and tested in context_pilot.context_design.
    for row, stimulus in zip(rows, stimuli):
        parts = row['conditions']
        if (len(row['history_ids']) not in (2, 3) or row['stimulus_id'] in row['history_ids']
                or parts['sentence_only'] != [stimulus['stimulus']]
                or parts['sentence_only'] != parts['normal_prefix'][-1:]
                or parts['reversed_prefix'] != list(reversed(parts['normal_prefix'][:-1])) + parts['normal_prefix'][-1:]):
            raise ExpansionError('invalid past-only context manipulation')
    retained = matched_rows(rows)
    selected = [stimuli[i] for i in retained]
    arrays = {'brain': array(source / 'brain.npy')[retained]}
    arrays.update({name: array(source / ('features-' + name + '.npy'))[retained] for name in CONDITIONS})
    metadata = {'stimuli': selected, 'neuroids': read_json(source / 'neuroids.json'),
                'splits': make_splits(selected), 'contexts': [rows[i] for i in retained],
                'excluded_ids': [r['stimulus_id'] for i, r in enumerate(rows) if i not in retained]}
    return save(new_directory(output), 'B', metadata, arrays,
                {'source_manifest_sha256': sha256(source / 'manifest.json'), 'source': 'verified local Pereira/distilgpt2 context extraction'})


def compute(packet, plan):
    import numpy as np
    from incremental.analysis import nested_predictions, squared_errors, score_errors, paired_interval
    from incremental.protocol import make_splits
    meta, a = packet['metadata'], packet['arrays']
    if meta['splits'] != make_splits(meta['stimuli']):
        raise ExpansionError('context folds differ')
    p = {**meta, 'brain': a['brain'], 'protocol': packet['protocol']}
    names = packet['protocol']['conditions']
    if any(a[n].shape[0] != len(meta['stimuli']) for n in names) or a['brain'].shape != (len(meta['stimuli']), len(meta['neuroids'])):
        raise ExpansionError('context array shape differs')
    predictions, traces = nested_predictions(p, {n: a[n] for n in names})
    baseline, errors = squared_errors(p, predictions)
    subjects = np.asarray([n['subject_id'] for n in meta['neuroids']])
    scores = {n: score_errors(errors[n].sum(axis=0), baseline.sum(axis=0), subjects)[0] for n in names}
    comparisons = {n: {'delta_r2': scores['normal_prefix'] - scores[n],
                       'interval': paired_interval(p, baseline, errors[n], errors['normal_prefix'])}
                   for n in ('sentence_only', 'reversed_prefix')}
    summary = {'scores': scores, 'comparisons': comparisons, 'folds': traces,
               'targets': len(meta['stimuli']), 'excluded_token_mismatches': len(meta['excluded_ids'])}
    conclusion = {'intervals': {n: 'positive' if c['interval'][0] > 0 else 'negative' if c['interval'][1] < 0 else 'includes_zero'
                               for n, c in comparisons.items()},
                  'scope': 'observed_subjects_heldout_story_groups', 'uncertainty': 'conditional_on_fitted_oof_predictions',
                  'human_context_intervention': False, 'long_term_memory_tested': False, 'causality_established': False}
    predictions['stimulus_ids'] = np.asarray([s['stimulus_id'] for s in meta['stimuli']])
    predictions['neuroid_ids'] = np.asarray([s['neuroid_id'] for s in meta['neuroids']])
    return summary, predictions, conclusion
