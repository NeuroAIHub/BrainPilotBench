"""C: concept-disjoint neural/behavioral evaluation of fixed representations."""
from pathlib import Path
import re

from real_brainscore.common import new_directory, sha256
from . import ExpansionError
from .packet import array, save
from .rsa import distance, partition, rank_unit, validate_partitions, vector


def prepare(raw, cache, output):
    import numpy as np
    import pandas as pd
    from .features import local_text_features
    raw = Path(raw)
    concept_ids = (raw / 'things-concept-ids.txt').read_text().splitlines()
    if len(concept_ids) != 1854 or len(set(concept_ids)) != 1854:
        raise ExpansionError('expected 1854 unique THINGS concept identities')
    all_rows, responses, subjects = [], [], []
    for subject in ('01', '02', '03'):
        rows = pd.read_csv(raw / ('sub-' + subject + '_StimulusMetadataTestset.csv'))
        y = array(raw / ('sub-' + subject + '_TestResponsesIT.npy')).astype('float64')
        if len(rows) != len(y) or not (rows.trial_type == 'test').all():
            raise ExpansionError('IT metadata and responses differ')
        all_rows.append(rows); responses.append(y); subjects.append(subject)
    image_ids = sorted(set(all_rows[0].stimulus))
    if any(set(rows.stimulus) != set(image_ids) for rows in all_rows):
        raise ExpansionError('IT subject image coverage differs')
    concepts = [re.sub(r'_[0-9]+[a-z]?\.[^.]+$', '', image) for image in image_ids]
    if len(set(concepts)) != len(concepts) or not set(concepts) <= set(concept_ids):
        raise ExpansionError('image/concept correspondence ambiguous')
    # Keep source image identities: behavior is concept-level, not the same image.
    neural = []
    repeat_counts = []
    for rows, y in zip(all_rows, responses):
        averages = np.stack([y[(rows.stimulus == image).to_numpy()].mean(axis=0) for image in image_ids])
        neural.append(distance(averages, center=True))
        repeat_counts.append([int((rows.stimulus == image).sum()) for image in image_ids])
    triplets = np.loadtxt(raw / 'things-behavior-trainset.txt', dtype='int64')
    if triplets.ndim != 2 or triplets.shape[1] != 3 or triplets.min() < 0 or triplets.max() >= 1854:
        raise ExpansionError('invalid source behavior triplets')
    # The author's preprocess_triplets.m applies sortind before writing
    # trainset.txt. Its indices already address alphabetic unique_id at base 0.
    # Applying sortind a second time would silently mislabel the observations.
    global_ids = np.asarray([concept_ids.index(c) for c in concepts])
    keep = np.isin(triplets, global_ids).all(axis=1)
    source_row_ids = np.flatnonzero(keep)
    triplets = triplets[keep]
    index = {int(i): j for j, i in enumerate(global_ids)}
    triplets = np.asarray([[index[int(i)] for i in row] for row in triplets], dtype='int64')
    parts = partition(concepts, [.4, .3, .3], 41)
    split = np.full(len(triplets), -1, dtype='int64')
    for number, part in enumerate(parts):
        split[np.isin(triplets, part).all(axis=1)] = number
    use = split >= 0
    if any(int(np.sum(split == i)) < 5 for i in range(3)):
        raise ExpansionError('insufficient within-partition behavior trials; do not silently mix concepts')
    features, provenance = local_text_features(['a photograph of ' + c.replace('_', ' ') for c in concepts], cache, candidates=True)
    meta = {'concept_ids': concepts, 'image_ids': image_ids, 'subjects': subjects, 'repeat_counts': repeat_counts,
            'candidates': ['distilgpt2_concept_first_block', 'distilgpt2_concept_final_block'],
            'partition_concept_ids': [[concepts[i] for i in part] for part in parts],
            'behavior_chosen_pair': [0, 1], 'behavior_index_mapping': 'already-sorted zero-based source trainset indices -> unique_id; no second sortind',
            'matching': 'one IT test exemplar per concept vs concept-level odd-one-out judgments; different modality participants',
            'candidate_scope': 'language representations of concept labels, not features extracted from the displayed images'}
    files = ['things-concept-ids.txt', 'things-preprocess_triplets.m', 'things-behavior-trainset.txt']
    files += ['sub-' + s + suffix for s in subjects for suffix in ('_StimulusMetadataTestset.csv', '_TestResponsesIT.npy')]
    return save(new_directory(output), 'C', meta,
                {'features': features, 'neural_rdms': np.stack(neural), 'triplets': triplets[use],
                 'triplet_partition': split[use], 'source_triplet_rows': source_row_ids[use]},
                {'sources': ['https://api.figshare.com/v2/articles/23284622', 'https://osf.io/f5rn6/'],
                 'raw_sha256': {n: sha256(raw / n) for n in files}, 'features': provenance,
                 'behavior_source': 'author trainset; this derived protocol repartitions by concept, not the official behavior test split',
                 'candidate_training': 'no fitting on human behavior or neural data; temperature uses training concepts only'})


