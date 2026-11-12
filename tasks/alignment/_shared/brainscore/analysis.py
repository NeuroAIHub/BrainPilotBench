"""T1 official reproduction and T2 paired descriptive analysis on local caches."""
from pathlib import Path

from real_brainscore.common import new_directory, separate_paths, write_json
from .bundle import load
from .official import compute
from .protocols import specification
from .registry import require
from .runtime import check, offline


def signed_correlation(x, y):
    import numpy as np
    keep = np.isfinite(x) & np.isfinite(y)
    if keep.sum() < 3 or np.std(x[keep]) == 0 or np.std(y[keep]) == 0:
        return None, int(keep.sum())
    return float(np.corrcoef(x[keep], y[keep])[0, 1]), int(keep.sum())


def column_correlations(predictions, targets):
    """Vectorized finite-pair Pearson for large voxel tables; undefined stays null."""
    import numpy as np
    valid = np.isfinite(predictions) & np.isfinite(targets)
    count = valid.sum(axis=0)
    first = np.where(valid, predictions, 0.)
    second = np.where(valid, targets, 0.)
    first = np.where(valid, first - first.sum(axis=0) / np.maximum(count, 1), 0.)
    second = np.where(valid, second - second.sum(axis=0) / np.maximum(count, 1), 0.)
    denominator = np.sqrt(np.sum(first ** 2, axis=0) * np.sum(second ** 2, axis=0))
    defined = (count >= 3) & (denominator > 0)
    values = np.divide(np.sum(first * second, axis=0), denominator, out=np.zeros_like(denominator), where=defined)
    return [float(np.clip(value, -1., 1.)) if keep else None for value, keep in zip(values, defined)]


def decomposition(packet, records):
    """Additional descriptive summaries; these never replace official aggregation."""
    import numpy as np
    aligned, meta = packet['aligned'], packet['metadata']
    if not records:
        keep = np.asarray([r['source_coordinates']['word_within_sentence_id'] != 1 for r in meta['presentations']])
        candidate, targets = aligned['candidate'], aligned['responses']
        subjects = []
        for index, unit in enumerate(meta['units']):
            value, count = signed_correlation(candidate[keep], targets[keep, index])
            subjects.append({'subject_id': unit['subject_id'], 'signed_r': value, 'valid_words': count})
        stories = []
        names = [r['source_coordinates'].get('story_id', r['source_coordinates'].get('story')) for r in meta['presentations']]
        for name in sorted({str(v) for v in names if v is not None}):
            rows = keep & np.asarray([str(v) == name for v in names])
            value, count = signed_correlation(candidate[rows], np.nanmean(targets[rows], axis=1))
            stories.append({'story': name, 'signed_r_vs_subject_mean': value, 'valid_words': count})
        return {'definition': 'signed Pearson on finite pairs after official first-word exclusion; descriptive only',
                'subjects': subjects, 'stories': stories}
    unit_positions = {value: i for i, value in enumerate(aligned['unit_ids'])}
    subject_of = {u['unit_id']: u['subject_id'] for u in meta['units']}
    subjects = []
    for subject in sorted({v for v in subject_of.values() if v is not None}):
        values = []
        for record in records:
            scores = [record['unit_scores'][j] for j, uid in enumerate(record['unit_ids']) if subject_of[uid] == subject]
            finite = [score for score in scores if np.isfinite(score)]
            if finite:
                values.append(float(np.median(finite)))
        subjects.append({'subject_id': subject, 'mean_fold_median_r': float(np.mean(values)) if values else None,
                         'fold_count': len(values)})
    row_positions = {value: i for i, value in enumerate(aligned['presentation_ids'])}
    stimuli = []
    for coordinate in ('story', 'texture_type', 'object_name'):
        if not all(coordinate in row['source_coordinates'] for row in meta['presentations']):
            continue
        labels = {str(row['source_coordinates'][coordinate]) for row in meta['presentations']}
        for label in sorted(labels):
            predictions, targets = [], []
            for record in records:
                for j, pid in enumerate(record['test_ids']):
                    index = row_positions[pid]
                    if str(meta['presentations'][index]['source_coordinates'][coordinate]) == label:
                        columns = [unit_positions[uid] for uid in record['unit_ids']]
                        predictions.append(record['prediction'][j])
                        targets.append(aligned['responses'][index, columns])
            per_unit = []
            if predictions:
                a, b = np.asarray(predictions), np.asarray(targets)
                per_unit = column_correlations(a, b)
            finite = [value for value in per_unit if value is not None]
            stimuli.append({'coordinate': coordinate, 'value': label, 'test_occurrences': len(predictions),
                            'valid_units': len(finite), 'median_signed_r': float(np.median(finite)) if finite else None})
    return {'definition': 'subject: median finite units per fold then mean defined folds; stimulus groups: pooled test-occurrence signed Pearson then median defined units',
            'repeated_test_occurrences_are_not_independent': True, 'subjects': subjects, 'stimulus_groups': stimuli}


