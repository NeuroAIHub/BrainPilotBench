"""Explicit server preparation and scoring. No work is performed on import."""
import csv
from pathlib import Path

from . import BENCHMARK, CACHE_SCHEMA, COMMIT, REAL_PROFILE, BackendError
from .common import config, load_cache, new_directory, read_json, runtime, seal, separate_paths, sha256, write_json
from .upstream import CV, CachedSubject, cached_benchmark, feature_assembly, load_brain, model_subject, traced_metric, traced_score


def resolve_config(source, output, revision='main', tokenizer_revision=None, allow_download=False):
    if not allow_download:
        raise BackendError('metadata network access requires --allow-download')
    configuration = config(source, require_revision=False)
    from huggingface_hub import HfApi
    api = HfApi()
    model = configuration['model']
    model['revision'] = api.model_info(model['id'], revision=model.get('revision') or revision).sha
    model['tokenizer_revision'] = api.model_info(
        model['id'], revision=model.get('tokenizer_revision') or tokenizer_revision or model['revision']).sha
    output = Path(output).expanduser().resolve()
    from .common import outside_repository
    outside_repository(output)
    if output.exists():
        raise BackendError('refusing to replace resolved configuration')
    write_json(output, configuration)
    return configuration


def prepare(configuration_path, output, device='cpu', allow_download=False):
    if not allow_download:
        raise BackendError('prepare may fetch brain data, ceilings and weights; pass --allow-download on the server')
    configuration = config(configuration_path)
    provenance = runtime(device, online=True)
    import numpy as np
    from brainscore_language import load_benchmark
    from brainscore_core.supported_data_standards.brainio.packaging import write_netcdf
    root = new_directory(output)
    benchmark = load_benchmark(BENCHMARK)
    brain = benchmark.data
    if tuple(brain.dims) != ('presentation', 'neuroid') or not np.isfinite(brain.values).all():
        raise BackendError('unexpected nonfinite brain assembly/axes after official experiment selection')
    stimuli = []
    for i in range(len(brain['presentation'])):
        record = {key: str(brain[key].values[i]) for key in ('stimulus_id', 'stimulus', 'story', 'passage_label')}
        record['passage_index'] = int(brain['passage_index'].values[i])
        stimuli.append(record)
    if len(stimuli) != 384 or len({row['stimulus_id'] for row in stimuli}) != 384:
        raise BackendError('expected 384 unique stimuli from the official experiment')
    subject = model_subject(configuration, online=True)
    subject.start_neural_recording('language_system', 'fMRI')
    arrays = {}
    for passage in sorted({row['passage_label'] for row in stimuli}):
        indices = [i for i, row in enumerate(stimuli) if row['passage_label'] == passage]
        neural = subject.digest_text([stimuli[i]['stimulus'] for i in indices])['neural']
        for layer in configuration['layers']:
            values = np.asarray(neural.sel(layer=layer).values, dtype=np.float32)
            if values.ndim != 2 or len(values) != len(indices) or not np.isfinite(values).all():
                raise BackendError('invalid model representations for ' + layer)
            if layer not in arrays:
                arrays[layer] = np.empty((len(stimuli), values.shape[1]), dtype=np.float32)
            arrays[layer][indices] = values
    (root / 'features').mkdir()
    for i, layer in enumerate(configuration['layers']):
        np.save(root / 'features' / ('layer-%03d.npy' % i), arrays[layer], allow_pickle=False)
    write_netcdf(brain, str(root / 'brain.nc'))
    write_json(root / 'config.json', configuration)
    write_json(root / 'stimuli.json', stimuli)
    ceiling = float(benchmark.ceiling)
    if not np.isfinite(ceiling) or ceiling <= 0:
        raise BackendError('official ceiling must be finite and positive')
    write_json(root / 'ceiling.json', {'value': ceiling, 'benchmark': BENCHMARK, 'upstream_commit': COMMIT,
                                    'source': 'official benchmark cached ceiling; upstream checks object SHA-1'})
    write_json(root / 'runtime.json', provenance)
    write_json(root / 'protocol.json', {
        'benchmark': BENCHMARK, 'upstream_commit': COMMIT,
        'cv': {**CV, 'splits': 10}, 'regression': 'upstream RidgeGCVTorch',
        'alphas': [.001, .01, .1, 1., 10., 100., 1000.], 'alpha_per_target': False,
        'aggregation': 'median all neuroids within fold, then mean folds',
        'normalization': 'official ceiling division with clipping to [0,1]',
        'context': 'upstream prepare_context over sentence prefixes within each passage_label',
        'pooling': 'last-token at configured module output', 'acceptance': 'server-validation-pending',
    })
    seal(root, {'schema': CACHE_SCHEMA, 'synthetic_only': False, 'benchmark': BENCHMARK,
                'upstream_commit': COMMIT, 'layers': configuration['layers'],
                'acceptance': 'server-validation-pending'})
    return {'cache': str(root), 'stimuli': len(stimuli), 'layers': len(arrays), 'acceptance': 'server-validation-pending'}


