"""L3: free choice of an upstream head and eight native units in any later MLP."""
from functools import cached_property
from itertools import combinations
import os
from pathlib import Path

import numpy as np

from expansion.selection import response_pool
from multiscale import CSV_SHA256, INSPECTIONS, K, fingerprint
from multiscale.analysis import checked_units, pearson, readout
from multiscale.model import WORD, encode
from real_brainscore.common import read_json, sha256, write_json
from unit_transfer.features import load_local
from . import SelectionPacket, index, prepare_packet
from .path_model import PathModel

ID = 'alignment-l3-circuit-paths'
PROTOCOL, METRIC, UNIT = ID + '-v1', 'path_specific_gain', 'nat'
CATEGORY, CLI = 'alignment-circuit-paths', 'circuit_paths_cli.py'
TITLE, MEASUREMENT = '注意力头到 MLP 的直接路径', 'l3-measurement.json'
SOURCE_FLAG, SCORE_MINUTES = '--csv', 20
QUESTION = ('选择 path={sender_layer,head,receiver_layer,units}，接收层必须更深，units 是 8 个不同的原生单元。'
            '最终提交另含 falsifier，简述哪项观察会推翻你的路径解释。所有位置在末词首 token 之前。'
            'public/training_gain_proxy.npy 的轴是训练折、层对、发送头、接收单元。它是干预后单元激活变化乘以'
            '乱序句目标 log 概率梯度的折内均值，可自由组合、用折间稳定性检验候选。层对顺序见 protocol.json。'
            'train_units.npy 和 brain.npy 分别是原句各层单元和各参与者的响应。开发及盲测实际恢复选定路径，'
            '可运行 python query.py choice.json --exchange train --timeout 600 在公开训练句上精确干预，返回 train_score 与 fold_gains。'
            '训练探测独立于开发额度，复跑时 training_feedback.json 提供按 probe 顺序的全部训练回执。'
            '主分是所选头相对同层其余头的平均额外目标词 log 概率增益（nat），比较时接收单元相同。'
            '盲测另报在原句切断该头到这组单元后，冻结读出对人脑响应的相关下降。')


def reverse_pair(tokenizer, original):
    """Reverse interior words in their original punctuation slots and verify the token-level control."""
    words = WORD.findall(original['text'])
    if len(words) < 4:
        return None
    order = iter([words[0], *reversed(words[1:-1]), words[-1]])
    text = WORD.sub(lambda _: next(order), original['text'])
    if text == original['text']:
        return None
    reverse = encode(tokenizer, text)
    start = original['start']
    if (reverse['start'] != start or original['ids'][start:] != reverse['ids'][start:]
            or sorted(original['ids']) != sorted(reverse['ids'])):
        return None
    return reverse


def sentence_splits(csv, tokenizer):
    if sha256(csv) != CSV_SHA256:
        raise ValueError('Tuckute CSV differs from the source lock')
    pool = response_pool(csv)
    meta = pool.metadata
    if list(pool.held_subjects) != [797, 841, 880]:
        raise ValueError('unexpected held participant coverage')
    all_text = set(meta['train_sentences'] + meta['candidate_sentences'])
    seen = set()

    def collect(ids, texts, indices, count):
        chosen, rows = [], []
        for i in sorted(indices, key=lambda j: fingerprint([PROTOCOL, ids[j]])):
            original = encode(tokenizer, texts[i])
            reverse = reverse_pair(tokenizer, original)
            if reverse is None or reverse['text'] in all_text:
                continue
            end = original['start'] + 1
            clean_ids, corrupt_ids = original['ids'][:end], reverse['ids'][:end]
            family = {tuple(clean_ids), tuple(corrupt_ids)}
            if len(family) != 2 or family & seen:
                continue
            chosen.append({'id': ids[i], 'original': texts[i], 'reverse': reverse['text'],
                           'clean_ids': clean_ids, 'corrupt_ids': corrupt_ids})
            rows.append(i)
            seen.update(family)
            if len(rows) == count:
                return chosen, rows
        raise ValueError('insufficient distinct token-aligned sentence pairs')

    train, train_rows = collect(meta['train_ids'], meta['train_sentences'], range(len(pool.train)), 64)
    parts = {'public': train, 'dev': [], 'test': []}
    test_rows = []
    for label in ('D', 'S'):
        indices = [i for i, value in enumerate(pool.conditions) if value == label]
        pairs, rows = collect(meta['candidate_ids'], meta['candidate_sentences'], indices, 48)
        for pair in pairs:
            pair['condition'] = label
        parts['dev'].extend(pairs[:16])
        parts['test'].extend(pairs[16:])
        test_rows.extend(rows[16:])
    return parts, pool.train[train_rows], pool.hidden[test_rows, 1:], list(map(str, pool.held_subjects[1:]))


