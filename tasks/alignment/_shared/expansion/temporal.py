"""D: complete temporal RSA and a discovery-frozen confirmation window."""
from pathlib import Path
import re

from real_brainscore.common import new_directory, read_json, sha256
from . import ExpansionError
from .packet import array, save, verify
from .rsa import distance, partition, rank_unit, validate_partitions


def prepare(converted, cache, output):
    import numpy as np
    from .features import local_text_features
    source, manifest = verify(converted, 'bpb-eeg2-converted/1')
    meta = read_json(source / 'metadata.json')
    images = meta['image_ids']
    source_concepts = meta['concept_ids']
    concepts = [re.sub(r'^\d{5}_', '', c) for c in source_concepts]
    if len(images) != 200 or len(set(images)) != 200 or len(set(concepts)) != 200:
        raise ExpansionError('expected 200 unique EEG2 test image/concept identities')
    if [re.sub(r'_[0-9]+[a-z]?\.[^.]+$', '', image) for image in images] != concepts:
        raise ExpansionError('EEG concept labels do not match image names')
    times = array(source / 'times.npy').astype('float64') * 1000.
    eeg = array(source / 'eeg.npy').astype('float64')
    if eeg.shape != (2, 200, len(meta['channels']), len(times)) or len(times) < 80:
        raise ExpansionError('expected two subjects with common EEG2 test data/time axis')
    if not np.allclose(np.diff(times), 10., atol=1e-5) or not np.isclose(times[0], -200.):
        raise ExpansionError('unexpected EEG sample times; expected original 100 Hz axis starting -200 ms')
    # Keep the entire released time axis, including the prestimulus interval.
    features, provenance = local_text_features(['a photograph of ' + c.replace('_', ' ') for c in concepts], cache, candidates=True)
    parts = partition(concepts, [.5, .5], 41)
    metadata = {**meta, 'concept_ids': concepts, 'source_concept_ids': source_concepts,
                'candidates': ['distilgpt2_concept_first_block', 'distilgpt2_concept_final_block'],
                'partition_concept_ids': [[concepts[i] for i in part] for part in parts],
                'discovery_subject_indices': [0], 'confirmation_subject_indices': [1],
                'candidate_scope': 'text concept-label representations; static layers are not temporal model states',
                'preprocessing': 'author baseline -200..0 ms, 100 Hz, 17 posterior channels, session-wise MVNN fit on both original train/test partitions; mean 80 repeats per image',
                'confirmation_scope': 'disjoint subjects and concepts; conditional on released within-subject author preprocessing; exploratory public-data reuse'}
    return save(new_directory(output), 'D', metadata, {'eeg': eeg, 'times_ms': times, 'features': features},
                {'source': 'https://osf.io/3jk45/', 'source_manifest_sha256': sha256(source / 'manifest.json'),
                 'author_code_commit': '101997d4f14c41b615bcaf8c0907740106d260c5', 'features': provenance,
                 'modality': 'EEG, not MEG', 'subset': 'first two author subject IDs, fixed before analysis'})


def rsa_inputs(features, eeg, indices, subjects):
    import numpy as np
    count = len(indices)
    triangle = np.triu_indices(count, 1)
    models = []
    rank_matrices = []
    for feature in features:
        ranks = rank_unit(distance(feature[indices])[triangle])
        matrix = np.zeros((count, count))
        matrix[triangle] = ranks
        matrix[(triangle[1], triangle[0])] = ranks
        models.append(ranks); rank_matrices.append(matrix)
    brain = []
    for subject in subjects:
        brain.append(np.stack([rank_unit(distance(eeg[subject, indices, :, t], center=True)[triangle])
                               for t in range(eeg.shape[3])]))
    return np.stack(models), np.mean(brain, axis=0), np.stack(rank_matrices), triangle