def score_summary(score, layer):
    import math
    value = score.attrs['layer_scores'][layer]
    raw, ceiling = float(value.attrs['raw']), float(value.attrs['ceiling'])
    result = {'raw_score': raw, 'ceiling': ceiling, 'normalized_score': float(value),
              'unclipped_normalized_score': raw / ceiling}
    if not all(math.isfinite(x) for x in result.values()):
        raise BackendError('nonfinite official score')
    return result


def export_trace(root, records):
    import numpy as np
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    predictions, fold_ids, stimulus_ids, folds = [], [], [], []
    neuroid_ids = None
    with (root / 'fold_scores.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['fold_id', 'subject_id', 'neuroid_id', 'pearson_r'])
        for index, record in enumerate(records):
            prediction = record['prediction'].sortby('neuroid_id')
            correlation = record['correlations'].sortby('neuroid_id')
            ids = [str(x) for x in prediction['neuroid_id'].values]
            if ids != [str(x) for x in correlation['neuroid_id'].values] or (neuroid_ids is not None and ids != neuroid_ids):
                raise BackendError('trace neuroid identity mismatch')
            neuroid_ids = ids
            test_ids = [str(x) for x in prediction['stimulus_id'].values]
            fold = 'fold-%d' % index
            predictions.append(np.asarray(prediction.values, dtype=np.float64))
            stimulus_ids.extend(test_ids)
            fold_ids.extend([fold] * len(test_ids))
            folds.append({'fold_id': fold, 'train_ids': record['train_ids'], 'test_ids': test_ids, 'alpha': record['alpha']})
            for subject, unit, value in zip(correlation['subject'].values, ids, correlation.values):
                writer.writerow([fold, str(subject), unit, float(value)])
    if not records:
        raise BackendError('upstream metric produced no recorded folds')
    np.savez(root / 'predictions.npz', values=np.concatenate(predictions), fold_ids=np.array(fold_ids),
             stimulus_ids=np.array(stimulus_ids), neuroid_ids=np.array(neuroid_ids))
    write_json(root / 'folds.json', folds)


def score_fixed(cache, output, layer=None, device='cpu', compare_live=False, allow_download=False,
                atol=1e-6, rtol=1e-5):
    root, manifest, configuration = load_cache(cache)
    separate_paths(root, output)
    if compare_live and not allow_download:
        raise BackendError('live official-entry comparison may fetch upstream data; explicitly pass --allow-download')
    provenance = runtime(device, online=compare_live)
    import numpy as np
    layer = layer or configuration['task1_layer']
    if layer not in configuration['layers']:
        raise BackendError('requested layer is not cached')
    destination = new_directory(output, allow_empty=True)
    benchmark = cached_benchmark(root)
    score, records = traced_score(benchmark, CachedSubject(root, layer))
    summary = {**score_summary(score, layer), 'schema': 'bpb-real-alignment-summary/1', 'synthetic_only': False,
               'benchmark': BENCHMARK, 'upstream_commit': COMMIT, 'layer': layer,
               'input_manifest_sha256': sha256(root / 'manifest.json'), 'acceptance': 'server-validation-pending'}
    analysis = {'schema': 'bpb-real-analysis-config/1', 'benchmark': BENCHMARK, 'upstream_commit': COMMIT,
                'model': configuration['model'], 'layer': layer,
                'input_manifest_sha256': summary['input_manifest_sha256']}
    export_trace(destination / 'results', records)
    write_json(destination / 'analysis_config.json', analysis)
    write_json(destination / 'results/summary.json', summary)
    write_json(destination / 'runtime.json', provenance)
    verification = {'traced_vs_untraced': None, 'live_vs_cached': None, 'atol': atol, 'rtol': rtol,
                    'tolerances_status': 'provisional_not_calibrated'}
    plain = score_summary(cached_benchmark(root)(CachedSubject(root, layer)), layer)
    verification['traced_vs_untraced'] = all(np.isclose(summary[k], v, atol=atol, rtol=rtol) for k, v in plain.items())
    if compare_live:
        from brainscore_language import load_benchmark
        # The installed official entry uses its own data/ceiling loader, so this
        # also checks the exported assembly and offline benchmark substitution.
        live = score_summary(load_benchmark(BENCHMARK)(model_subject(configuration, [layer], online=False)), layer)
        verification['live_result'] = live
        verification['live_vs_cached'] = all(np.isclose(summary[k], v, atol=atol, rtol=rtol) for k, v in live.items())
    write_json(destination / 'verification.json', verification)
    (destination / 'report.md').write_text(
        '# Real Brain-Score server draft\n\nOfficial pinned metric; see results, folds and runtime provenance.\n'
        'This run alone does not certify the Agent benchmark or its isolation.\n')
    if not verification['traced_vs_untraced'] or verification['live_vs_cached'] is False:
        raise BackendError('reference equivalence failed; inspect verification.json; do not promote the task')
    return summary


def _subject_scores(prediction, target, correlation):
    import numpy as np
    scores = correlation(prediction, target)
    if not np.isfinite(scores.values).all():
        raise BackendError('nonfinite per-neuroid Pearson scores')
    subjects = scores['subject'].values
    return {str(subject): float(np.median(scores.values[subjects == subject])) for subject in sorted(set(subjects))}


def _oof_prediction(records, target):
    import numpy as np
    ids = [str(x) for x in target['stimulus_id'].values]
    units = [str(x) for x in target['neuroid_id'].values]
    index = {sid: i for i, sid in enumerate(ids)}
    values, covered = np.empty(target.shape, dtype=np.float64), set()
    for record in records:
        pred = record['prediction']
        unit_index = {str(x): i for i, x in enumerate(pred['neuroid_id'].values)}
        if set(unit_index) != set(units):
            raise BackendError('OOF neuroid coverage mismatch')
        reordered = pred.values[:, [unit_index[unit] for unit in units]]
        for row, sid in enumerate(pred['stimulus_id'].values):
            sid = str(sid)
            if sid in covered or sid not in index:
                raise BackendError('OOF stimulus coverage mismatch')
            values[index[sid]] = reordered[row]
            covered.add(sid)
    if covered != set(ids):
        raise BackendError('OOF predictions must cover development stimuli exactly once')
    return target.copy(data=values)


def build_profile(cache, output, device='cpu', seed=17, fraction=.2, folds=5, margin=.02):
    root, manifest, configuration = load_cache(cache)
    separate_paths(root, output)
    provenance = runtime(device)
    import numpy as np
    from sklearn.model_selection import GroupShuffleSplit
    from brainscore_language import load_metric
    from .profile_packet import validate_real_packet
    if not 0 < fraction < 1 or not 0 < margin < 1 or folds < 2:
        raise BackendError('invalid confirmation fraction, fold count or descriptive margin')
    destination = new_directory(output)
    brain = load_brain(root)
    groups = brain['story'].values
    development, confirmation = next(GroupShuffleSplit(n_splits=1, test_size=fraction, random_state=seed).split(
        np.zeros(len(groups)), groups=groups))
    if len(set(groups[development])) < folds:
        raise BackendError('not enough development story groups for the requested inner folds')
    split = {'schema': 'bpb-material-split/1', 'group': 'story', 'seed': seed, 'fraction': fraction, 'inner_folds': folds,
             'development_ids': [str(x) for x in brain['stimulus_id'].values[development]],
             'confirmation_ids': [str(x) for x in brain['stimulus_id'].values[confirmation]]}
    write_json(destination / 'split.json', split)  # frozen before computing any layer score
    datasets = {}
    for role, positions in [('development', development), ('confirmation', confirmation)]:
        target = brain.isel(presentation=positions)
        subjects = sorted({str(x) for x in target['subject'].values})
        datasets[role] = {'metric_id': 'subject_median_pooled_pearsonr', 'subjects': subjects,
                          'blocks': sorted({str(x) for x in target['story'].values}),
                          'stimulus_ids': [str(x) for x in target['stimulus_id'].values],
                          'subject_layer_scores': {subject: {} for subject in subjects}}
    for number, layer in enumerate(configuration['layers']):
        features = feature_assembly(root, layer)
        if list(features['stimulus_id'].values) != list(brain['stimulus_id'].values):
            raise BackendError('cached X and Y stimulus identities/order differ')
        x_dev, y_dev = features.isel(presentation=development), brain.isel(presentation=development)
        x_test, y_test = features.isel(presentation=confirmation), brain.isel(presentation=confirmation)
        metric = load_metric('ridge_pearsonr', crossvalidation_kwargs={**CV, 'splits': folds, 'random_state': seed})
        _, records = traced_metric(metric, lambda: metric(x_dev, y_dev))
        prediction = _oof_prediction(records, y_dev)
        dev_scores = _subject_scores(prediction, y_dev, metric.correlation)
        export_trace(destination / 'traces' / ('layer-%03d' % number), records)
        # Confirmation responses are never passed to fit or alpha selection.
        metric.regression.fit(x_dev, y_dev)
        test_prediction = metric.regression.predict(x_test)
        test_scores = _subject_scores(test_prediction, y_test, metric.correlation)
        np.savez(destination / 'traces' / ('confirmation-%03d.npz' % number),
                 values=np.asarray(test_prediction.values, dtype=np.float64),
                 stimulus_ids=np.asarray(test_prediction['stimulus_id'].values).astype(str),
                 neuroid_ids=np.asarray(test_prediction['neuroid_id'].values).astype(str))
        for role, scores in [('development', dev_scores), ('confirmation', test_scores)]:
            for subject, value in scores.items():
                datasets[role]['subject_layer_scores'][subject][layer] = value
    packet = {'schema': 'bpb-real-profile-packet/1', 'synthetic_only': False, 'protocol_id': REAL_PROFILE,
              'packet_id': 'pereira-' + sha256(root / 'manifest.json')[:16] + '-seed-' + str(seed),
              'layers': configuration['layers'], 'baseline_layer': configuration['baseline_layer'], 'margin': margin,
              'source_id': 'development', 'confirmation_id': 'confirmation',
              'shift': {'kind': 'new_material', 'description': 'Same subjects; disjoint story groups, reserved before fitting and selection.'},
              'provenance': {'upstream_commit': COMMIT, 'benchmark_source': BENCHMARK,
                             'cache_sha256': sha256(root / 'manifest.json'), 'split_sha256': sha256(destination / 'split.json'),
                             'model': configuration['model'], 'aggregation': 'pooled held-out Pearson per neuroid; median within subject; equal mean subjects',
                             'official_benchmark_equivalence': False, 'acceptance': 'server-validation-pending',
                             'threshold_status': 'engineering_only_not_scientifically_calibrated'},
              'datasets': datasets}
    validate_real_packet(packet)
    write_json(destination / 'packet.json', packet)
    write_json(destination / 'runtime.json', provenance)
    seal(destination, {'schema': 'bpb-real-profile-artifacts/1', 'synthetic_only': False, 'protocol_id': REAL_PROFILE})
    return {'packet': str(destination / 'packet.json'), 'protocol_id': REAL_PROFILE, 'official_benchmark_equivalence': False}
