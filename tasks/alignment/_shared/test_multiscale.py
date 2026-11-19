"""Offline checks for the multiscale score, intervention and irreversible stage order."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from expansion.selection import response_pool, stimulus_id
from incremental.analysis import ridge_path
from multiscale import ALPHA
from multiscale.analysis import brain_scores, readout
from multiscale.model import LanguageModel
from multiscale.session import call, history, journal


class MultiscaleTests(unittest.TestCase):
    def test_legacy_f_can_select_sents_without_a_shared_drive_suppress_label(self):
        import pandas as pd
        records = []
        for item in range(22):
            for participant in ((1, 2) if item < 2 else (3, 4)):
                condition = 'B' if item < 2 else ('D' if participant == 3 or item > 2 else 'S')
                records.append({'item_id': item, 'roi': 'lang_LH_netw', 'target_UID': participant,
                                'cond': condition, 'response_target': .1 * participant,
                                'sentence': f'The observer will see item {item}.'})
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / 'responses.csv'
            pd.DataFrame(records).to_csv(source, index=False)
            pool = response_pool(source)
        self.assertEqual(pool.hidden.shape, (20, 2))
        row = pool.metadata['candidate_ids'].index(stimulus_id(2))
        self.assertIsNone(pool.conditions[row])
        self.assertEqual(pool.conditions.count('D'), 19)

    def test_ridge_map_uses_training_scale_and_matches_existing_ridge(self):
        rng = np.random.default_rng(3)
        x = rng.normal(size=(80, 13))
        x[:53, 2] = 4.
        y = rng.normal(size=80)
        train, test = np.arange(53), np.arange(53, 80)
        fitted = readout(x, y, train, test)
        expected = next(ridge_path(x[train], y[train, None], x[test], [ALPHA])).ravel()
        np.testing.assert_allclose(fitted['predictions'], expected, atol=1e-12)
        y[test] += 1000
        self.assertEqual(readout(x, y, train, test), fitted)
        np.testing.assert_allclose(x[test] @ fitted['weights'] + fitted['intercept'], expected, atol=1e-12)

    def test_pooled_and_within_condition_correlations_can_reverse(self):
        ids = list('abcdef')
        identities = {'ids': ids, 'subjects': ['a'], 'conditions': list('DDDSSS')}
        outcomes = np.array([1, 2, 3, 11, 12, 13])[:, None]
        control = {'predictions': [11, 12, 13, 1, 2, 3]}
        select = {'predictions': [3, 2, 1, 13, 12, 11]}
        constant = {'predictions': [1] * 6}
        frozen = {'candidate_ids': ids, 'random_groups': [[2]],
                  'maps': {'control': control, 'selected': select, 'whole': constant, 'random0': control}}
        scores = brain_scores(frozen, identities, outcomes)
        self.assertGreater(scores['all']['subjects']['a']['delta_r'], 1)
        for condition in ('D', 'S'):
            self.assertAlmostEqual(scores[condition]['subjects']['a']['delta_r'], -2)
            self.assertIsNone(scores[condition]['subjects']['a']['whole_delta_r'])
        with self.assertRaises(ValueError):
            brain_scores(frozen, {**identities, 'ids': ids[::-1]}, outcomes)

    def test_outcomes_require_committed_predictions_and_exact_retries(self):
        with TemporaryDirectory() as tmp:
            packet = SimpleNamespace(root=Path(tmp), digest='packet')
            with patch('multiscale.session.perform', return_value=({'valid': True}, None)) as compute:
                with self.assertRaisesRegex(ValueError, 'next required'):
                    call(packet, 'A', 'probe', {})
                call(packet, 'A', 'open', {})
                for stage in ('inspect1', 'inspect2', 'freeze'):
                    call(packet, 'A', stage, {'stage': stage})
                call(packet, 'A', 'freeze', {'stage': 'freeze'})
                with self.assertRaisesRegex(ValueError, 'different parameters'):
                    call(packet, 'A', 'freeze', {'stage': 'changed'})
                with self.assertRaisesRegex(ValueError, 'next required'):
                    call(packet, 'A', 'score', {})
                self.assertEqual(compute.call_count, 4)
                with patch('multiscale.session.perform', side_effect=RuntimeError('interrupted')):
                    with self.assertRaises(RuntimeError):
                        call(packet, 'A', 'probe', {})
                call(packet, 'A', 'probe', {})
            db = journal(packet.root)
            try:
                self.assertEqual(len(history(db, 'A', 'packet')), 5)
                db.execute("UPDATE events SET response='{}' WHERE stage='freeze'")
                db.commit()
                with self.assertRaisesRegex(ValueError, 'digest'):
                    history(db, 'A', 'packet')
            finally:
                db.close()

    def test_last_block_intervention_uses_the_prefix_and_requested_position(self):
        import torch
        from transformers import GPT2Config, GPT2LMHeadModel
        torch.manual_seed(5)
        torch.set_num_threads(1)
        lm = LanguageModel.__new__(LanguageModel)
        lm.model = GPT2LMHeadModel(GPT2Config(n_layer=2, n_head=2, n_embd=12, n_inner=20,
                                            n_positions=16, vocab_size=40)).eval()
        lm.tokenizer = SimpleNamespace(eos_token_id=39)
        entry = {'ids': [4, 8, 12, 16, 20, 24], 'start': 4}
        short = {'ids': [5, 6, 7, 8], 'start': 2}
        units = list(range(20))
        before = lm.target_probabilities([entry, short], 1, 0, [units])
        with torch.inference_mode():
            logits = lm.model(torch.tensor([entry['ids'][:4]])).logits[0, -1]
        self.assertAlmostEqual(before[0, 0], logits.log_softmax(0)[20].item(), places=5)
        after = lm.target_probabilities([{**entry, 'ids': [4, 8, 12, 16, 20, 31, 32]}, short], 1, 0, [units])
        np.testing.assert_array_equal(before, after)
        self.assertTrue(np.any(np.abs(before[:, 1] - before[:, 0]) > 1e-5))
        # With no later attention layer, changing pre2 cannot affect logits at pre1.
        earlier = lm.target_probabilities([entry, short], 1, 1, [units])
        np.testing.assert_allclose(earlier[:, 0], earlier[:, 1], atol=1e-6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
