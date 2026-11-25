"""Regression coverage for the two hook architectures and the blind evaluation contract."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from real_brainscore.common import seal, sha256, write_json
from unit_transfer import PROTOCOL
from unit_transfer.features import batch_features, projections
from unit_transfer.query import query
from unit_transfer.reference import select
from unit_transfer.scoring import Packet
from unit_transfer.session import grade, record
from unit_transfer.staging import serve_dev, stage


def fixture(directory):
    root = Path(directory) / 'packet'
    rng = np.random.default_rng(40)
    for name in ('train', 'dev', 'search', 'modify', 'pereira_fit', 'pereira'):
        part = root / 'public' if name == 'train' else root / 'owner' / name
        part.mkdir(parents=True)
        x = rng.normal(size=(36, 2, 2, 20)).astype('float32')
        controls = rng.normal(size=(36, 2))
        signal = x[:, 0, 0, 0] + .3 * controls[:, 0]
        y = np.column_stack([signal, signal + .4 * controls[:, 1]])
        if name == 'search':
            y[18:] *= -1
            y[18:] += 20
        labels = ['all'] * len(y) if name.startswith('pereira') else ['D'] * 18 + ['S'] * 18
        write_json(part / 'items.json', {'conditions': labels, 'subjects': ['a', 'b']})
        for key, value in [('units', x), ('responses', y), ('controls', controls)]:
            np.save(part / (key + '.npy'), value, allow_pickle=False)
    write_json(root / 'public/protocol.json', {'model': {'id': 'fixture'}, 'n_units': 8, 'positions': ['pre1', 'pre2']})
    seal(root / 'public', {'schema': PROTOCOL + '/public'})
    seal(root / 'owner', {'schema': PROTOCOL + '/owner', 'public_sha256': sha256(root / 'public/manifest.json')})
    return Packet(root)


class UnitTransferTest(unittest.TestCase):
    def test_channels_match_native_activation_and_padding_independent_controls(self):
        import torch
        from transformers import GPT2Config, GPT2LMHeadModel, LlamaConfig, LlamaForCausalLM

        torch.set_num_threads(1)
        torch.manual_seed(7)
        models = [GPT2LMHeadModel(GPT2Config(n_layer=2, n_embd=16, n_head=2, n_inner=32, vocab_size=64)),
                  LlamaForCausalLM(LlamaConfig(num_hidden_layers=2, hidden_size=16, intermediate_size=32,
                                              num_attention_heads=2, num_key_value_heads=1, vocab_size=64))]
        entries = [{'ids': [1, 6, 2, 4, 8, 9], 'start': 4}, {'ids': [7, 8, 3, 6], 'start': 2}]
        for model in models:
            with self.subTest(family=model.config.model_type), torch.inference_mode():
                model.eval()
                acts, controls = batch_features(model, entries, 0)
                self.assertEqual(acts.shape, (2, 2, 2, 32))
                self.assertEqual(projections(model)[1], 32)
                layer = model.base_model.h[0] if model.config.model_type == 'gpt2' else model.base_model.layers[0]
                mlp = layer.mlp
                captured = []
                hook = mlp.register_forward_pre_hook(lambda module, args: captured.append(args[0]))
                try:
                    for i, entry in enumerate(entries):
                        ids = torch.tensor([entry['ids']])
                        logits = model(ids).logits
                        h = captured[-1]
                        inter = mlp.act(mlp.c_fc(h)) if model.config.model_type == 'gpt2' else mlp.act_fn(mlp.gate_proj(h)) * mlp.up_proj(h)
                        pos = entry['start']
                        np.testing.assert_allclose(acts[i, 0], inter[0, [pos-1, pos-2]].numpy(), atol=1e-6)
                        loss = torch.nn.functional.cross_entropy(logits[0, :-1], ids[0, 1:])
                        np.testing.assert_allclose(controls[i], [ids.shape[1], loss.item()], atol=1e-6)
                finally:
                    hook.remove()

    def test_signed_cells_and_transfer_refit(self):
        with TemporaryDirectory() as tmp:
            packet = fixture(tmp)
            group = {'packet_sha256': packet.identity, 'layer': 0, 'position': 'pre1', 'units': list(range(8))}
            packet.check_controls()
            scores = packet.results(group)
            cells = scores['search']['cells']
            self.assertLess(cells['a']['S']['delta_r'], 0)
            self.assertGreater(cells['a']['D']['delta_r'], 0)
            self.assertEqual(scores['search']['delta_r'], np.mean([c['delta_r'] for p in cells.values() for c in p.values()]))
            original = scores['pereira']
            packet.train.y = -packet.train.y
            self.assertEqual(packet.results(group)['pereira'], original)
            packet.splits['pereira_fit'].y = -packet.splits['pereira_fit'].y
            self.assertAlmostEqual(packet.results(group)['pereira']['delta_r'], -original['delta_r'])
            packet.splits['dev'].y = np.full_like(packet.splits['dev'].y, .1)
            with self.assertRaisesRegex(ValueError, 'variance'):
                packet.check_controls()

    @patch.dict(os.environ, {'BPB_SUBMISSION_ISOLATION': 'process', 'BPB_ALIGNMENT_TRUSTED_LOCAL': '1'})
    def test_public_mailbox_budget_race_and_immutable_source(self):
        with TemporaryDirectory() as tmp:
            packet = fixture(tmp)
            public = packet.root / 'public'
            first = select(public, 'top8')
            second = select(public, 'random')
            third = {**first, 'units': list(range(8))}
            with self.assertRaisesRegex(ValueError, 'different packet'):
                record(packet, 'actor', {**first, 'packet_sha256': 'wrong'})
            with self.assertRaisesRegex(ValueError, 'distinct unit'):
                record(packet, 'actor', {**first, 'units': [0] * 8})
            task = Path(tmp) / 'task'
            stage(packet, task, 'actor')
            self.assertEqual({p.name for p in (task / 'public').iterdir()}, {p.name for p in public.iterdir()})
            self.assertFalse((task / 'owner').exists())
            exchange = Path(tmp) / 'workspace/dev'
            exchange.parent.mkdir()
            with ThreadPoolExecutor(max_workers=2) as workers:
                service = workers.submit(serve_dev, packet, 'actor', exchange, True)
                reply = query(first, exchange, timeout=5)
                service.result(timeout=5)
                self.assertEqual(set(reply), {'query', 'choice', 'dev_delta_r'})
                self.assertEqual(reply, record(packet, 'actor', {**first, 'units': list(reversed(first['units']))}))
                futures = [workers.submit(record, packet, 'actor', choice) for choice in (second, third)]
                failures = [f.exception() for f in futures if f.exception()]
                self.assertEqual(len(failures), 1)
                self.assertIn('budget', str(failures[0]))
            code = Path(tmp) / 'strategy.py'
            code.write_text('import json,sys\nprint(json.dumps(json.load(open(sys.argv[2]))[0]["choice"]))\n')
            result = grade(packet, 'actor', first, code)
            self.assertTrue(result['replay']['verified'])
            self.assertEqual(result, grade(packet, 'actor', first, code))
            self.assertEqual(len(result['freeze']['feedback']), 2)
            with self.assertRaisesRegex(ValueError, 'frozen'):
                record(packet, 'actor', first)
            with self.assertRaisesRegex(ValueError, 'different submission'):
                grade(packet, 'actor', second, code)
            code.write_text('print("{}")')
            with self.assertRaisesRegex(ValueError, 'different submission'):
                grade(packet, 'actor', first, code)
            self.assertEqual(record(packet, 'new-actor', first)['query'], 1)
            with self.assertRaisesRegex(ValueError, 'expected packet_sha256'):
                grade(packet, 'new-actor', first, code)


if __name__ == '__main__':
    unittest.main()
