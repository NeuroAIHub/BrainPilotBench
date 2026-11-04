"""Maintainer reference: nested grouped ridge and conditional OOF uncertainty.

This module is not supplied in the Agent's task workspace or worker image.
"""
from pathlib import Path
import shutil

from real_brainscore.common import new_directory, separate_paths, write_json
from . import PROTOCOL, IncrementalError
from .data import load_inputs
from .protocol import MODELS, expected_conclusion, validate_plan


def ridge_path(train_x, train_y, test_x, alphas):
    """Train-only scaling, an unpenalized intercept and one SVD per training set."""
    import numpy as np
    mean, scale = train_x.mean(axis=0), train_x.std(axis=0)
    scale = np.where(scale == 0, 1., scale)
    z = (train_x - mean) / scale
    test = (test_x - mean) / scale
    y_mean = train_y.mean(axis=0)
    u, singular, vt = np.linalg.svd(z, full_matrices=False)
    projected_y = u.T @ (train_y - y_mean)
    projected_x = test @ vt.T
    for alpha in alphas:
        yield (projected_x * (singular / (singular ** 2 + alpha))) @ projected_y + y_mean


def aggregate(values, subjects):
    import numpy as np
    return {subject: float(np.mean(values[subjects == subject])) for subject in sorted(set(subjects))}


def score_errors(errors, baseline, subjects):
    import numpy as np
    if not np.isfinite(baseline).all() or np.any(baseline <= 0):
        raise IncrementalError('R2 baseline denominator is nonpositive; no implicit exclusion or clipping')
    per_subject = aggregate(1 - errors / baseline, subjects)
    return float(np.mean(list(per_subject.values()))), per_subject


def squared_errors(packet, predictions):
    import numpy as np
    y = packet['brain']
    ids = [s['stimulus_id'] for s in packet['stimuli']]
    index = {sid: i for i, sid in enumerate(ids)}
    baseline = np.empty_like(y)
    for fold in packet['splits']:
        train, test = [[index[s] for s in fold[k]] for k in ('train_ids', 'test_ids')]
        baseline[test] = (y[test] - y[train].mean(axis=0)) ** 2
    return baseline, {name: (y - values) ** 2 for name, values in predictions.items()}