def prepare(source, model_id, model_dir, destination, batch_size):
    model, tokenizer, binding = load_local(model_id, model_dir)
    parts, y_train, y_test, subjects = sentence_splits(source, tokenizer)
    engine = PathModel(model, tokenizer.eos_token_id)
    folds = 4
    protocol = {'task': PROTOCOL, 'primary_metric': METRIC, 'unit': UNIT, 'model': binding,
                'layer_pairs': [list(p) for p in engine.pairs], 'heads': engine.heads, 'units_per_path': K,
                'dev_queries': INSPECTIONS, 'source_sha256': CSV_SHA256, 'training_folds': folds,
                'proxy': 'fold mean of gradient of corrupt target logp times exact direct-path change of one receiving unit',
                'public_probe': 'exact forward interventions on public pairs; returns mean and fold-specific gain',
                'fold_assignment': 'public pair index modulo training_folds', 'prediction_target': 'first token of final word'}
    with prepare_packet(destination, protocol, Packet) as root:
        public = root / 'public'
        for split, pairs in parts.items():
            folder = public if split == 'public' else root / 'owner' / split
            write_json(folder / 'pairs.json', pairs)
        np.save(public / 'brain.npy', y_train, allow_pickle=False)
        np.save(root / 'owner/test/brain.npy', y_test, allow_pickle=False)
        write_json(root / 'owner/test/participants.json', subjects)
        # A relocatable host-only locator. load_local verifies the sealed public model identity before use.
        write_json(root / 'model-location.json', {'directory': str(Path(model_dir).expanduser().resolve())})
        engine.training(parts['public'], public, batch_size, folds)
    return {'root': str(destination), 'model': model_id, 'pairs': {s: len(v) for s, v in parts.items()},
            'packet_sha256': sha256(Path(destination) / 'public/manifest.json')}


def brain_effect(train_x, train_y, intact, cut, test_y, labels):
    """Fit once on intact original training sentences. Apply identical weights to both test signals."""
    n = len(train_x)
    x = np.concatenate((train_x, intact, cut))
    pred = np.asarray(readout(x, train_y.mean(axis=1), np.arange(n), np.arange(n, len(x)))['predictions'])
    intact_pred, cut_pred = np.split(pred, 2)
    cells = []
    for subject in range(test_y.shape[1]):
        for condition in ('D', 'S'):
            use = labels == condition
            r1 = pearson(intact_pred[use], test_y[use, subject])
            r0 = pearson(cut_pred[use], test_y[use, subject])
            cells.append({'subject_index': subject, 'condition': condition, 'intact_r': r1, 'cut_r': r0})
    drops = [c['intact_r'] - c['cut_r'] for c in cells if c['intact_r'] is not None and c['cut_r'] is not None]
    return {'brain_delta_r': float(np.mean(drops)) if len(drops) == len(cells) else None, 'brain_cells': cells}


