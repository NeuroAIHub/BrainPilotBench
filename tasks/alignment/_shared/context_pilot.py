#!/usr/bin/env python3
"""Task B pilot: past-only short-passage contexts, local weights, fixed readout.

This produces a maintainer experiment, not a registered or graded Agent task.
"""
import argparse
import copy
from collections import defaultdict
from pathlib import Path
import shutil
import sys

from incremental import IncrementalError
from incremental.data import load_inputs
from incremental.protocol import make_splits, specification
from real_brainscore import BackendError
from real_brainscore.common import load_cache, new_directory, read_json, runtime, seal, separate_paths, sha256, write_json

PROTOCOL = 'pereira384-short-context-pilot-v2'
CONDITIONS = ('sentence_only', 'normal_prefix', 'reversed_prefix')


def context_design(stimuli):
    """Only positions 3/4 have enough history for a nontrivial order control."""
    passages = defaultdict(list)
    for row in stimuli:
        passages[row['passage_label']].append(row)
    records = []
    for rows in passages.values():
        rows.sort(key=lambda row: row['stimulus_num'])
        if len(rows) != 4 or len({r['story'] for r in rows}) != 1:
            raise IncrementalError('context pilot expects intact four-sentence passages')
        for pos in (2, 3):
            target, history = rows[pos], rows[:pos]
            records.append({
                'stimulus_id': target['stimulus_id'], 'position': pos + 1,
                'history_ids': [r['stimulus_id'] for r in history],
                'conditions': {
                    'sentence_only': [target['stimulus']],
                    'normal_prefix': [r['stimulus'] for r in history] + [target['stimulus']],
                    'reversed_prefix': [r['stimulus'] for r in reversed(history)] + [target['stimulus']],
                },
            })
    index = {s['stimulus_id']: i for i, s in enumerate(stimuli)}
    records.sort(key=lambda r: index[r['stimulus_id']])
    return records


def context_specification():
    return {**specification(), 'protocol_id': PROTOCOL,
            'conditions': list(CONDITIONS),
            'targets': 'positions 3/4 with equal normal/reversed prefix token counts; identical common subset for all conditions',
            'interpretation': 'model-only history manipulation; original human responses unchanged; not long-term memory or matched human intervention'}


def matched_rows(design):
    return [i for i, r in enumerate(design)
            if r['token_lengths']['normal_prefix'] == r['token_lengths']['reversed_prefix']]