def negative_log_likelihood(rdm, triplets, temperature):
    import numpy as np
    pairs = ((0, 1), (0, 2), (1, 2))
    logits = -np.column_stack([rdm[triplets[:, a], triplets[:, b]] for a, b in pairs]) / temperature
    shifted = logits - logits.max(axis=1, keepdims=True)
    return np.log(np.exp(shifted).sum(axis=1)) - shifted[:, 0]


def neural_scores(models, neural, indices):
    import numpy as np
    first = np.stack([rank_unit(vector(rdm, indices)) for rdm in models])
    second = np.stack([rank_unit(vector(rdm, indices)) for rdm in neural])
    return first @ second.T


def compute(packet, plan):
    import numpy as np
    a, meta, spec = packet['arrays'], packet['metadata'], packet['protocol']
    parts = validate_partitions(meta, [.4, .3, .3], spec['split_seed'])
    triplets, split = a['triplets'], a['triplet_partition']
    n = len(meta['concept_ids'])
    if triplets.ndim != 2 or triplets.shape[1] != 3 or triplets.dtype.kind not in 'iu' or triplets.min() < 0 or triplets.max() >= n:
        raise ExpansionError('triplet identities invalid')
    if a['neural_rdms'].shape != (len(meta['subjects']), n, n) or a['features'].shape[:2] != (len(meta['candidates']), n):
        raise ExpansionError('candidate/neural identity shape differs')
    if split.shape != (len(triplets),) or not np.isin(split, [0, 1, 2]).all():
        raise ExpansionError('invalid behavior split')
    for i, part in enumerate(parts):
        if np.sum(split == i) < 5 or not np.isin(triplets[split == i], part).all():
            raise ExpansionError('behavior concept leakage or insufficient data')
    models = np.stack([distance(x) for x in a['features']])
    temperatures, losses = [], []
    for rdm in models:
        scores = [negative_log_likelihood(rdm, triplets[split == 0], t).mean() for t in spec['temperature_grid']]
        temperature = spec['temperature_grid'][int(np.argmin(scores))]
        temperatures.append(temperature)
        losses.append(negative_log_likelihood(rdm, triplets, temperature))
    losses = np.stack(losses)
    neural = np.stack([neural_scores(models, a['neural_rdms'], indices) for indices in parts], axis=2)
    means = np.stack([losses[:, split == i].mean(axis=1) for i in range(3)], axis=1)
    first, second = plan['candidate_pair']
    contrasts = {}
    for i in (1, 2):
        brain_delta = float(neural[first, :, i].mean() - neural[second, :, i].mean())
        behavior_delta = float(means[second, i] - means[first, i])  # positive favors first.
        delete_one = []
        for concept in parts[i]:
            remaining = parts[i][parts[i] != concept]
            selected_trials = (split == i) & ~(triplets == concept).any(axis=1)
            if selected_trials.sum() < 1:
                raise ExpansionError('cannot compute concept jackknife with empty trials')
            scores = neural_scores(models, a['neural_rdms'], remaining).mean(axis=1)
            delete_one.append([scores[first] - scores[second],
                               (losses[second, selected_trials] - losses[first, selected_trials]).mean()])
        jack = np.asarray(delete_one)
        se = np.sqrt((len(jack) - 1) / len(jack) * ((jack - jack.mean(axis=0)) ** 2).sum(axis=0))
        relation = 'same_direction' if brain_delta * behavior_delta > 0 else 'opposite_direction' if brain_delta * behavior_delta < 0 else 'tie'
        contrasts[spec['partitions'][i]] = {'neural_first_minus_second': brain_delta, 'behavior_second_minus_first_nll': behavior_delta,
                                          'concept_jackknife_se': se.tolist(), 'descriptive_ranking': relation}
    summary = {'candidates': meta['candidates'], 'partitions': spec['partitions'], 'temperatures': temperatures,
               'neural_rsa': neural.mean(axis=1).tolist(), 'behavior_nll': means.tolist(),
               'trial_counts': [int(np.sum(split == i)) for i in range(3)], 'contrasts': contrasts,
               'matching': meta['matching'], 'candidate_scope': meta['candidate_scope']}
    conclusion = {'confirmation_ranking': contrasts['confirmation']['descriptive_ranking'],
                  'ranking_equivalence_established': False, 'population_dissociation_established': False,
                  'same_person_correlation_tested': False, 'image_level_feature_matching': False,
                  'scope': 'fixed_concept_label_representations_observed_cohorts'}
    return summary, {'concept_ids': np.asarray(meta['concept_ids']), 'triplet_nll': losses, 'neural_rsa': neural}, conclusion