class Packet(SelectionPacket):
    public_files = {'protocol.json', 'pairs.json', 'train_units.npy', 'brain.npy', 'training_gain_proxy.npy'}
    extra_fields = {'falsifier'}

    def __init__(self, root):
        super().__init__(root, PROTOCOL, METRIC)
        p = self.protocol
        self.layers, self.width = (p['model'][k] for k in ('layers', 'width'))
        layer_pairs = [list(v) for v in combinations(range(self.layers), 2)]
        if (p['unit'] != UNIT or p['units_per_path'] != K or p['heads'] < 2 or p['layer_pairs'] != layer_pairs
                or p['training_folds'] < 1):
            raise ValueError('unexpected path search space')
        self.pairs, seen, seen_ids = {}, set(), set()
        for name in ('public', 'dev', 'test'):
            folder = self.root / ('public' if name == 'public' else 'owner/' + name)
            records = read_json(folder / 'pairs.json')
            for pair in records:
                clean, rev = pair['clean_ids'], pair['corrupt_ids']
                family = {tuple(clean), tuple(rev)}
                if (len(clean) < 2 or len(clean) != len(rev) or clean[-1] != rev[-1] or len(family) != 2
                        or sorted(clean) != sorted(rev) or family & seen or pair['id'] in seen_ids):
                    raise ValueError('overlapping sentence families or misaligned target')
                seen.update(family)
                seen_ids.add(pair['id'])
            if not records or (name != 'public' and {r['condition'] for r in records} != {'D', 'S'}):
                raise ValueError('missing circuit probe conditions')
            self.pairs[name] = records
        public = self.root / 'public'
        self.train_units = np.load(public / 'train_units.npy', mmap_mode='r', allow_pickle=False)
        self.train_y = np.load(public / 'brain.npy', allow_pickle=False)
        self.test_y = np.load(self.root / 'owner/test/brain.npy', allow_pickle=False)
        subjects = read_json(self.root / 'owner/test/participants.json')
        proxy = np.load(public / 'training_gain_proxy.npy', mmap_mode='r', allow_pickle=False)
        n = len(self.pairs['public'])
        if (proxy.shape != (p['training_folds'], len(layer_pairs), p['heads'], self.width) or
                self.train_units.shape != (n, self.layers, self.width) or self.train_y.ndim != 2 or
                self.train_y.shape[0] != n or self.train_y.shape[1] == 0 or not subjects or
                self.test_y.shape != (len(self.pairs['test']), len(subjects)) or len(set(subjects)) != len(subjects)
                or not np.isfinite(self.train_y).all() or not np.isfinite(self.test_y).all()):
            raise ValueError('misaligned public or private path arrays')
        self._test_scores = {}

    @cached_property
    def engine(self):
        directory = os.environ.get('BPB_CIRCUIT_MODEL_DIR') or read_json(self.root / 'model-location.json')['directory']
        model, tokenizer, binding = load_local(self.protocol['model']['id'], directory)
        engine = PathModel(model, tokenizer.eos_token_id)
        if binding != self.protocol['model'] or engine.heads != self.protocol['heads']:
            raise ValueError('scoring model or runtime differs from prepared coefficients')
        return engine

    def query_choice(self, raw):
        path = self.selection(raw, 'path')
        if not isinstance(path, dict) or set(path) != {'sender_layer', 'head', 'receiver_layer', 'units'}:
            raise ValueError('expected sender_layer, head, receiver_layer and units')
        s, r, h = path['sender_layer'], path['receiver_layer'], path['head']
        if not index(s, self.layers) or not index(r, self.layers) or s >= r or not index(h, self.protocol['heads']):
            raise ValueError('invalid head or downstream layer')
        group = checked_units({'layer': r, 'position': 'pre1', 'units': path['units']}, self.layers, self.width)
        return {'packet_sha256': self.identity, 'path': {**path, 'units': group['units']}}

    def choice(self, raw):
        pick = super().choice(raw)
        claim = raw.get('falsifier')
        if not isinstance(claim, str) or not 1 <= len(claim.strip()) <= 500:
            raise ValueError('final path needs a falsifier of at most 500 characters')
        return {**pick, 'falsifier': claim.strip()}

    def training_feedback(self, choice):
        path = choice['path']
        effects, _, _, _ = self.engine.effects(self.pairs['public'], path, batch_size=8)
        gain = effects[:, path['head']] - np.delete(effects, path['head'], axis=1).mean(axis=1)
        folds = self.protocol['training_folds']
        return {'train_score': float(gain.mean()), 'fold_gains': [float(gain[i::folds].mean()) for i in range(folds)]}

    def scores(self, split, choice):
        path = choice['path']
        key = fingerprint(path)
        if split == 'test' and key in self._test_scores:
            return self._test_scores[key].copy()
        effects, gap, intact, cut = self.engine.effects(self.pairs[split], path, batch_size=8, cut=split == 'test')
        head = path['head']
        other = np.delete(effects, head, axis=1).mean(axis=1)
        gain = effects[:, head] - other
        if not np.isfinite(gain).all():
            raise ValueError('nonfinite intervention gain')
        scores = {METRIC: float(gain.mean()), 'patched_logp_gain': float(effects[:, head].mean()),
                  'other_heads_mean': float(other.mean()), 'intact_minus_corrupt_logp': float(gap.mean())}
        if split == 'test':
            train = self.train_units[:, path['receiver_layer'], :][:, path['units']]
            conditions = np.asarray([p['condition'] for p in self.pairs['test']])
            scores.update(brain_effect(train, self.train_y, intact, cut, self.test_y, conditions))
            self._test_scores[key] = scores.copy()
        return scores