def run(cache, inputs, output, device='cpu'):
    import numpy as np
    root, _, config = load_cache(cache)
    packet = load_inputs(inputs)
    provenance = read_json(packet['root'] / 'provenance.json')
    if provenance['source_cache_sha256'] != sha256(root / 'manifest.json'):
        raise IncrementalError('Task A and context source caches differ')
    for source in (root, packet['root']):
        separate_paths(source, output)
    destination = new_directory(output)
    design = context_design(packet['stimuli'])
    ids = [s['stimulus_id'] for s in packet['stimuli']]
    selected = [ids.index(row['stimulus_id']) for row in design]
    packet['stimuli'] = [packet['stimuli'][i] for i in selected]
    packet['brain'] = packet['brain'][selected]
    packet['splits'] = make_splits(packet['stimuli'])
    packet['protocol'] = context_specification()
    # Write design and splits before model inference or readout results.
    write_json(destination / 'protocol.json', packet['protocol'])
    write_json(destination / 'contexts.json', design)
    write_json(destination / 'splits.json', packet['splits'])
    write_json(destination / 'stimuli.json', packet['stimuli'])
    write_json(destination / 'neuroids.json', packet['neuroids'])
    np.save(destination / 'brain.npy', packet['brain'], allow_pickle=False)
    execution = runtime(device, online=False)
    from brainscore_language.model_helpers.preprocessing import prepare_context
    from real_brainscore.upstream import model_subject
    subject = model_subject(config, [provenance['layer']], online=False)
    subject.start_neural_recording('language_system', 'fMRI')
    features = {name: [] for name in CONDITIONS}
    max_difference, max_tokens = 0., 0
    for number, row in enumerate(design):
        token_lengths = {}
        for name in CONDITIONS:
            context = prepare_context(row['conditions'][name])
            length = len(subject.tokenizer(context, truncation=False)['input_ids'])
            if length > subject.tokenizer.model_max_length:
                raise IncrementalError('context would be truncated; pilot requires intact histories')
            token_lengths[name] = length
            max_tokens = max(max_tokens, length)
            neural = subject.digest_text(context)['neural']
            values = np.asarray(neural.sel(layer=provenance['layer']).values, dtype=np.float32)
            if values.shape != (1, packet['features'].shape[1]) or not np.isfinite(values).all():
                raise IncrementalError('context feature shape/value mismatch')
            features[name].append(values[0])
        row['token_lengths'] = token_lengths
        original = packet['features'][selected[number]]
        difference = float(np.max(np.abs(features['normal_prefix'][-1] - original)))
        max_difference = max(max_difference, difference)
        if not np.allclose(features['normal_prefix'][-1], original, atol=1e-6, rtol=1e-5):
            raise IncrementalError('normal context extraction does not reproduce the verified cache')
        if (number + 1) % 32 == 0:
            print('context extraction: %d/%d targets' % (number + 1, len(design)), flush=True)
    features = {name: np.stack(values) for name, values in features.items()}
    write_json(destination / 'contexts.json', design)
    for name, values in features.items():
        np.save(destination / ('features-' + name + '.npy'), values, allow_pickle=False)
    write_json(destination / 'provenance.json', {'source': provenance, 'task_a_input_sha256': packet['manifest_sha256'],
                                              'runtime': execution})
    return analyze(packet, features, design, destination, max_difference, max_tokens)


def analyze(packet, features, design, destination, max_difference, max_tokens):
    import numpy as np
    # Match input token counts before any response-dependent readout fitting.
    retained = matched_rows(design)
    excluded = [r['stimulus_id'] for i, r in enumerate(design) if i not in retained]
    packet = copy.copy(packet)
    packet['stimuli'] = [packet['stimuli'][i] for i in retained]
    packet['brain'] = packet['brain'][retained]
    packet['protocol'] = context_specification()
    packet['splits'] = make_splits(packet['stimuli'])
    features = {name: values[retained] for name, values in features.items()}
    write_json(destination / 'protocol.json', packet['protocol'])
    write_json(destination / 'splits.json', packet['splits'])
    write_json(destination / 'analysis_selection.json', {
        'stimulus_ids': [r['stimulus_id'] for r in packet['stimuli']],
        'excluded_token_count_mismatch_ids': excluded,
        'rule': 'normal_prefix and reversed_prefix have equal tokenizer length; no brain response used in selection',
    })
    from incremental.analysis import nested_predictions, paired_interval, score_errors, squared_errors
    predictions, traces = nested_predictions(packet, features)
    baseline, errors = squared_errors(packet, predictions)
    subjects = np.asarray([n['subject_id'] for n in packet['neuroids']])
    scores = {}
    for name in CONDITIONS:
        mean, per_subject = score_errors(errors[name].sum(axis=0), baseline.sum(axis=0), subjects)
        scores[name] = {'mean_r2': mean, 'subjects': per_subject}
    comparisons = {}
    for first in ('sentence_only', 'reversed_prefix'):
        comparisons['normal_minus_' + first] = {
            'mean_delta_r2': scores['normal_prefix']['mean_r2'] - scores[first]['mean_r2'],
            'descriptive_interval': paired_interval(packet, baseline, errors[first], errors['normal_prefix']),
            'subjects': {s: scores['normal_prefix']['subjects'][s] - scores[first]['subjects'][s]
                         for s in scores[first]['subjects']},
        }
    summary = {'schema': 'bpb-context-pilot-summary/1', 'protocol_id': PROTOCOL,
               'synthetic_only': False, 'agent_evaluation': False,
               'coverage': {'stimuli': len(retained), 'candidate_stimuli': len(design),
                            'stories': len({s['story'] for s in packet['stimuli']}),
                            'subjects': len(set(subjects)), 'neuroids': len(subjects)},
               'scores': scores, 'comparisons': comparisons,
               'normal_cache_max_abs_difference': max_difference, 'max_context_tokens': max_tokens,
               'excluded_token_count_mismatches': len(excluded),
               'analyzed_token_count_mismatches': 0,
               'uncertainty': packet['protocol']['uncertainty'], 'scope': packet['protocol']['interpretation'],
               'official_benchmark_equivalence': False}
    write_json(destination / 'results/summary.json', summary)
    write_json(destination / 'results/folds.json', traces)
    np.savez(destination / 'results/predictions.npz', **predictions,
             stimulus_ids=np.asarray([s['stimulus_id'] for s in packet['stimuli']]),
             neuroid_ids=np.asarray([n['neuroid_id'] for n in packet['neuroids']]))
    seal(destination, {'schema': 'bpb-context-pilot-artifacts/1', 'protocol_id': PROTOCOL, 'synthetic_only': False})
    print(__import__('json').dumps(summary, indent=2), flush=True)
    return summary


