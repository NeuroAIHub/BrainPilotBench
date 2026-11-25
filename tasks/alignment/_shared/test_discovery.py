"""Offline L1/L3 contracts, nonlinear path interventions and separation of confirmation data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np

from discovery import cells, paths, prepare_packet, reference, workflow
from discovery.path_model import PathModel
from multiscale.circuits import head_paths
from multiscale.model import LanguageModel
from real_brainscore.common import read_json, write_json
from unit_transfer.session import record


def cell_fixture(root):
    spec = {'task': cells.PROTOCOL, 'primary_metric': cells.METRIC, 'unit': cells.UNIT, 'domains': list(range(9)),
            'cells': ['a', 'b'], 'model': {'id': 'tiny', 'layers': 2, 'width': 4}}
    rng = np.random.default_rng(53)
    with prepare_packet(root, spec, cells.Packet) as temp:
        for i, split in enumerate(cells.PARTS):
            dest = temp / ('public' if i == 0 else 'owner/' + split)
            domain = np.tile(np.arange(9), 3)
            units = rng.normal(size=(len(domain), 2, 4))
            units[:, 0, 0] = domain
            units[:, 1, 1] = -domain
            units[:, 1, 3] = 0
            trials = np.asarray([(c, 100*i + j//9, int(d)) for c in range(2) for j, d in enumerate(domain)])
            rates = np.concatenate((domain, -domain)).astype('float64')
            write_json(dest / 'words.json', {'words': [f'{split}-{j}' for j in range(len(domain))],
                                             'domains': domain.tolist()})
            for name, arr in [('units', units), ('trials', trials), ('rates', rates)]:
                np.save(dest / (name + '.npy'), arr, allow_pickle=False)
    return cells.Packet(root)


def tiny_model(family):
    import torch
    from transformers import GPT2Config, GPT2LMHeadModel, LlamaConfig, LlamaForCausalLM
    torch.set_num_threads(1)
    torch.manual_seed(18)
    if family == 'gpt2':
        config = GPT2Config(n_positions=16, n_layer=3, n_head=4, n_embd=16, n_inner=24, vocab_size=64)
        model = GPT2LMHeadModel(config)
    else:
        config = LlamaConfig(max_position_embeddings=16, num_hidden_layers=3, num_attention_heads=4,
                             num_key_value_heads=2, hidden_size=16, intermediate_size=24, vocab_size=64)
        model = LlamaForCausalLM(config)
    return PathModel(model.eval(), 63)


def pairs(n, start=0):
    records = []
    for i in range(start, start + n):
        prefix = [1, (i % 33) + 3, 41, 43] if i % 2 == 0 else [1, (i % 33) + 3, 41]
        rev = [prefix[0], *prefix[:0:-1]]
        target = 48 + i % 10
        records.append({'id': f's{i}', 'condition': 'D' if i % 2 == 0 else 'S',
                        'clean_ids': [*prefix, target], 'corrupt_ids': [*rev, target]})
    return records


def path_fixture(root, engine):
    spec = {'task': paths.PROTOCOL, 'primary_metric': paths.METRIC, 'unit': paths.UNIT,
            'units_per_path': 8, 'heads': engine.heads, 'training_folds': 2,
            'model': {'id': 'tiny', 'layers': engine.layers, 'width': engine.width},
            'layer_pairs': [list(v) for v in engine.pairs]}
    train = pairs(12)
    rng = np.random.default_rng(29)
    with prepare_packet(root, spec, paths.Packet) as temp:
        for name, records in [('public', train), ('owner/dev', pairs(8, 12)), ('owner/test', pairs(8, 20))]:
            write_json(temp / name / 'pairs.json', records)
        engine.training(train, temp / 'public', 3, 2)
        np.save(temp / 'public/brain.npy', rng.normal(size=(12, 3)))
        np.save(temp / 'owner/test/brain.npy', rng.normal(size=(8, 2)))
        write_json(temp / 'owner/test/participants.json', ['p', 'q'])
    packet = paths.Packet(root)
    packet.engine = engine
    return packet


class DiscoveryTests(unittest.TestCase):
    def test_probe_word_uses_final_subtoken_even_with_separate_whitespace(self):
        def tokenizer(text, **kwargs):
            self.assertEqual(text, 'I heard hummingbird today.')
            return {'input_ids': list(range(7)), 'offset_mapping': [(0, 1), (2, 7), (8, 15), (15, 19),
                                                                     (19, 20), (20, 25), (25, 26)]}
        entry = cells.word_entry(tokenizer, 'hummingbird', 'I heard {word} today.')
        self.assertEqual(entry['ids'][entry['start'] - 1], 3)

    def test_fixed_panel_uses_only_training_responses(self):
        import pandas as pd
        ids = np.repeat(np.arange(80), 9)
        domain = np.tile(np.arange(9), 80)
        fixed = cells.partition(list(map(int, ids)), 'trial')
        frame = pd.DataFrame({'trial_ID': ids, 'domain_w2v': domain, 'trial_type': 'sentence', 'fr': domain})
        noisy = frame.assign(fr=0.)
        source = {0: frame, 1: noisy}
        with patch.object(cells, 'source_table', return_value=source):
            names, reliability, before = cells.human_splits(None)
            self.assertEqual(names, ['cell_0'])
            self.assertAlmostEqual(reliability[0], 1.)
            hidden = ~frame.trial_ID.isin(fixed['public'])
            frame.loc[hidden, 'fr'] = -frame.loc[hidden, 'fr']
            noisy.loc[hidden, 'fr'] = domain[hidden]
            after_names, after_r, after = cells.human_splits(None)
            self.assertEqual((names, reliability), (after_names, after_r))
            np.testing.assert_array_equal(before['public'][1], after['public'][1])
            self.assertFalse(np.array_equal(before['test'][1], after['test'][1]))

    @patch.dict(os.environ, {'BPB_SUBMISSION_ISOLATION': 'process', 'BPB_ALIGNMENT_TRUSTED_LOCAL': '1'})
    def test_cell_scores_nulls_budgets_and_replay(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = cell_fixture(root / 'packet')
            best = reference.select(packet.root / 'public')
            self.assertEqual(best['mapping'], {'a': {'layer': 0, 'unit': 0}, 'b': {'layer': 1, 'unit': 1}})
            self.assertAlmostEqual(packet.scores('test', best)['unit_tuning_r'], 1.)
            other = deepcopy(best)
            other['mapping']['a'] = {'layer': 1, 'unit': 1}
            self.assertAlmostEqual(packet.scores('test', other)['unit_tuning_r'], 0.)
            bad = deepcopy(other)
            bad['mapping']['b']['unit'] = 3
            self.assertIsNone(packet.scores('test', bad)['unit_tuning_r'])
            q = record(packet, 'test', best)
            self.assertEqual(set(q), {'choice', 'query', 'dev_score'})
            self.assertEqual(record(packet, 'test', {**best, 'predicted_score': -.8}), q)
            self.assertEqual(record(packet, 'test', other)['query'], 2)
            with self.assertRaisesRegex(ValueError, 'budget'):
                record(packet, 'test', bad)
            for invalid in [{**best, 'mapping': {}}, {**best, 'packet_sha256': ''}, {**best, 'predicted_score': 1.1}]:
                with self.assertRaises(ValueError):
                    packet.choice(invalid)
            result = workflow.grade(packet, 'test', best, Path(reference.__file__))
            self.assertTrue(result['replay']['verified'])
            self.assertAlmostEqual(result['results']['agent']['scores']['gain_over_train_top'], 0.)
            with self.assertRaisesRegex(ValueError, 'different submission'):
                workflow.grade(packet, 'test', other, Path(reference.__file__))
            workflow.stage(cells, packet, root / 'task', 'other')
            self.assertFalse((root / 'task/public/owner').exists())
            self.assertFalse((root / 'task/solution').exists())

    def test_exact_gpt2_path_matches_old_independent_implementation(self):
        engine = tiny_model('gpt2')
        records = pairs(7)
        path = {'sender_layer': 0, 'receiver_layer': 2, 'head': 2, 'units': list(range(8))}
        lm = LanguageModel.__new__(LanguageModel)
        lm.model = engine.model
        lm.tokenizer = SimpleNamespace(eos_token_id=63)
        def entries(field):
            return [{'ids': p[field], 'start': len(p[field]) - 1} for p in records]
        expected, gap = head_paths(lm, entries('clean_ids'), entries('corrupt_ids'), path['units'], 0, 2, 3)
        values, actual_gap, intact, cut = engine.effects(records, path, 3, cut=True)
        np.testing.assert_allclose(values, expected, atol=1e-6)
        np.testing.assert_allclose(actual_gap, gap, atol=1e-6)
        self.assertGreater(np.max(np.abs(intact - cut)), 0.)

    def test_llama_query_heads_gated_mlp_and_zero_intervention(self):
        import torch
        engine = tiny_model('llama')
        records = pairs(7)
        path = {'sender_layer': 0, 'receiver_layer': 2, 'head': 3, 'units': list(range(8))}
        effect, _, intact, cut = engine.effects(records, path, 3, cut=True)
        self.assertEqual(effect.shape, (7, 4))
        self.assertGreater(np.abs(effect).max(), 1e-7)
        self.assertGreater(np.max(np.abs(intact - cut)), 0.)
        same = [{**r, 'corrupt_ids': r['clean_ids']} for r in records]
        np.testing.assert_allclose(engine.effects(same, path, 3)[0], 0., atol=1e-6)
        with torch.no_grad():
            engine.down[2].weight[:, path['units']] = 0.
        np.testing.assert_allclose(engine.effects(records, path, 3)[0], 0., atol=1e-6)

    @patch.dict(os.environ, {'BPB_SUBMISSION_ISOLATION': 'process', 'BPB_ALIGNMENT_TRUSTED_LOCAL': '1'})
    def test_path_contract_replay_marginal_gain_and_brain_readout(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = tiny_model('llama')
            packet = path_fixture(root / 'packet', engine)
            best = reference.select(packet.root / 'public')
            path = best['path']
            for invalid in [{**path, 'receiver_layer': path['sender_layer']},
                            {**path, 'head': 4}, {**path, 'units': [False] + list(range(1, 8))}]:
                with self.assertRaises(ValueError):
                    packet.query_choice({**best, 'path': invalid})
            with self.assertRaisesRegex(ValueError, 'falsifier'):
                packet.choice({**best, 'falsifier': ''})
            with patch.object(packet, 'pairs', {'public': packet.pairs['public']}):
                probe = record(packet, 'test', best, training=True)
            self.assertEqual(set(probe), {'probe', 'choice', 'train_score', 'fold_gains'})
            self.assertAlmostEqual(probe['train_score'], np.mean(probe['fold_gains']), places=6)
            for head in range(3):
                record(packet, 'test', {**best, 'path': {**path, 'head': head}}, training=True)
            self.assertEqual(record(packet, 'test', best, training=True), probe)
            q = record(packet, 'test', best)
            self.assertEqual(q['query'], 1)
            same = {**best, 'path': {**path, 'units': path['units'][::-1]}, 'falsifier': 'other', 'predicted_score': -2.}
            self.assertEqual(record(packet, 'test', same), q)
            self.assertEqual(set(q), {'query', 'choice', 'dev_score'})
            raw = engine.effects(packet.pairs['dev'], path, 3)[0]
            expected = (raw[:, path['head']] - np.delete(raw, path['head'], axis=1).mean(axis=1)).mean()
            self.assertAlmostEqual(q['dev_score'], expected, places=6)
            strategy = root / 'strategy.py'
            strategy.write_text('import json, sys\nfrom pathlib import Path\n'
                                'train = json.loads(Path("training_feedback.json").read_text())\n'
                                'dev = json.loads(Path(sys.argv[2]).read_text())\n'
                                'assert train[0]["choice"] == dev[0]["choice"] and len(train) >= 3\n'
                                'result = dict(train[0]["choice"])\n'
                                'result.update(predicted_score=0.0, falsifier=' + repr(best['falsifier']) + ')\n'
                                'print(json.dumps(result))\n')
            result = workflow.grade(packet, 'test', best, strategy)
            self.assertEqual(result['freeze']['training_feedback'][0], probe)
            scores = result['results']['agent']['scores']
            self.assertEqual(len(scores['brain_cells']), 4)
            self.assertAlmostEqual(scores['brain_delta_r'], np.mean([c['intact_r'] - c['cut_r'] for c in scores['brain_cells']]))
            with self.assertRaisesRegex(ValueError, 'frozen'):
                record(packet, 'test', same)
            with self.assertRaisesRegex(ValueError, 'frozen'):
                record(packet, 'test', same, training=True)
            workflow.stage(paths, packet, root / 'task', 'other')
            inventory = set(p.name for p in (root / 'task/public').iterdir())
            self.assertEqual(inventory, {'protocol.json','manifest.json','brain.npy','pairs.json','training_gain_proxy.npy','train_units.npy'})

    def test_slow_inference_cannot_publish_a_probe_after_freeze(self):
        with TemporaryDirectory() as tmp:
            packet = cell_fixture(Path(tmp) / 'packet')
            pick = reference.select(packet.root / 'public')
            started, release = Event(), Event()
            def slow(selection):
                started.set()
                if not release.wait(timeout=5):
                    raise RuntimeError('freeze blocked on inference')
                return {'dev_score': 1.}
            with patch.object(packet, 'development_feedback', side_effect=slow), ThreadPoolExecutor(1) as pool:
                pending = pool.submit(record, packet, 'parallel', pick)
                try:
                    self.assertTrue(started.wait(timeout=5))
                    frozen = record(packet, 'parallel', pick, 'source-digest')
                    self.assertEqual(frozen['feedback'], [])
                finally:
                    release.set()
                with self.assertRaisesRegex(ValueError, 'frozen'):
                    pending.result(timeout=5)

    def test_fixed_readout_keeps_sign_and_condition(self):
        rng = np.random.default_rng(173)
        train, test = rng.normal(size=(36, 1)), rng.normal(size=(16, 1))
        labels = np.asarray(['D', 'S'] * 8)
        measured = np.column_stack((test[:, 0], test[:, 0])) + (labels == 'D')[:, None] * 100
        result = paths.brain_effect(train, train, test, -test, measured, labels)
        self.assertAlmostEqual(result['brain_delta_r'], 2.)
        measured[:, 1] = 0.
        self.assertIsNone(paths.brain_effect(train, train, test, -test, measured, labels)['brain_delta_r'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
