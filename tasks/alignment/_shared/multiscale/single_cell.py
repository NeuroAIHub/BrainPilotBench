"""L1. Match one human cell's semantic tuning to one native MLP unit."""
from collections import Counter
import hashlib
import io
from pathlib import Path
from urllib.request import urlopen

import numpy as np

from . import fingerprint
from .analysis import pearson
from .model import LanguageModel, encode

# The authors release these two tables as Python objects. Decode only these exact files.
JAMALI = {
    'jamali-cells.pickle': ('47389075', 1867230, '8ef82919d47631f449d2612601bc300d990571c07c2b09d0e04efc800a5498a0'),
    'jamali-domains.pickle': ('47389087', 943013, 'eabfd20d3faca13ce5d2adb00d008eb23c5c91891a16d0d26d1311801dce89d2'),
}


def checked_bytes(raw, name):
    _, size, digest = JAMALI[name]
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Jamali source differs: ' + name)
    return raw


def fetch(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    for name, (file_id, size, _) in JAMALI.items():
        path = root / name
        if path.exists():
            checked_bytes(path.read_bytes(), name)
            continue
        with urlopen('https://ndownloader.figshare.com/files/' + file_id, timeout=90) as response:
            raw = checked_bytes(response.read(size + 1), name)
        with path.open('xb') as stream:
            stream.write(raw)
    return list(JAMALI)


def tuning(values, labels, mask):
    return np.stack([values[mask & (labels == domain)].mean(axis=0) for domain in range(9)])


def source_table(directory, name):
    import pandas as pd
    raw = checked_bytes((Path(directory) / name).read_bytes(), name)
    return pd.read_pickle(io.BytesIO(raw))


def unit_task(directory, model_dir):
    cells = source_table(directory, 'jamali-cells.pickle')
    lexicon, _ = source_table(directory, 'jamali-domains.pickle')
    # The source neuron index is fixed in advance, independent of selectivity and reliability.
    trials = cells[1].dropna(subset=['fr', 'domain_w2v', 'trial_ID'])
    trials = trials[trials.trial_type == 'sentence']
    trial_ids = trials.trial_ID.astype(int).to_numpy()
    ordered = sorted(set(trial_ids.tolist()), key=lambda i: fingerprint(['L1-trial', i]))
    train_neural = np.isin(trial_ids, ordered[:2 * len(ordered) // 3])
    labels, rates = trials.domain_w2v.to_numpy(), trials.fr.to_numpy()
    if any(min(Counter(labels[part]).get(d, 0) for d in range(9)) < 2 for part in (train_neural, ~train_neural)):
        raise ValueError('insufficient domain coverage in independent sentence trials')
    human = [tuning(rates, labels, mask) for mask in (train_neural, ~train_neural)]

    words = sorted(lexicon)
    domains = np.asarray([lexicon[w] for w in words])
    train_words = np.zeros(len(words), dtype=bool)
    for d in range(9):
        rows = sorted(np.flatnonzero(domains == d), key=lambda i: fingerprint(['L1-word', words[i]]))
        train_words[rows[:2 * len(rows) // 3]] = True
    lm = LanguageModel(model_dir)
    # Pre1 relative to "today" is the last token of the probed word in this fixed carrier.
    inputs = [encode(lm.tokenizer, 'I heard ' + w + ' today.') for w in words]
    features = lm.features(inputs)[0][:, :, 0, :]
    curves = [tuning(features, domains, mask) for mask in (train_words, ~train_words)]
    public, private = [], {}
    rng = np.random.default_rng(150)
    for layer in range(features.shape[1]):
        train = curves[0][:, layer, :].astype('float64')
        train -= train.mean(axis=0)
        yc = human[0] - np.mean(human[0])
        denom = np.linalg.norm(train, axis=0) * np.linalg.norm(yc)
        corr = np.divide(yc @ train, denom, out=np.zeros_like(denom), where=denom > 0)
        for u in np.argsort(-corr, kind='stable')[:2]:
            key = f'L{layer}-U{u}'
            examples = np.flatnonzero(train_words)
            order = examples[np.argsort(features[examples, layer, u])]
            public.append({'id': key, 'train_value': float(corr[u]), 'model_tuning': curves[0][:, layer, u].tolist(),
                           'high_words': [words[i] for i in order[-3:][::-1]], 'low_words': [words[i] for i in order[:3]]})
            observed = curves[1][:, layer, u]
            null = [pearson(curves[1][:, layer, r], human[1]) for r in rng.choice(features.shape[-1], 32, replace=False)]
            private[key] = {'value': pearson(observed, human[1]), 'random_unit_mean_r': float(np.mean(null)),
                            'model_tuning': observed.tolist(), 'human_tuning': human[1].tolist(),
                            'model_preferred_domain': int(np.argmax(observed)), 'human_preferred_domain': int(np.argmax(human[1]))}
    facts = {'source': 'Jamali et al. Figshare 26046127 v1', 'source_sha256': [v[2] for v in JAMALI.values()],
             'revision': lm.revision, 'human_cell_id': 1, 'domains': list(range(9)), 'human_training_tuning': human[0].tolist(),
             'words_train_test': [int(train_words.sum()), int((~train_words).sum())],
             'trial_ids_train_test': [int(len(set(trial_ids[mask]))) for mask in (train_neural, ~train_neural)],
             'firing_rate_observations': [int(train_neural.sum()), int((~train_neural).sum())],
             'carrier': 'I heard {word} today.', 'model_read': 'last BPE of the probed word, post GELU'}
    return facts, public, private
