"""Prepare subject- and sentence-disjoint Tuckute packets for regional edge scoring."""
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from expansion.selection import response_pool, stimulus_id
from multiscale import CSV_SHA256, INSPECTIONS, K, POSITIONS
from multiscale.networks import EDGES, ROIS, search_halves
from real_brainscore.common import seal, sha256, write_json
from unit_transfer.features import load_local, write_features
from . import METRIC, PROTOCOL


@dataclass
class Cohort:
    items: dict
    responses: np.ndarray


def cohorts(csv_file):
    if sha256(csv_file) != CSV_SHA256:
        raise ValueError('Tuckute participant CSV differs from the source lock')
    pool = response_pool(csv_file)
    meta = pool.metadata
    if list(pool.held_subjects) != [797, 841, 880]:
        raise ValueError('unexpected search participants')
    columns = ['target_UID', 'item_id', 'roi', 'cond', 'session_id', 'run_id', 'response_target']
    frame = pd.read_csv(csv_file, usecols=columns)
    frame = frame[frame.roi.isin(ROIS)].copy()
    frame['sid'] = frame.item_id.map(stimulus_id)
    wide = frame.pivot(index=['target_UID', 'sid', 'cond', 'session_id', 'run_id'],
                       columns='roi', values='response_target')[ROIS]

    def cohort(ids, texts, conditions, subjects):
        responses, runs = [], []
        for subject in subjects:
            table = wide.loc[int(subject)].reset_index().set_index('sid', verify_integrity=True).loc[ids]
            if table.cond.tolist() != conditions or table[['session_id', 'run_id']].isna().any().any():
                raise ValueError('misaligned condition or scan identifiers')
            runs.append((table.session_id.astype(str) + '/' + table.run_id.astype(str)).tolist())
            responses.append(table[ROIS].to_numpy(dtype='float64'))
        y = np.stack(responses, axis=1)
        if not np.isfinite(y).all():
            raise ValueError('incomplete five-region responses')
        return Cohort({'ids': ids, 'texts': texts, 'conditions': conditions, 'subjects': list(map(str, subjects)),
                       'runs': np.asarray(runs).T.tolist()}, y)

    train = cohort(meta['train_ids'], meta['train_sentences'], ['B'] * len(pool.train), meta['train_subjects'])
    ids, texts, labels = meta['candidate_ids'], meta['candidate_sentences'], np.asarray(pool.conditions)
    dev, test = search_halves(ids, labels, split_key=PROTOCOL)

    def held(rows, subjects):
        return cohort([ids[i] for i in rows], [texts[i] for i in rows], labels[rows].tolist(), subjects)

    parts = {'public': train, 'dev': held(dev, pool.held_subjects[:1]), 'test': held(test, pool.held_subjects[1:])}
    if [p.responses.shape for p in parts.values()] != [(988, 5, 5), (250, 1, 5), (250, 2, 5)]:
        raise ValueError('unexpected Tuckute population')
    return parts


def prepare(csv_file, candidate, model_dir, output, batch_size=16):
    destination = Path(output).expanduser().resolve()
    if destination.exists() or batch_size < 1:
        raise ValueError('use a fresh output directory and a positive batch size')
    parts = cohorts(csv_file)
    model, tokenizer, binding = load_local(candidate, model_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as tmp:
        root = Path(tmp) / 'packet'
        root.mkdir(mode=0o700)
        for name, part in parts.items():
            folder = root / 'public' if name == 'public' else root / 'owner' / name
            folder.mkdir(parents=True)
            write_features(folder, part.items['texts'], model, tokenizer, batch_size)
            np.save(folder / 'responses.npy', part.responses, allow_pickle=False)
            write_json(folder / 'items.json', part.items)
        write_json(root / 'public/protocol.json', {
            'task': PROTOCOL, 'model': binding, 'primary_metric': METRIC, 'rois': ROIS,
            'edges': [[ROIS[i], ROIS[j]] for i, j in EDGES], 'positions': list(POSITIONS),
            'units_per_roi': K, 'dev_queries': INSPECTIONS, 'source_sha256': CSV_SHA256,
        })
        seal(root / 'public', {'schema': PROTOCOL + '/public'})
        identity = sha256(root / 'public/manifest.json')
        seal(root / 'owner', {'schema': PROTOCOL + '/owner', 'public_sha256': identity})
        from .scoring import Packet
        Packet(root)
        root.rename(destination)
    return {'root': str(destination), 'model': candidate, 'packet_sha256': identity,
            'cohorts': {name: list(p.responses.shape) for name, p in parts.items()}}
