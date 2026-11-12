"""Reviewable task drafts; no runnable task.yaml until real acceptance exists."""
from real_brainscore.common import new_directory, separate_paths, write_json
from ..registry import blockers, require


def contract(registry, instance):
    behavior = all(registry['benchmarks'][bid]['adapter'] == 'language-behavior' for bid in instance['benchmark_ids'])
    t1 = instance['template'] == 't1-reproduce'
    return {
        'schema': 'bpb-bs-task-contract-draft/1', 'task_id': instance['id'], 'template': instance['template'],
        'protocol_id': 'bpb-bs-t1-reproduce-draft/1' if t1 else 'bpb-bs-t2-descriptive-draft/1',
        'entrypoint': 'python submission/analyze.py --inputs DIR --output DIR',
        'category': 'alignment-analysis', 'metric': 'analysis_success',
        'candidate_ids': instance['candidate_ids'], 'benchmark_ids': instance['benchmark_ids'],
        'outputs': ['submission/analyze.py', 'results/summary.json', 'results/trace.json',
                    'results/*.npy', 'conclusion.json', 'report.md'],
        'required_trace': (['word_ids', 'subject_ids', 'model_reading_times', 'valid_response_mask', 'inclusion_mask', 'subject_metrics']
                           if behavior else ['fold_ids', 'train_ids', 'test_ids', 'unit_ids', 'predictions', 'unit_metrics']),
        'required_score_fields': ['raw', 'ceiling', 'normalized', 'unclipped', 'normalization', 'aggregation'],
        'comparison': None if t1 else {'paired_candidates': True, 'same_stimuli_and_protocol': True,
                      'keep_each_endpoint': True, 'scope': 'descriptive', 'cv_folds_are_independent_samples': False},
        'reference_visibility': 'owner-only; do not copy into agent workspace',
        'validation': {'saved_outputs_and_isolated_rerun': True, 'functional_controls': True,
                       'numerical_tolerance': {'atol': 1e-6, 'rtol': 1e-5, 'status': 'provisional'},
                       'limits': {'cpus': 2, 'memory': '8g', 'timeout_seconds': 900, 'output_bytes': 536870912},
                       'free_text_quality': 'human-review-pending'},
        'state': 'draft-not-runnable', 'blockers': blockers(registry, instance),
    }


def render_prompt(value):
    task = ('Reproduce the frozen official analysis for the specified candidate.' if value['template'] == 't1-reproduce'
            else 'Compare the fixed candidates using paired stimuli and the same protocol. Keep each endpoint separate. '
                 'Report descriptive differences and coverage; do not treat cross-validation folds as independent samples.')
    trace = ', '.join(value['required_trace'])
    return ('# Task draft: ' + value['task_id'] + '\n\n'
            '**Not runnable: real inputs, official equivalence, tolerances and resource limits are pending.**\n\n'
            + task + '\n\nBenchmark(s): ' + ', '.join(value['benchmark_ids']) + '.\n\n'
            'Candidate(s): ' + ', '.join(value['candidate_ids']) + '.\n\n'
            'Use the supplied local inputs and frozen protocol. Align by explicit presentation and measurement identities; '
            'preserve missing-response masks, source exclusions and stimulus context. Do not download data or model weights.\n\n'
            'Implement `' + value['entrypoint'] + '`. Submit the source, numerical outputs, structured conclusion and report. '
            'The numerical trace must contain: ' + trace + '. Preserve raw scores, ceiling, normalization and aggregation. '
            'Reading-time behavior uses the model output directly with no extra fitted readout.\n\n'
            'A correct negative or inconclusive scientific result can receive full analysis_success. '
            'This is a public-data analysis task: the scientific test-fold responses are visible. '
            'The trusted evaluator must rerun the program and check saved outputs; stdout is not a score.\n')


def draft(registry, output, phase=None):
    selected = [i for i in registry['instances'].values() if phase is None or i['phase'] == phase]
    require(selected, 'no instances selected')
    separate_paths(registry['root'], output)
    root = new_directory(output)
    for instance in selected:
        value = contract(registry, instance)
        folder = root / instance['id']
        write_json(folder / 'contract.draft.json', value)
        (folder / 'prompt.draft.md').write_text(render_prompt(value))
    write_json(root / 'index.json', {'schema': 'bpb-bs-drafts/1', 'state': 'draft-not-runnable',
                                    'instances': [i['id'] for i in selected]})
    return {'output': str(root), 'drafts': len(selected), 'runnable': 0, 'state': 'draft-not-runnable'}