def run(inputs, output, registry):
    import numpy as np
    bundle = load(inputs, registry)
    separate_paths(inputs, output)
    root = new_directory(output, allow_empty=True)
    (root / 'results').mkdir()
    instance = bundle['instance']
    ecosystem = registry['families'][instance['family_id']]['ecosystem']
    with offline():
        runtime = check(ecosystem, registry['root'])
        cases, traces = [], []
        for index, packet in enumerate(bundle['packets']):
            score, records = compute(packet)
            case = {'id': 'case-%02d' % index, 'benchmark_id': packet['manifest']['benchmark_id'],
                    'candidate_id': packet['manifest']['candidate_id'], 'score': score,
                    'cache_manifest_sha256': packet['manifest_sha256'], 'decomposition': decomposition(packet, records)}
            cases.append(case)
            trace = {'case_id': case['id'], 'kind': 'neural' if records else 'behavior', 'folds': []}
            for record in records:
                prefix = case['id'] + '-' + record['id']
                prediction_file, score_file = prefix + '-predictions.npy', prefix + '-unit-scores.npy'
                np.save(root / 'results' / prediction_file, record['prediction'], allow_pickle=False)
                np.save(root / 'results' / score_file, record['unit_scores'], allow_pickle=False)
                trace['folds'].append({key: value for key, value in record.items() if key not in ('prediction', 'unit_scores')} |
                                      {'predictions_file': prediction_file, 'unit_scores_file': score_file})
            if not records:
                aligned = packet['aligned']
                trace.update(presentation_ids=aligned['presentation_ids'], unit_ids=aligned['unit_ids'])
                keep = np.asarray([r['source_coordinates']['word_within_sentence_id'] != 1 for r in packet['metadata']['presentations']])
                for name, values in {'reading_times': aligned['candidate'], 'response_valid': aligned['response_valid'], 'included': keep}.items():
                    filename = case['id'] + '-' + name + '.npy'
                    np.save(root / 'results' / filename, values, allow_pickle=False)
                    trace[name + '_file'] = filename
            traces.append(trace)
    comparisons = []
    if instance['template'] == 't2-compare':
        for bid in instance['benchmark_ids']:
            first, second = [next(case for case in cases if case['benchmark_id'] == bid and case['candidate_id'] == cid)
                             for cid in instance['candidate_ids']]
            delta = second['score']['normalized'] - first['score']['normalized']
            comparisons.append({'benchmark_id': bid, 'first': first['candidate_id'], 'second': second['candidate_id'],
                                'second_minus_first_normalized': delta,
                                'ranking': 'numerical_tie' if abs(delta) <= 1e-6 else second['candidate_id'] if delta > 0 else first['candidate_id'],
                                'scope': 'descriptive_within_supplied_stimuli_and_units'})
    summary = {'schema': 'bpb-bs-analysis/1', 'instance_id': instance['id'], 'template': instance['template'],
               'input_manifest_sha256': bundle['manifest_sha256'], 'synthetic_only': bundle['manifest']['synthetic_only'],
               'cases': cases, 'comparisons': comparisons, 'official_equivalence': 'requires-live-reference-evidence'}
    conclusion = {'schema': 'bpb-bs-conclusion/1', 'instance_id': instance['id'], 'template': instance['template'],
                  'scope': 'supplied_stimuli_and_measurement_units', 'causal_effect_established': False,
                  'new_subject_generalization_tested': False, 'cv_folds_are_independent_samples': False,
                  'rankings': comparisons, 'model_quality_is_analysis_success': False}
    write_json(root / 'results/summary.json', summary)
    write_json(root / 'results/trace.json', traces)
    write_json(root / 'conclusion.json', conclusion)
    write_json(root / 'runtime.json', runtime)
    (root / 'report.md').write_text('# Brain-Score analysis\n\nOfficial pinned metrics on supplied cached outputs. '
                                  'Additional subject/material summaries are descriptive. '
                                  'Synthetic inputs do not establish real-data equivalence or Agent acceptance.\n')
    return summary
