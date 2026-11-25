"""Build fixed, stimulus-aligned cohorts from the two original data files."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from expansion.selection import response_pool, stimulus_id
from incremental.protocol import group_folds
from multiscale import CSV_SHA256
from multiscale.networks import ROIS, search_halves
from real_brainscore.common import read_json, seal, sha256, write_json
from . import ALPHA, CONTROLS, INSPECTIONS, K, POSITIONS, PROTOCOL
from .features import load_local, write_features


@dataclass
class Cohort:
    ids: list
    texts: list
    subjects: list
    labels: list
    y: np.ndarray
    passages: list | None = None


def tuckute(path):
    if sha256(path) != CSV_SHA256:
        raise ValueError('Tuckute participant CSV differs from the source lock')
    pool = response_pool(path)
    m = pool.metadata
    train = Cohort(m['train_ids'], m['train_sentences'], m['train_subjects'], ['B'] * len(pool.train), pool.train)
    ids, texts, labels = m['candidate_ids'], m['candidate_sentences'], np.asarray(pool.conditions)
    if list(pool.held_subjects) != [797, 841, 880]:
        raise ValueError('unexpected search participants')
    dev_rows, test_rows = search_halves(ids, labels)

    def search(rows, cols):
        return Cohort([ids[i] for i in rows], [texts[i] for i in rows], [str(pool.held_subjects[j]) for j in cols],
                      labels[rows].tolist(), pool.hidden[np.ix_(rows, cols)])

    frame = pd.read_csv(path, usecols=['roi', 'cond_approach', 'item_id', 'target_UID', 'response_target', 'sentence', 'cond'])
    frame = frame[(frame.roi == 'lang_LH_netw') & frame.cond_approach.isin(['D_modify', 'S_modify'])]
    table = frame.pivot(index='item_id', columns='target_UID', values='response_target').sort_index()
    items = frame.drop_duplicates('item_id').set_index('item_id').loc[table.index]
    modify = Cohort([stimulus_id(i) for i in table.index], items.sentence.str.strip().tolist(),
                    list(map(str, table.columns)), items.cond.tolist(), table.to_numpy())
    groups = {'train': train, 'dev': search(dev_rows, [0]), 'search': search(test_rows, [1, 2]), 'modify': modify}
    if [c.y.shape for c in groups.values()] != [(988, 5), (250, 1), (250, 2), (500, 2)]:
        raise ValueError('unexpected Tuckute coverage')
    for name in ('ids', 'texts', 'subjects'):
        values = [v for cohort in groups.values() for v in getattr(cohort, name)]
        if len(values) != len(set(values)):
            raise ValueError(f'overlapping Tuckute {name}')
    for cohort in list(groups.values())[1:]:
        if any(cohort.labels.count(label) != len(cohort.ids) // 2 for label in ('D', 'S')):
            raise ValueError('unbalanced Tuckute conditions')
    return groups


def pereira(path):
    import h5py

    locks = read_json(Path(__file__).resolve().parents[2] / 'brainscore/source-assets.json')
    assets = next(s['assets'] for s in locks['sources'] if s['source_id'] == 'pereira2018')
    expected = next(a['sha1'] for a in assets if a['kind'] == 'data_only_assembly')
    with open(path, 'rb') as f:
        if hashlib.file_digest(f, 'sha1').hexdigest() != expected:
            raise ValueError('Pereira assembly differs from the source lock')
    with h5py.File(path, 'r') as f:
        rows = np.flatnonzero(f['experiment'].asstr()[:] == '384sentences')
        ids, texts, stories, passages = [f[k].asstr()[:][rows] for k in ('stimulus_id', 'stimulus', 'story', 'passage_label')]
        people = f['subject'].asstr()[:]
        regions = f['roi'].asstr()[:]
        raw = f['data'][rows, :]
    if len(set(ids)) != 384 or len(set(passages)) != 96:
        raise ValueError('unexpected Pereira384 stimulus identities')
    fit, test = group_folds(stories, 5, 41)[0]
    if set(passages[fit]) & set(passages[test]):
        raise ValueError('Pereira passage crosses the holdout')
    # Include columns measured in the training materials. Within each person,
    # average the same language voxels on every training and held-out sentence.
    keep = np.isin(regions, [r.removeprefix('lang_') for r in ROIS]) & np.isfinite(raw[fit]).all(axis=0)
    if not np.isfinite(raw[:, keep]).all():
        raise ValueError('incomplete measurements for Pereira training voxels')
    subjects = sorted(set(people[keep]))
    if len(subjects) != 9:
        raise ValueError('unexpected Pereira384 subject coverage')
    y = np.column_stack([raw[:, keep & (people == s)].mean(axis=1, dtype='float64') for s in subjects])

    def subset(indices):
        return Cohort(ids[indices].tolist(), texts[indices].tolist(), subjects, ['all'] * len(indices),
                      y[indices], passages[indices].tolist())
    return {'pereira_fit': subset(fit), 'pereira': subset(test)}


def prepare(csv_file, assembly, candidate, model_dir, output, batch_size=16):
    destination = Path(output).expanduser().resolve()
    if destination.exists() or batch_size < 1:
        raise ValueError('use a fresh output directory and a positive batch size')
    groups = {**tuckute(csv_file), **pereira(assembly)}
    if any(not np.isfinite(c.y).all() for c in groups.values()):
        raise ValueError('nonfinite participant responses')
    model, tokenizer, binding = load_local(candidate, model_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as tmp:
        root = Path(tmp) / 'packet'
        root.mkdir(mode=0o700)
        for name, cohort in groups.items():
            part = root / 'public' if name == 'train' else root / 'owner' / name
            part.mkdir(parents=True)
            write_features(part, cohort.texts, model, tokenizer, batch_size)
            np.save(part / 'responses.npy', cohort.y, allow_pickle=False)
            write_json(part / 'items.json', {'ids': cohort.ids, 'texts': cohort.texts, 'subjects': cohort.subjects,
                                             'conditions': cohort.labels, 'passages': cohort.passages})
        protocol = {'task': PROTOCOL, 'model': binding, 'positions': list(POSITIONS), 'n_units': K,
                    'controls': list(CONTROLS), 'alpha': ALPHA, 'dev_queries': INSPECTIONS,
                    'primary_metric': 'mean signed within-condition, within-subject search delta_r',
                    'tuckute_sha256': CSV_SHA256, 'pereira_sha256': sha256(assembly)}
        write_json(root / 'public/protocol.json', protocol)
        seal(root / 'public', {'schema': PROTOCOL + '/public'})
        identity = sha256(root / 'public/manifest.json')
        seal(root / 'owner', {'schema': PROTOCOL + '/owner', 'public_sha256': identity})
        from .scoring import Packet
        Packet(root).check_controls()
        root.rename(destination)
    return {'root': str(destination), 'packet_sha256': identity, 'model': candidate,
            'cohorts': {k: list(v.y.shape) for k, v in groups.items()}}
