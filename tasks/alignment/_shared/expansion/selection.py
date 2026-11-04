"""F: constrained selection against owner-only human measurements."""
import hashlib
import json
import os
from pathlib import Path

from real_brainscore.common import new_directory, read_json, seal, separate_paths, sha256, write_json
from . import ExpansionError
from .packet import array, save, verify
from .protocol import specification


def prepare(csv, cache, output, hidden):
    import numpy as np
    import pandas as pd
    from .features import local_text_features
    for a, b in ((output, hidden), (csv, output), (csv, hidden)):
        separate_paths(a, b)
    frame = pd.read_csv(csv)
    frame = frame[frame['roi'] == 'lang_LH_netw'].copy()
    if frame.duplicated(['item_id', 'target_UID']).any():
        raise ExpansionError('duplicate sentence/subject responses')
    # Coverage decisions only, before inspecting response magnitudes.
    train_subjects = sorted(set(frame.target_UID) - set(frame.loc[frame.cond != 'B', 'target_UID']))
    train = frame[(frame.cond == 'B') & frame.target_UID.isin(train_subjects)]
    candidates = frame[frame.cond != 'B']
    coverage = candidates.groupby('item_id').target_UID.apply(lambda v: tuple(sorted(v)))
    groups = sorted(set(coverage), key=lambda g: (-len(g), -int(coverage.apply(lambda v: v == g).sum()), g))
    if not groups or len(groups[0]) < 2 or len(train_subjects) < 2:
        raise ExpansionError('insufficient independent participant coverage')
    held_subjects = list(groups[0])
    candidate_ids = sorted(coverage[coverage.apply(lambda g: g == groups[0])].index.tolist(),
                           key=lambda i: hashlib.sha256(('tuckute:' + str(i)).encode()).hexdigest())
    candidates = candidates[candidates.item_id.isin(candidate_ids)]
    table = train.pivot(index='item_id', columns='target_UID', values='response_target')[train_subjects]
    missing_train = table.index[~np.isfinite(table.to_numpy()).all(axis=1)].tolist()
    train_ids = sorted(set(table.index) - set(missing_train))
    train_y = table.loc[train_ids].to_numpy(dtype='float64')
    hidden_y = candidates.pivot(index='item_id', columns='target_UID', values='response_target').loc[candidate_ids, held_subjects].to_numpy(dtype='float64')
    if (set(train_ids) & set(candidate_ids) or not np.isfinite(train_y).all() or not np.isfinite(hidden_y).all()):
        raise ExpansionError('overlap or incomplete response coverage')
    text = frame.groupby('item_id').sentence.unique()
    if any(len(v) != 1 for v in text):
        raise ExpansionError('conflicting sentence identities')
    all_ids = train_ids + candidate_ids
    texts = [str(text[i][0]).strip() for i in all_ids]
    if set(texts[:len(train_ids)]) & set(texts[len(train_ids):]):
        raise ExpansionError('sentence text leaks across partitions')
    features, feature_provenance = local_text_features(texts, cache)
    # Opaque IDs omit source condition and author model predictions.
    ids = ['sentence-' + hashlib.sha256(('tuckute:' + str(i)).encode()).hexdigest()[:16] for i in all_ids]
    words = np.asarray([len(s.split()) for s in texts])
    bins = np.digitize(words, specification('F')['length_bins_words'][1:-1])
    pool_bins = bins[len(train_ids):]
    counts = {str(b): int(np.sum(pool_bins == b)) // 2 for b in sorted(set(pool_bins))}
    quota = {b: 0 for b in counts}
    for _ in range(specification('F')['selection_per_group']):
        available = [b for b in quota if quota[b] < counts[b]]
        if not available:
            raise ExpansionError('insufficient candidates for matched budget')
        chosen = min(available, key=lambda b: (quota[b], int(b)))
        quota[chosen] += 1
    meta = {'train_ids': ids[:len(train_ids)], 'candidate_ids': ids[len(train_ids):],
            'train_sentences': texts[:len(train_ids)], 'candidate_sentences': texts[len(train_ids):],
            'train_subjects': [str(s) for s in train_subjects], 'hidden_subject_count': len(held_subjects),
            'candidate_length_bins': pool_bins.tolist(), 'quota_per_group': quota,
            'response_units': 'author session-wise voxel z-scores, then ROI mean',
            'population': 'largest common held-out participant coverage group; ties resolved by candidate count then participant IDs'}
    public = save(new_directory(output), 'F', meta,
                  {'train_features': features[:len(train_ids)], 'candidate_features': features[len(train_ids):], 'train_responses': train_y},
                  {'source': 'https://osf.io/ru38b/', 'csv_sha256': sha256(csv), 'features': feature_provenance,
                   'excluded_incomplete_training_source_ids': missing_train,
                   'contamination': 'public sentences and labels; offline experimental use only'})
    owner = new_directory(hidden)
    np.save(owner / 'responses.npy', hidden_y, allow_pickle=False)
    write_json(owner / 'identities.json', {'candidate_ids': meta['candidate_ids'], 'subjects': [str(s) for s in held_subjects]})
    seal(owner, {'schema': 'bpb-selection-hidden/1', 'public_manifest_sha256': public['manifest_sha256']})
    return {'inputs': str(public['root']), 'hidden': str(owner), 'train_sentences': len(train_ids),
            'candidate_sentences': len(candidate_ids), 'train_subjects': train_subjects, 'heldout_subjects': held_subjects}


def balanced_selection(predictions, metadata):
    import numpy as np
    ids = metadata['candidate_ids']
    bins = np.asarray(metadata['candidate_length_bins'])
    drive, suppress = [], []
    for b, count in metadata['quota_per_group'].items():
        indices = np.flatnonzero(bins == int(b))
        ordered = sorted(indices, key=lambda i: (float(predictions[i]), ids[i]))
        if 2 * count > len(ordered):
            raise ExpansionError('infeasible selection quota')
        suppress.extend(ids[i] for i in ordered[:count])
        drive.extend(ids[i] for i in ordered[-count:] if count)
    return {'drive': sorted(drive), 'suppress': sorted(suppress)}


def compute(packet, plan):
    import numpy as np
    from incremental.analysis import ridge_path
    a, meta = packet['arrays'], packet['metadata']
    pred = next(ridge_path(a['train_features'].astype('float64'), a['train_responses'].mean(axis=1, keepdims=True),
                          a['candidate_features'].astype('float64'), [100.]))[:, 0]
    selection = balanced_selection(pred, meta)
    return {'selection': selection}, {'candidate_ids': np.asarray(meta['candidate_ids']), 'predictions': pred}, {
        'new_human_experiment_performed': False, 'hidden_responses_used': False,
        'public_label_contamination_possible': True, 'scope': 'offline_candidate_pool_observed_heldout_subjects'}


def load_hidden(root, packet):
    root, manifest = verify(root, 'bpb-selection-hidden/1')
    identities = read_json(root / 'identities.json')
    if (manifest['public_manifest_sha256'] != packet['manifest_sha256']
            or identities['candidate_ids'] != packet['metadata']['candidate_ids']):
        raise ExpansionError('hidden/public identities differ')
    y = array(root / 'responses.npy')
    if y.shape != (len(identities['candidate_ids']), len(identities['subjects'])) or y.dtype.kind != 'f':
        raise ExpansionError('hidden response shape/dtype differs')
    return {'responses': y, **identities, 'manifest_sha256': sha256(root / 'manifest.json')}


def validate_selection(packet, output, plan):
    import numpy as np
    from execution import AnalysisFailure
    from .evaluation import bounded_output
    try:
        bounded_output(output)
        root, meta = Path(output), packet['metadata']
        if read_json(root / 'analysis_plan.json') != plan:
            raise ExpansionError('saved plan differs')
        expected_conclusion = {'new_human_experiment_performed': False, 'hidden_responses_used': False,
                               'public_label_contamination_possible': True, 'scope': 'offline_candidate_pool_observed_heldout_subjects'}
        if read_json(root / 'conclusion.json') != expected_conclusion:
            raise ExpansionError('unsupported interpretation')
        summary = read_json(root / 'results/summary.json')
        if (set(summary) != {'protocol_id', 'input_manifest_sha256', 'selection'}
                or summary['protocol_id'] != packet['protocol']['protocol_id']
                or summary['input_manifest_sha256'] != packet['manifest_sha256']):
            raise ExpansionError('invalid selection summary')
        selection = summary['selection']
        ids = meta['candidate_ids']
        if not isinstance(selection, dict) or set(selection) != {'drive', 'suppress'}:
            raise ExpansionError('drive/suppress groups required')
        k = packet['protocol']['selection_per_group']
        for values in selection.values():
            if (not isinstance(values, list) or len(values) != k or len(set(values)) != k or not set(values) <= set(ids)):
                raise ExpansionError('invalid candidate selection or budget')
            for b, count in meta['quota_per_group'].items():
                if sum(meta['candidate_length_bins'][ids.index(i)] == int(b) for i in values) != count:
                    raise ExpansionError('length-bin quota violated')
        if set(selection['drive']) & set(selection['suppress']):
            raise ExpansionError('groups overlap')
        pred_ids = array(root / 'results/candidate_ids.npy')
        pred = array(root / 'results/predictions.npy')
        if (pred_ids.shape != (len(ids),) or len(set(pred_ids)) != len(ids) or set(pred_ids) != set(ids)
                or pred.shape != (len(ids),) or pred.dtype != np.dtype('float64')):
            raise ExpansionError('prediction identities/dtype/shape differ')
        order = {v: i for i, v in enumerate(pred_ids)}
        return {key: sorted(values) for key, values in selection.items()}, pred[[order[i] for i in ids]]
    except Exception as exc:
        raise AnalysisFailure('invalid selection: ' + str(exc)) from exc


def freeze(ledger, key, record):
    """Owner ledger: one choice per packet/participant, identical retries allowed.

    The operator assigns one ledger directory per Agent identity. It must never
    be inside the Agent workspace. Atomic exclusive creation arbitrates races.
    """
    from execution import AnalysisFailure, InfrastructureError
    root = Path(ledger).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / (key + '.json')
    canonical = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != canonical:
            raise AnalysisFailure('submission already frozen; different source, plan, predictions or choices rejected')
        return hashlib.sha256(canonical).hexdigest()
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise InfrastructureError('failed to persist submission freeze') from exc
    return hashlib.sha256(canonical).hexdigest()


def effect(selection, ids, y):
    import numpy as np
    index = {sid: i for i, sid in enumerate(ids)}
    delta = y[[index[i] for i in selection['drive']]].mean(axis=0) - y[[index[i] for i in selection['suppress']]].mean(axis=0)
    return float(np.mean(delta)), delta.tolist()


def grade_selection(packet, owner, output, saved_results, plan, source_hashes, ledger):
    import numpy as np
    from execution import AnalysisFailure
    selection, predictions = validate_selection(packet, output, plan)
    if saved_results is None:
        raise AnalysisFailure('F requires previously saved choices/predictions for replay comparison')
    saved, saved_predictions = validate_selection(packet, saved_results, plan)
    if saved != selection or not np.allclose(saved_predictions, predictions, atol=1e-7, rtol=1e-5):
        raise AnalysisFailure('frozen saved and replayed choices/predictions differ')
    separate_paths(ledger, packet['root'])
    separate_paths(ledger, saved_results)
    digest = freeze(ledger, packet['manifest_sha256'], {'selection': selection,
                    'predictions_sha256': hashlib.sha256(saved_predictions.tobytes()).hexdigest(),
                    'plan': plan, 'source': source_hashes, 'hidden_manifest_sha256': owner['manifest_sha256']})
    ids, y, meta = owner['candidate_ids'], owner['responses'], packet['metadata']
    value, subjects = effect(selection, ids, y)
    fixed, _, _ = compute(packet, plan)
    fixed_value, _ = effect(fixed['selection'], ids, y)
    rng = np.random.default_rng(packet['protocol']['random_seed'])
    random_values = []
    bins = np.asarray(meta['candidate_length_bins'])
    for _ in range(packet['protocol']['random_baseline_replicates']):
        groups = {'drive': [], 'suppress': []}
        for b, count in meta['quota_per_group'].items():
            chosen = rng.permutation(np.flatnonzero(bins == int(b)))[:2 * count]
            groups['drive'].extend(ids[i] for i in chosen[:count])
            groups['suppress'].extend(ids[i] for i in chosen[count:])
        random_values.append(effect(groups, ids, y)[0])
    return {'state': 'scored', 'selection_valid': 1, 'selection_effect': value,
            'subject_effects': dict(zip(owner['subjects'], subjects)), 'fixed_predictor_effect': fixed_value,
            'random_effect_mean': float(np.mean(random_values)), 'random_effect_interval': np.percentile(random_values, [2.5, 97.5]).tolist(),
            'random_reference_percentile': float(np.mean(np.asarray(random_values) <= value)),
            'random_reference_is_significance_test': False, 'freeze_sha256': digest,
            'scope': 'offline_candidate_pool_observed_heldout_subjects'}