def compute(packet, plan):
    import numpy as np
    a, meta, spec = packet['arrays'], packet['metadata'], packet['protocol']
    parts = validate_partitions(meta, [.5, .5], spec['split_seed'])
    times, eeg, features = a['times_ms'], a['eeg'], a['features']
    if (times.ndim != 1 or not np.all(np.diff(times) > 0) or eeg.ndim != 4
            or eeg.shape[1] != len(meta['concept_ids']) or eeg.shape[-1] != len(times)
            or features.shape[:2] != (len(meta['candidates']), len(meta['concept_ids']))):
        raise ExpansionError('temporal identity/time/array shape differs')
    discovery_subjects, confirmation_subjects = meta['discovery_subject_indices'], meta['confirmation_subject_indices']
    if (not discovery_subjects or not confirmation_subjects or set(discovery_subjects) & set(confirmation_subjects)
            or min(discovery_subjects + confirmation_subjects) < 0 or max(discovery_subjects + confirmation_subjects) >= eeg.shape[0]):
        raise ExpansionError('discovery and confirmation subjects must be disjoint')
    dm, db, _, _ = rsa_inputs(features, eeg, parts[0], discovery_subjects)
    cm, cb, rank_matrices, triangle = rsa_inputs(features, eeg, parts[1], confirmation_subjects)
    discovery, confirmation = dm @ db.T, cm @ cb.T
    first, second = plan['candidate_pair']
    windows = [(times >= start) & (times < start + spec['window_width_ms']) for start in spec['window_start_grid_ms']]
    if any(np.sum(window) < 2 for window in windows):
        raise ExpansionError('time axis lacks a prespecified analysis window')
    window_means = [float((discovery[first, w] - discovery[second, w]).mean()) for w in windows]
    selected = int(np.argmax(window_means))
    selected_window = windows[selected]
    observed = float((confirmation[first, selected_window] - confirmation[second, selected_window]).mean())
    rng = np.random.default_rng(spec['permutation_seed'])
    null_max, null_contrast = [], []
    for _ in range(spec['permutations']):
        order = rng.permutation(len(parts[1]))
        # One common stimulus relabeling preserves model-pair and time dependencies.
        vectors = rank_matrices[:, order[triangle[0]], order[triangle[1]]]
        null = vectors @ cb.T
        null_max.append(float(np.max(np.abs(null))))
        null_contrast.append(float((null[first, selected_window] - null[second, selected_window]).mean()))
    null_max, null_contrast = np.asarray(null_max), np.asarray(null_contrast)
    corrected_p = (1 + (null_max[:, None, None] >= np.abs(confirmation)[None]).sum(axis=0)) / (len(null_max) + 1)
    contrast_p = float((1 + (np.abs(null_contrast) >= abs(observed)).sum()) / (len(null_contrast) + 1))
    start = spec['window_start_grid_ms'][selected]
    summary = {'candidates': meta['candidates'], 'candidate_pair': plan['candidate_pair'],
               'selected_window_ms': [start, start + spec['window_width_ms']],
               'discovery_window_differences': window_means, 'confirmation_window_difference': observed,
               'selected_window_label_permutation_p': contrast_p,
               'null_hypothesis': 'no correspondence under common stimulus relabeling; not equality of population model performance',
               'confirmation_scope': meta['confirmation_scope'],
               'time_axis': {'first_ms': float(times[0]), 'last_ms': float(times[-1]), 'samples': len(times)},
               'permutations': spec['permutations'], 'corrected_p_family': 'all candidates and all released times'}
    conclusion = {'selected_window_label_null_rejected': contrast_p <= .05,
                  'precise_effect_onset_established': False, 'layer_depth_is_brain_latency': False,
                  'same_dynamic_mechanism_established': False, 'population_model_superiority_tested': False,
                  'new_prospective_confirmation': False, 'scope': 'observed_disjoint_subject_and_concept_partitions'}
    return summary, {'times_ms': times, 'discovery_rsa': discovery, 'confirmation_rsa': confirmation,
                     'confirmation_max_stat_p': corrected_p, 'null_max_abs_rsa': null_max,
                     'null_window_contrast': null_contrast, 'concept_ids': np.asarray(meta['concept_ids'])}, conclusion