def replay(source, output):
    """Reanalyse sealed local feature conditions without repeating model inference."""
    import numpy as np
    source = Path(source).resolve()
    separate_paths(source, output)
    manifest = read_json(source / 'manifest.json')
    if manifest.get('schema') != 'bpb-context-pilot-artifacts/1' or manifest.get('synthetic_only') is not False:
        raise IncrementalError('expected real sealed context features')
    actual = set()
    for path in source.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise IncrementalError('nonregular context artifact')
        if path.is_file():
            actual.add(path.relative_to(source).as_posix())
    if actual != set(manifest['files']) | {'manifest.json'}:
        raise IncrementalError('context inventory differs')
    for rel, expected in manifest['files'].items():
        path = source / rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or expected != {'bytes': path.stat().st_size, 'sha256': sha256(path)}:
            raise IncrementalError('context hash/path mismatch')
    destination = new_directory(output)
    names = ['brain.npy', 'stimuli.json', 'neuroids.json', 'contexts.json'] + ['features-' + name + '.npy' for name in CONDITIONS]
    for name in names:
        shutil.copyfile(source / name, destination / name)
    provenance = read_json(source / 'provenance.json')
    provenance['replayed_feature_manifest_sha256'] = sha256(source / 'manifest.json')
    write_json(destination / 'provenance.json', provenance)
    packet = {'stimuli': read_json(source / 'stimuli.json'), 'neuroids': read_json(source / 'neuroids.json'),
              'brain': np.load(source / 'brain.npy', allow_pickle=False)}
    features = {name: np.load(source / ('features-' + name + '.npy'), allow_pickle=False) for name in CONDITIONS}
    original = read_json(source / 'results/summary.json')
    return analyze(packet, features, read_json(source / 'contexts.json'), destination,
                   original['normal_cache_max_abs_difference'], original['max_context_tokens'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--cache')
    group.add_argument('--features-from', help='Replay a sealed context pilot without model inference')
    p.add_argument('--inputs', help='Task A inputs, required with --cache')
    p.add_argument('--output', required=True)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    try:
        args = vars(p.parse_args())
        source = args.pop('features_from')
        if source:
            if args['inputs']:
                p.error('--inputs is only used with --cache')
            replay(source, args['output'])
        else:
            if not args['inputs']:
                p.error('--cache requires --inputs')
            run(**args)
    except (IncrementalError, BackendError, OSError, ImportError) as exc:
        print('context pilot: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(1)