def paired_interval(packet, baseline, first_error, second_error):
    """Descriptive interval for R2(second) - R2(first), conditional on predictions."""
    import numpy as np
    spec = packet['protocol']
    subjects = np.asarray([n['subject_id'] for n in packet['neuroids']])
    groups = np.asarray([s['story'] for s in packet['stimuli']])
    names = sorted(set(groups))
    denominator = np.stack([baseline[groups == g].sum(axis=0) for g in names])
    difference = np.stack([(first_error - second_error)[groups == g].sum(axis=0) for g in names])
    # Reuse the same story draws across all neuroids and subjects, preserving pairing.
    rng = np.random.default_rng(spec['bootstrap_seed'])
    samples = rng.integers(0, len(names), size=(spec['bootstrap_replicates'], len(names)))
    weights = np.stack([np.bincount(row, minlength=len(names)) for row in samples])
    boot = []
    for batch in np.array_split(weights, max(1, len(weights) // 50)):
        base = batch @ denominator
        if np.any(base <= 0):
            raise IncrementalError('bootstrap has a nonpositive baseline denominator')
        delta = (batch @ difference) / base
        subject_means = np.stack([delta[:, subjects == s].mean(axis=1) for s in sorted(set(subjects))])
        boot.extend(subject_means.mean(axis=0).tolist())
    return np.percentile(boot, spec['bootstrap_percentiles']).tolist()


def summarize(packet, plan, predictions):
    import numpy as np
    spec = packet['protocol']
    subjects = np.asarray([n['subject_id'] for n in packet['neuroids']])
    ids = [s['stimulus_id'] for s in packet['stimuli']]
    names = {s['story'] for s in packet['stimuli']}
    baseline, errors = squared_errors(packet, predictions)
    scores = {}
    for name in MODELS:
        mean, per_subject = score_errors(errors[name].sum(axis=0), baseline.sum(axis=0), subjects)
        scores[name] = {'mean_r2': mean, 'subjects': per_subject}
    delta_subjects = {s: scores['joint']['subjects'][s] - scores['control']['subjects'][s]
                      for s in scores['control']['subjects']}
    interval = paired_interval(packet, baseline, errors['control'], errors['joint'])
    return {
        'schema': 'bpb-incremental-summary/1', 'protocol_id': PROTOCOL,
        'synthetic_only': packet['manifest']['synthetic_only'],
        'input_manifest_sha256': packet['manifest_sha256'], 'control_set': plan['control_set'],
        'coverage': {'stimuli': len(ids), 'stories': len(names), 'subjects': len(set(subjects)),
                     'neuroids': len(subjects), 'outer_folds': len(packet['splits'])},
        'scores': scores,
        'increment': {'mean_delta_r2': scores['joint']['mean_r2'] - scores['control']['mean_r2'],
                      'subjects': delta_subjects, 'descriptive_interval': interval},
        'uncertainty': spec['uncertainty'], 'scope': spec['inference_scope'],
        'official_benchmark_equivalence': False,
    }


def compute(packet, plan):
    import numpy as np
    validate_plan(plan)
    c = packet['controls']
    c = c[:, :1] if plan['control_set'] == 'word_count' else c[:, 1:] if plan['control_set'] == 'position' else c
    x = packet['features']
    matrices = {'control': c, 'model': x, 'joint': np.column_stack([c, x])}
    predictions, traces = nested_predictions(packet, matrices)
    return predictions, traces, summarize(packet, plan, predictions)


def nested_predictions(packet, matrices):
    """Shared, protocol-bound readout for fixed feature conditions."""
    import numpy as np
    matrices = {name: np.asarray(values, dtype=np.float64) for name, values in matrices.items()}
    y, spec = packet['brain'], packet['protocol']
    subjects = np.asarray([n['subject_id'] for n in packet['neuroids']])
    ids = [s['stimulus_id'] for s in packet['stimuli']]
    index = {sid: i for i, sid in enumerate(ids)}
    predictions = {name: np.full(y.shape, np.nan) for name in matrices}
    traces = []
    for fold in packet['splits']:
        train, test = [np.asarray([index[s] for s in fold[k]]) for k in ('train_ids', 'test_ids')]
        baseline = np.zeros(y.shape[1])
        for inner in fold['inner']:
            a, b = [np.asarray([index[s] for s in inner[k]]) for k in ('train_ids', 'test_ids')]
            baseline += ((y[b] - y[a].mean(axis=0)) ** 2).sum(axis=0)
        trace = {'fold_id': fold['fold_id'], 'train_ids': fold['train_ids'], 'test_ids': fold['test_ids'], 'readouts': {}}
        for name, features in matrices.items():
            losses = np.zeros((len(spec['alphas']), y.shape[1]))
            for inner in fold['inner']:
                a, b = [np.asarray([index[s] for s in inner[k]]) for k in ('train_ids', 'test_ids')]
                for k, pred in enumerate(ridge_path(features[a], y[a], features[b], spec['alphas'])):
                    losses[k] += ((pred - y[b]) ** 2).sum(axis=0)
            scores = [score_errors(loss, baseline, subjects)[0] for loss in losses]
            alpha = spec['alphas'][int(np.argmax(scores))]
            predictions[name][test] = next(ridge_path(features[train], y[train], features[test], [alpha]))
            trace['readouts'][name] = {'alpha': alpha, 'inner_r2': scores}
        traces.append(trace)
    if not all(np.isfinite(a).all() for a in predictions.values()):
        raise IncrementalError('outer predictions do not cover every stimulus')
    return predictions, traces


def run_analysis(inputs, output, plan):
    import numpy as np
    separate_paths(inputs, output)
    packet = load_inputs(inputs)
    predictions, traces, summary = compute(packet, plan)
    destination = new_directory(output, allow_empty=True)
    write_json(destination / 'analysis_plan.json', plan)
    write_json(destination / 'results/summary.json', summary)
    write_json(destination / 'results/folds.json', traces)
    write_json(destination / 'conclusion.json', expected_conclusion(summary))
    np.savez(destination / 'results/predictions.npz', **predictions,
             stimulus_ids=np.asarray([s['stimulus_id'] for s in packet['stimuli']]),
             neuroid_ids=np.asarray([n['neuroid_id'] for n in packet['neuroids']]))
    (destination / 'report.md').write_text(
        '# Incremental prediction: maintainer reference\n\n'
        + plan['rationale'] + '\n\n'
        + 'Joint-minus-control R2: %.8g; descriptive interval: %s.\n\n' % (
            summary['increment']['mean_delta_r2'], summary['increment']['descriptive_interval'])
        + 'The interval conditions on fitted OOF predictions. It does not account for refitting uncertainty. '
        'Results concern these observed subjects and held-out story groups. They do not establish causality, '
        'rule out all confounders, demonstrate equivalence, or test new participants. '
        'This is a derived protocol, not an official Brain-Score score.\n')
    return summary


def reference_submission(output, control_set='word_count+position'):
    """Copy the explicit maintainer baseline, never called by Agent task setup."""
    from .protocol import CONTROL_SETS
    if control_set not in CONTROL_SETS:
        raise IncrementalError('unknown control set')
    root = new_directory(output)
    package = Path(__file__).parent
    target = root / 'incremental'
    target.mkdir()
    for name in ('__init__.py', 'protocol.py', 'data.py', 'analysis.py'):
        shutil.copyfile(package / name, target / name)
    # These helpers contain no results. Including them makes the baseline self-contained.
    shared = package.parent / 'real_brainscore'
    (root / 'real_brainscore').mkdir()
    for name in ('__init__.py', 'common.py'):
        shutil.copyfile(shared / name, root / 'real_brainscore' / name)
    write_json(root / 'plan.json', {'protocol_id': PROTOCOL, 'control_set': control_set,
                                   'rationale': 'Check incremental prediction beyond the declared simple stimulus attributes.'})
    (root / 'analyze.py').write_text(
        'import argparse\nfrom pathlib import Path\n'
        'from real_brainscore.common import read_json\nfrom incremental.analysis import run_analysis\n'
        'p=argparse.ArgumentParser()\np.add_argument("--inputs", required=True)\np.add_argument("--output", required=True)\n'
        'a=p.parse_args()\nrun_analysis(a.inputs, a.output, read_json(Path(__file__).with_name("plan.json")))\n')
    return {'submission': str(root), 'baseline': 'maintainer-fixed-script-not-agent'}
