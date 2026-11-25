"""Synthetic, offline regression tests for the L4 scientific and submission contracts."""
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from multiscale import K, POSITIONS
from multiscale.networks import EDGES, ROIS
from multiscale.roi_reference import select
from network_edges import METRIC, PROTOCOL
from network_edges.scoring import Packet, grade
from network_edges.staging import stage
from real_brainscore.common import seal, sha256, write_json
from unit_transfer.session import record


def fixture(root):
    rng = np.random.default_rng(29)
    groups = {roi: {'layer': j % 2, 'position': POSITIONS[j % 2], 'units': list(range(8 * j, 8 * j + 8))}
              for j, roi in enumerate(ROIS)}
    for name, n, people in [('public', 64, 3), ('dev', 56, 1), ('test', 80, 2)]:
        part = root / 'public' if name == 'public' else root / 'owner' / name
        part.mkdir(parents=True)
        x = rng.normal(size=(n, 2, 2, 48)).astype('float32')
        selected = np.stack([x[:, j % 2, j % 2, 8 * j:8 * j + 8] for j in range(5)], axis=1).astype('float64')
        if name == 'public':
            mu, sd = selected.mean(axis=0), selected.std(axis=0)
        signal = ((selected - mu) / sd).mean(axis=2)
        runs = rng.integers(2, size=(n, people))
        y = np.stack([signal + runs[:, j, None] * np.arange(5) for j in range(people)], axis=1)
        labels = ['B'] * n if name == 'public' else ['D', 'S'] * (n // 2)
        write_json(part / 'items.json', {'ids': [f'{name}-id-{i}' for i in range(n)],
                   'texts': [f'{name} item {i}' for i in range(n)], 'subjects': [f'{name}-{j}' for j in range(people)],
                   'conditions': labels, 'runs': runs.astype(str).tolist()})
        for key, array in [('units', x), ('responses', y), ('controls', rng.normal(size=(n, 2)))]:
            np.save(part / f'{key}.npy', array, allow_pickle=False)
    write_json(root / 'public/protocol.json', {'task': PROTOCOL, 'model': {'id': 'fixture', 'layers': 2, 'width': 48},
               'positions': list(POSITIONS), 'units_per_roi': K, 'rois': ROIS,
               'edges': [[ROIS[i], ROIS[j]] for i, j in EDGES]})
    seal(root / 'public', {'schema': PROTOCOL + '/public'})
    digest = sha256(root / 'public/manifest.json')
    seal(root / 'owner', {'schema': PROTOCOL + '/owner', 'public_sha256': digest})
    return Packet(root), {'packet_sha256': digest, 'groups': groups, 'predicted_edge_r': 0.4}


class NetworkEdgesTest(unittest.TestCase):
    def test_within_run_edges_participant_average_and_exact_permutations(self):
        with TemporaryDirectory() as tmp:
            packet, choice = fixture(Path(tmp))
            scores = packet.scores('test', choice, include_permutations=True)
            self.assertAlmostEqual(scores[METRIC], 1.)
            self.assertAlmostEqual(scores['roi_permutation']['one_sided_p'], 1/120)
            part = packet.splits['test']
            for j, person in enumerate(part.subjects):
                expected = np.zeros(10)
                for label, sign in [('D', 1), ('S', -1)]:
                    rows = part.labels == label
                    y, runs = part.y[rows, j].copy(), part.runs[rows, j]
                    residuals = np.vstack([y[runs == run] - y[runs == run].mean(axis=0) for run in set(runs)])
                    expected += sign * np.corrcoef(residuals.T)[np.triu_indices(5, 1)]
                result = scores['participants'][person]
                np.testing.assert_allclose(result['brain_edge_changes'], expected)
                np.testing.assert_allclose(result['model_edge_changes'], expected)
            packet.brain['test'][1] = -packet.brain['test'][1]
            self.assertAlmostEqual(packet.scores('test', choice)[METRIC], 0.)
            part.units = np.zeros_like(part.units)
            self.assertIsNone(packet.scores('test', choice)[METRIC])

    @patch.dict(os.environ, {'BPB_SUBMISSION_ISOLATION': 'process', 'BPB_ALIGNMENT_TRUSTED_LOCAL': '1'})
    def test_scalar_queries_freeze_and_public_only_replay(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, choice = fixture(root / 'packet')
            stage(packet, root / 'task', 'researcher')
            self.assertEqual(set(p.name for p in (root/'task/public').iterdir()),
                             {'units.npy', 'responses.npy', 'controls.npy', 'items.json', 'protocol.json', 'manifest.json'})
            self.assertFalse((root/'task/owner').exists())
            first = record(packet, 'researcher', choice)
            self.assertEqual(set(first), {'query', 'choice', 'dev_edge_r'})
            self.assertAlmostEqual(first['dev_edge_r'], 1.)
            reordered = deepcopy(choice)
            reordered['groups'][ROIS[1]]['units'].reverse()
            reordered.pop('predicted_edge_r')
            self.assertEqual(first, record(packet, 'researcher', reordered))
            other = select(packet.root / 'public', 'random')
            self.assertEqual(record(packet, 'researcher', other)['query'], 2)
            third = select(packet.root / 'public', 'roi_specific')
            with self.assertRaisesRegex(ValueError, 'budget'):
                record(packet, 'researcher', third)
            code = root / 'strategy.py'
            code.write_text('import json, sys\nfrom pathlib import Path\n'
                            'assert sys.argv[1:] == ["public", "feedback.json"]\n'
                            'assert not Path("owner").exists() and not Path("public/owner").exists()\n'
                            'answer = json.loads(Path("feedback.json").read_text())[0]["choice"]\n'
                            'answer["predicted_edge_r"] = 0.4\nprint(json.dumps(answer))\n')
            result = grade(packet, 'researcher', choice, code)
            self.assertTrue(result['replay']['verified'])
            self.assertEqual(result['freeze']['choice'], choice)
            self.assertEqual(result['freeze']['strategy_sha256'], sha256(code))
            self.assertAlmostEqual(result['results']['agent']['scores']['prediction_abs_error'], .6)
            gain = result['results']['agent']['scores']['gain_over_roi_specific']
            self.assertAlmostEqual(gain, 1. - result['results']['roi_specific']['scores'][METRIC])
            self.assertEqual(result, grade(packet, 'researcher', choice, code))
            with self.assertRaisesRegex(ValueError, 'different submission'):
                grade(packet, 'researcher', {**choice, 'predicted_edge_r': 0.5}, code)
            with self.assertRaisesRegex(ValueError, 'frozen'):
                record(packet, 'researcher', choice)
            wrong = root / 'wrong.py'
            wrong.write_text('print(' + repr(json.dumps(other)) + ')')
            with self.assertRaisesRegex(ValueError, 'replayed choice differs'):
                grade(packet, 'independent', choice, wrong)

    def test_schema_and_global_native_unit_identity(self):
        with TemporaryDirectory() as tmp:
            packet, choice = fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, 'different packet'):
                packet.choice({**choice, 'packet_sha256': 'wrong'})
            for forecast in [None, True, float('nan'), 1.1]:
                with self.subTest(forecast=forecast), self.assertRaisesRegex(ValueError, 'predicted_edge_r'):
                    packet.choice({**choice, 'predicted_edge_r': forecast})
            overlap = deepcopy(choice)
            overlap['groups'][ROIS[1]] = {**choice['groups'][ROIS[0]], 'position': 'pre2'}
            with self.assertRaisesRegex(ValueError, 'across regions'):
                packet.choice(overlap)
            del overlap['groups'][ROIS[0]]
            with self.assertRaisesRegex(ValueError, 'five regions'):
                packet.choice(overlap)


if __name__ == '__main__':
    unittest.main()
