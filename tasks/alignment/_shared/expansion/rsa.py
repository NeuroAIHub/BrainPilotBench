"""Identity-aware RSA primitives; RDM entries are never independent samples."""
import numpy as np
from scipy.stats import rankdata

from . import ExpansionError


def distance(features, center=False):
    x = np.asarray(features, dtype='float64')
    if x.ndim != 2 or not np.isfinite(x).all():
        raise ExpansionError('invalid feature matrix')
    if center:
        x = x - x.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(x, axis=1, keepdims=True)
    if np.any(norm == 0):
        raise ExpansionError('undefined distance for zero feature vector')
    x = x / norm
    return np.clip(1. - x @ x.T, 0., 2.)


def rank_unit(values):
    ranks = rankdata(values, method='average', axis=-1)
    ranks -= ranks.mean(axis=-1, keepdims=True)
    norm = np.linalg.norm(ranks, axis=-1, keepdims=True)
    if np.any(norm == 0):
        raise ExpansionError('undefined RSA for constant RDM')
    return ranks / norm


def vector(rdm, indices):
    sub = rdm[np.ix_(indices, indices)]
    return sub[np.triu_indices(len(indices), 1)]


def partition(ids, proportions, seed):
    if len(set(ids)) != len(ids):
        raise ExpansionError('duplicate concept identities')
    ordered = np.asarray(sorted(ids))
    permutation = np.random.default_rng(seed).permutation(ordered)
    cuts = np.cumsum([int(len(ids) * p) for p in proportions[:-1]])
    parts = np.split(permutation, cuts)
    index = {v: i for i, v in enumerate(ids)}
    return [np.asarray(sorted(index[v] for v in part), dtype='int64') for part in parts]


def validate_partitions(metadata, proportions, seed):
    parts = partition(metadata['concept_ids'], proportions, seed)
    expected = [[metadata['concept_ids'][i] for i in indices] for indices in parts]
    if metadata['partition_concept_ids'] != expected or min(map(len, parts)) < 4:
        raise ExpansionError('concept-disjoint partitions differ or are too small')
    return parts
