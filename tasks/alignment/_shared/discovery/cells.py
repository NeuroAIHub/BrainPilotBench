"""L1: select one native model unit per prequalified human cell on Jamali semantic domains."""
from pathlib import Path

import numpy as np

from multiscale import INSPECTIONS, fingerprint
from multiscale.single_cell import JAMALI, source_table
from real_brainscore.common import read_json, sha256, write_json
from unit_transfer.features import batch_features, load_local
from . import SelectionPacket, index, prepare_packet
from .reference import correlations, domain_curves

ID = 'alignment-l1-cell-tuning'
PROTOCOL = ID + '-v1'
METRIC, UNIT = 'unit_tuning_r', 'correlation'
CATEGORY, CLI = 'alignment-cell-tuning', 'cell_tuning_cli.py'
TITLE, MEASUREMENT = '单神经元语义调谐', 'l1-measurement.json'
SOURCE_FLAG, SCORE_MINUTES = '--jamali-dir', 5
QUESTION = ('为每个指定的人类细胞自由选一个模型 MLP 单元。mapping 将每个细胞名映射到 {layer,unit}，从零计数。'
            'units.npy 为词×层×单元，words.json 给出各词的语义域，trials.npy 三列为细胞下标、试次、域，'
            'rates.npy 为对应放电率。双方在九域上分别取均值，盲测按细胞等权平均有符号 Pearson r。')
DOMAINS = 9
PARTS = ('public', 'dev', 'test')


def partition(values, kind):
    ordered = sorted(set(values), key=lambda v: fingerprint([PROTOCOL, kind, v]))
    a, b = 3 * len(ordered) // 5, 4 * len(ordered) // 5
    return dict(zip(PARTS, (ordered[:a], ordered[a:b], ordered[b:])))


