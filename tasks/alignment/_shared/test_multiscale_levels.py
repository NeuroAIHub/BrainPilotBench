"""Offline regression checks for the four scale-specific experiments and their decision protocol."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from multiscale.breadth import CARDS, grade, reference
from multiscale.circuits import head_paths
from multiscale.model import LanguageModel
from multiscale.networks import edge_change, modules
from multiscale.single_cell import source_table, tuning
from multiscale.systems import graph_features
from real_brainscore.common import seal, sha256, write_json


class MultiscaleLevelTests(unittest.TestCase):
    def test_single_cell_tuning_uses_only_the_selected_trials(self):
        labels = np.tile(np.arange(9), 3)
        rates = np.concatenate((np.arange(9), np.arange(9) + 2, np.arange(9) + 100))
        train = np.arange(len(rates)) < 18
        np.testing.assert_array_equal(tuning(rates, labels, train), np.arange(9) + 1)
        np.testing.assert_array_equal(tuning(rates, labels, ~train), np.arange(9) + 100)
        with TemporaryDirectory() as tmp, patch('pandas.read_pickle') as decode:
            (Path(tmp) / 'jamali-cells.pickle').write_bytes(b'another source')
            with self.assertRaisesRegex(ValueError, 'source differs'):
                source_table(tmp, 'jamali-cells.pickle')
            decode.assert_not_called()

    def test_patching_only_reaches_output_through_the_selected_receiver(self):
        import torch
        from transformers import GPT2Config, GPT2LMHeadModel
        torch.manual_seed(104)
        torch.set_num_threads(1)
        lm = LanguageModel.__new__(LanguageModel)
        lm.model = GPT2LMHeadModel(GPT2Config(n_layer=3, n_head=2, n_embd=12, n_inner=20,
                                              n_positions=16, vocab_size=40)).eval()
        lm.tokenizer = SimpleNamespace(eos_token_id=39)
        normal = [{'ids': [4, 8, 12, 16, 20, 24], 'start': 4},
                  {'ids': [9, 3, 5, 7, 18], 'start': 3}]
        corrupt = [{'ids': [4, 12, 8, 16, 20, 35], 'start': 4},
                   {'ids': [9, 5, 3, 7, 11], 'start': 3}]
        selected = [1, 3, 5, 6, 7, 9, 10, 13]
        same, gap = head_paths(lm, normal, normal, selected)
        np.testing.assert_allclose(same, 0, atol=5e-7)
        np.testing.assert_array_equal(gap, 0)
        effect, _ = head_paths(lm, normal, corrupt, selected)
        self.assertGreater(np.abs(effect).max(), 1e-7)
        with torch.no_grad():
            lm.model.transformer.h[2].mlp.c_proj.weight[selected] = 0
        blocked, gap = head_paths(lm, normal, corrupt, selected)
        np.testing.assert_array_equal(blocked, 0)
        self.assertGreater(np.abs(gap).max(), 1e-4)

    def test_network_edges_remove_run_offsets_and_regions_use_disjoint_units(self):
        rng = np.random.default_rng(414)
        activity = rng.normal(size=(96, 5))
        conditions = np.repeat(['D', 'S'], 48)
        runs = np.tile(np.repeat(np.arange(4), 12), 2)
        shifted = activity.copy()
        for name in ('D', 'S'):
            for run in range(4):
                shifted[(conditions == name) & (runs == run)] += rng.normal(size=5) * 100
        expected = edge_change(activity, conditions, runs)
        self.assertEqual(expected.shape, (10,))
        np.testing.assert_allclose(edge_change(shifted, conditions, runs), expected, atol=1e-12)
        x, target = rng.normal(size=(60, 48)), rng.normal(size=(40, 5))
        before, groups = modules(x, np.arange(40), target)
        self.assertEqual(len({u for group in groups for u in group}), 40)
        x[40:] += 100
        after, repeated = modules(x, np.arange(40), target)
        self.assertEqual(groups, repeated)
        np.testing.assert_array_equal(before[:40], after[:40])

    def test_whole_system_controls_preserve_global_mean_and_change_topology(self):
        atlas = np.repeat(np.arange(9), 2)
        edges = np.tril_indices(len(atlas), -1)
        within = atlas[edges[0]] == atlas[edges[1]]
        fc = np.where(within[None, :], .6, .08)
        measured = graph_features(fc, atlas, edges)
        shuffle = graph_features(fc, np.random.default_rng(5).permutation(atlas), edges)
        np.testing.assert_array_equal(measured['mean_connectivity'], shuffle['mean_connectivity'])
        np.testing.assert_allclose(measured['system_segregation'][0, 1:], 1 - np.arctanh(.08) / np.arctanh(.6))
        self.assertGreater(np.abs(measured['system_segregation'] - shuffle['system_segregation']).max(), .1)
        self.assertEqual(measured['network_blocks'].shape, (1, 46))
        self.assertTrue(np.all((measured['two_step_return'][:, 1:] > 0) & (measured['two_step_return'][:, 1:] < 1)))

    def test_reference_uses_public_evidence_and_a_researcher_cannot_rescore_a_changed_choice(self):
        task, metric, unit, threshold, _ = CARDS[1]
        challenge = {'level': 1, 'task': task, 'unit': unit, 'metric': metric, 'near_zero_threshold': threshold,
                     'candidates': [{'id': 'A', 'train_value': .8}, {'id': 'B', 'train_value': .6}]}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'public/challenge.json', challenge)
            seal(root / 'public', {'schema': task + '/public-v1'})
            write_json(root / 'owner/outcomes.json', {'A': {'value': -.2}, 'B': {'value': .02}})
            seal(root / 'owner', {'schema': task + '/owner-v1', 'public_sha256': sha256(root / 'public/manifest.json')})
            answer = reference(challenge)
            scored = grade(root, 'first', answer)
            self.assertEqual(scored['scores'], {metric: -.2, 'direction_correct': 0, 'forecast_absolute_error': 1.})
            self.assertEqual(grade(root, 'first', answer), scored)
            second = {**answer, 'choice': 'B', 'forecast': -.05}
            with self.assertRaisesRegex(ValueError, 'already froze'):
                grade(root, 'first', second)
            self.assertEqual(grade(root, 'second', second)['scores']['direction_correct'], 1)
            for invalid in ({}, {**answer, 'choice': 'C'}, {**answer, 'forecast': 1.2},
                            {**answer, 'forecast': float('nan')}, {**answer, 'alternative': ''}):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    grade(root, 'new', invalid)


if __name__ == '__main__':
    unittest.main(verbosity=2)