def reliability(trials, labels, rates):
    """Training-only median over repeated, whole-trial split halves."""
    ids = np.unique(trials)
    valid = []
    for seed in range(20):
        order = np.random.default_rng(seed).permutation(ids)
        half = np.isin(trials, order[:len(order) // 2])
        curves = []
        for mask in (half, ~half):
            counts = np.bincount(labels[mask], minlength=DOMAINS)
            if counts.min() < 2:
                break
            curves.append(np.bincount(labels[mask], weights=rates[mask], minlength=DOMAINS) / counts)
        if len(curves) == 2 and all(np.ptp(c) > 0 for c in curves):
            valid.append(float(np.corrcoef(curves)[0, 1]))
    return float(np.median(valid)) if len(valid) >= 10 else None


def human_splits(source):
    cells = source_table(source, 'jamali-cells.pickle')
    rows, all_trials = {}, set()
    for key, table in sorted(cells.items()):
        sentences = table.loc[table.trial_type == 'sentence']
        all_trials.update(map(int, sentences.trial_ID.dropna().unique()))
        frame = sentences.dropna(subset=['trial_ID', 'domain_w2v', 'fr'])
        rows[int(key)] = (frame.trial_ID.to_numpy(dtype=int), frame.domain_w2v.to_numpy(dtype=int),
                          frame.fr.to_numpy(dtype='float64'))
    trials = partition(all_trials, 'trial')
    parts = {s: [] for s in PARTS}
    names, stability = [], []
    for key, (ids, labels, rates) in rows.items():
        train = np.isin(ids, trials['public'])
        value = reliability(ids[train], labels[train], rates[train])
        if value is None or value < .30:
            continue
        idx = len(names)
        names.append(f'cell_{key}')
        stability.append(value)
        for s in PARTS:
            mask = np.isin(ids, trials[s])
            obs = np.column_stack((np.full(mask.sum(), idx), ids[mask], labels[mask]))
            parts[s].append((obs, rates[mask]))
    if not names:
        raise ValueError('no cells pass the training reliability criterion')
    return names, stability, {s: (np.concatenate([a for a, _ in records]),
                                  np.concatenate([b for _, b in records])) for s, records in parts.items()}


def word_entry(tokenizer, word, carrier):
    text = carrier.format(word=word)
    begin = carrier.index('{word}')
    end = begin + len(word)
    encoded = tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
    probe = [i for i, (lo, hi) in enumerate(encoded['offset_mapping']) if lo < end and hi > begin]
    if not probe or probe[-1] < 1:
        raise ValueError('probe word lacks a lexical token with context')
    # batch_features reads pre1 at start-1. An independent whitespace token can follow the probe.
    return {'ids': encoded['input_ids'], 'start': probe[-1] + 1}


def prepare(source, model_id, model_dir, destination, batch_size):
    names, stability, responses = human_splits(source)
    lexicon, _ = source_table(source, 'jamali-domains.pickle')
    words = {s: [] for s in PARTS}
    for d in range(DOMAINS):
        for split, group in partition([w for w in lexicon if lexicon[w] == d], 'word').items():
            words[split].extend(group)
    model, tokenizer, binding = load_local(model_id, model_dir)
    protocol = {'task': PROTOCOL, 'primary_metric': METRIC, 'unit': UNIT, 'model': binding, 'cells': names,
                'domains': list(range(DOMAINS)), 'train_split_half_r': stability, 'dev_queries': INSPECTIONS,
                'cell_selection': 'training only, 20 trial splits, at least 10 with >=2 observations/domain/half, median r >= 0.30',
                'source_sha256': {k: v[2] for k, v in JAMALI.items()}, 'carrier': 'I heard {word} today.'}
    with prepare_packet(destination, protocol, Packet) as root:
        for split in PARTS:
            folder = root / ('public' if split == 'public' else 'owner/' + split)
            vocab = words[split]
            write_json(folder / 'words.json', {'words': vocab, 'domains': [int(lexicon[w]) for w in vocab]})
            out = np.lib.format.open_memmap(folder / 'units.npy', mode='w+', dtype='float32',
                                            shape=(len(vocab), binding['layers'], binding['width']))
            for start in range(0, len(vocab), batch_size):
                batch = slice(start, start + batch_size)
                entries = [word_entry(tokenizer, w, protocol['carrier']) for w in vocab[batch]]
                out[batch] = batch_features(model, entries, tokenizer.eos_token_id)[0][:, :, 0]
            out.flush()
            np.save(folder / 'trials.npy', responses[split][0], allow_pickle=False)
            np.save(folder / 'rates.npy', responses[split][1], allow_pickle=False)
    return {'root': str(destination), 'model': model_id, 'cells': len(names),
            'words': {s: len(v) for s, v in words.items()}, 'packet_sha256': sha256(Path(destination) / 'public/manifest.json')}


class Packet(SelectionPacket):
    public_files = {'protocol.json', 'words.json', 'units.npy', 'trials.npy', 'rates.npy'}

    def __init__(self, root):
        super().__init__(root, PROTOCOL, METRIC)
        self.cells = self.protocol['cells']
        if (self.protocol['unit'] != UNIT or self.protocol['domains'] != list(range(DOMAINS)) or
                not self.cells or len(self.cells) != len(set(self.cells))):
            raise ValueError('unexpected L1 protocol')
        self.layers, self.width = (self.protocol['model'][k] for k in ('layers', 'width'))
        self.curves = {}
        seen_words, seen_trials = set(), set()
        for split in PARTS:
            folder = self.root / ('public' if split == 'public' else 'owner/' + split)
            words = read_json(folder / 'words.json')
            vocab, domains = words['words'], np.asarray(words['domains'])
            units = np.load(folder / 'units.npy', mmap_mode='r', allow_pickle=False)
            trials = np.load(folder / 'trials.npy', allow_pickle=False)
            rates = np.load(folder / 'rates.npy', allow_pickle=False)
            if (domains.shape != (len(vocab),) or set(domains) != set(range(DOMAINS))
                    or units.shape != (len(vocab), self.layers, self.width) or trials.shape != (len(rates), 3)
                    or trials.dtype.kind not in 'iu' or rates.ndim != 1 or not np.isfinite(rates).all()
                    or set(trials[:, 0]) != set(range(len(self.cells)))):
                raise ValueError('misaligned word, cell or trial arrays')
            trial_ids = set(trials[:, 1])
            if len(vocab) != len(set(vocab)) or seen_words.intersection(vocab) or seen_trials & trial_ids:
                raise ValueError('overlapping words or human trials')
            seen_words.update(vocab)
            seen_trials.update(trial_ids)
            human = []
            for idx in range(len(self.cells)):
                mask = trials[:, 0] == idx
                labels = trials[mask, 2]
                if set(labels) != set(range(DOMAINS)):
                    raise ValueError('missing semantic domain in fixed human panel')
                human.append(domain_curves(labels, rates[mask]))
            model = domain_curves(domains, units)
            if not np.isfinite(model).all():
                raise ValueError('nonfinite model tuning')
            self.curves[split] = model, human

    def query_choice(self, raw):
        mapping = self.selection(raw, 'mapping')
        if not isinstance(mapping, dict) or set(mapping) != set(self.cells):
            raise ValueError('one assignment per fixed cell is required')
        for site in mapping.values():
            if (not isinstance(site, dict) or set(site) != {'layer', 'unit'}
                    or not index(site['layer'], self.layers) or not index(site['unit'], self.width)):
                raise ValueError('invalid native layer or unit')
        return {'packet_sha256': self.identity, 'mapping': {c: mapping[c] for c in self.cells}}

    def scores(self, split, choice):
        model, human = self.curves[split]
        per_cell, random_layer = {}, []
        for i, cell in enumerate(self.cells):
            site = choice['mapping'][cell]
            rs = correlations(model[:, site['layer']], human[i])
            value = rs[site['unit']]
            per_cell[cell] = float(value) if np.isfinite(value) else None
            good = rs[np.isfinite(rs)]
            random_layer.append(float(good.mean()) if len(good) else None)
        rs = list(per_cell.values())
        primary = None if None in rs else float(np.mean(rs))
        matched = None if None in random_layer else float(np.mean(random_layer))
        return {METRIC: primary, 'per_cell_r': per_cell, 'same_layer_random_r': matched,
                'gain_over_same_layer_random': None if primary is None or matched is None else primary - matched}
