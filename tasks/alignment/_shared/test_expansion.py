"""Offline numerical, leakage, replay and hidden-decision regression tests."""
import copy
import itertools
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.special import logsumexp
from scipy.stats import spearmanr

from execution import AnalysisFailure, InfrastructureError
from expansion import ExpansionError
from expansion.packet import array, load, save
from expansion.protocol import default_plan, specification
from expansion.runner import reference_submission, run
from expansion.evaluation import compare, evaluate
from expansion.rsa import distance, partition, vector
from expansion import brain_behavior, learning, selection, temporal
from real_brainscore.common import new_directory, read_json, seal, write_json


def fixture(root, task):
    rng = np.random.default_rng(8)
    root = new_directory(root)
    if task in ('C', 'D'):
        ids = ['concept-%02d' % i for i in range(20)]
        features = rng.normal(size=(2, 20, 8))
        parts = partition(ids, [.4, .3, .3] if task == 'C' else [.5, .5], 41)
        meta = {'concept_ids': ids, 'candidates': ['one', 'two'], 'subjects': ['s1', 's2'],
                'partition_concept_ids': [[ids[i] for i in part] for part in parts]}
        if task == 'C':
            trips = np.asarray([row for part in parts for row in itertools.combinations(part, 3)])
            splits = np.concatenate([np.full(len(list(itertools.combinations(part, 3))), i) for i, part in enumerate(parts)])
            meta.update(matching='concept proxy', candidate_scope='fixture only')
            arrays = {'features': features, 'neural_rdms': np.stack([distance(features[0] + rng.normal(size=(20, 8)) * .2) for _ in range(2)]),
                      'triplets': trips, 'triplet_partition': splits}
        else:
            times = np.arange(-200., 401., 10.)
            eeg = rng.normal(size=(2, 20, 8, len(times)))
            eeg[:, :, :, (times >= 100) & (times < 150)] += features[0][None, :, :, None] * 3
            meta.update(discovery_subject_indices=[0], confirmation_subject_indices=[1], confirmation_scope='fixture only')
            arrays = {'features': features, 'eeg': eeg, 'times_ms': times}
    elif task == 'E':
        target = rng.uniform(-np.pi, np.pi, size=(6, 3, 60))
        meta = {'participant_ids': ['p%d' % i for i in range(6)], 'conditions': ['same'] * 3 + ['far'] * 3,
                'human_phase_repetitions': 1, 'models': [{'id': 'once', 'phase_repetitions': 1,
                 'state_reset_between_phases': False, 'update_without_feedback': False}]}
        arrays = {'targets': target, 'human_responses': target + .1, 'model_0_responses': target + .2,
                  'feedback_present': np.ones((6, 3, 120), dtype=bool)}
    elif task == 'F':
        meta = {'train_ids': ['t%d' % i for i in range(30)], 'candidate_ids': ['c%02d' % i for i in range(40)],
                'candidate_length_bins': [0] * 20 + [1] * 20, 'quota_per_group': {'0': 5, '1': 5}}
        arrays = {'train_features': rng.normal(size=(30, 6)), 'train_responses': rng.normal(size=(30, 2)),
                  'candidate_features': rng.normal(size=(40, 6))}
    else:
        from test_incremental import fixture as a_fixture
        from incremental.data import load_inputs
        old = load_inputs(a_fixture(root.parent / 'old-inputs'))
        meta = {k: old[k] for k in ('stimuli', 'neuroids', 'splits')}
        meta['excluded_ids'] = []
        arrays = {'brain': old['brain'], 'sentence_only': old['features'],
                  'normal_prefix': old['features'] + .1, 'reversed_prefix': rng.normal(size=old['features'].shape)}
    return save(root, task, meta, arrays, {'fixture': True}, synthetic=True)


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bpb-expansion-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_behavior_softmax_matches_independent_logsumexp(self):
        rdm = np.asarray([[0., .2, 1.2], [.2, 0., .7], [1.2, .7, 0.]])
        got = brain_behavior.negative_log_likelihood(rdm, np.array([[0, 1, 2]]), .3)[0]
        logits = -np.array([.2, 1.2, .7]) / .3
        self.assertAlmostEqual(got, logsumexp(logits) - logits[0])

    def test_c_temperature_never_uses_confirmation_choices(self):
        p = fixture(self.root / 'c', 'C')
        original = brain_behavior.compute(p, default_plan('C'))[0]
        changed = copy.deepcopy(p)
        rows = changed['arrays']['triplet_partition'] == 2
        changed['arrays']['triplets'][rows] = changed['arrays']['triplets'][rows][:, [0, 2, 1]]
        altered = brain_behavior.compute(changed, default_plan('C'))[0]
        self.assertEqual(original['temperatures'], altered['temperatures'])
        self.assertNotEqual(original['behavior_nll'], altered['behavior_nll'])

    def test_c_rejects_cross_concept_partition_leakage(self):
        p = fixture(self.root / 'c', 'C')
        indices = partition(p['metadata']['concept_ids'], [.4, .3, .3], 41)
        p['arrays']['triplets'][0, 0] = indices[2][0]
        with self.assertRaisesRegex(ExpansionError, 'leakage'):
            brain_behavior.compute(p, default_plan('C'))

    def test_rsa_agrees_with_scipy_and_handles_ties(self):
        p = fixture(self.root / 'c', 'C')
        models = np.stack([distance(x) for x in p['arrays']['features']])
        indices = np.arange(8)
        got = brain_behavior.neural_scores(models, p['arrays']['neural_rdms'], indices)
        for m in range(2):
            for s in range(2):
                expected = spearmanr(vector(models[m], indices), vector(p['arrays']['neural_rdms'][s], indices)).statistic
                self.assertAlmostEqual(got[m, s], expected)

    def test_d_confirmation_cannot_select_window_and_pvalues_are_bounded(self):
        p = fixture(self.root / 'd', 'D')
        before, arrays, _ = temporal.compute(p, default_plan('D'))
        changed = copy.deepcopy(p)
        changed['arrays']['eeg'][1] = np.random.default_rng(99).normal(size=changed['arrays']['eeg'][1].shape)
        after, altered, _ = temporal.compute(changed, default_plan('D'))
        self.assertEqual(before['selected_window_ms'], after['selected_window_ms'])
        np.testing.assert_array_equal(arrays['discovery_rsa'], altered['discovery_rsa'])
        self.assertFalse(np.array_equal(arrays['confirmation_rsa'], altered['confirmation_rsa']))
        self.assertTrue(np.all((arrays['confirmation_max_stat_p'] >= 1/500) & (arrays['confirmation_max_stat_p'] <= 1)))
        uncorrected = (1 + (np.abs(arrays['null_window_contrast']) >= abs(before['confirmation_window_difference'])).sum()) / 500
        self.assertEqual(before['selected_window_label_permutation_p'], uncorrected)

    def test_d_rejects_subject_overlap_and_reversed_time(self):
        p = fixture(self.root / 'd', 'D')
        p['metadata']['confirmation_subject_indices'] = [0]
        with self.assertRaisesRegex(ExpansionError, 'disjoint'):
            temporal.compute(p, default_plan('D'))
        p['metadata']['confirmation_subject_indices'] = [1]
        p['arrays']['times_ms'] = p['arrays']['times_ms'][::-1]
        with self.assertRaisesRegex(ExpansionError, 'time'):
            temporal.compute(p, default_plan('D'))

    def test_circular_errors_and_phase_metric_signs(self):
        np.testing.assert_allclose(learning.circular_error(np.deg2rad([359., -179., 10.]), np.deg2rad([1., 179., 10.])), [2., 2., 0.])
        errors = np.array([[[40.] * 20 + [10.] * 20, [20.] * 20 + [5.] * 20, [30.] * 20 + [15.] * 20]])
        metrics, curves = learning.trajectory_metrics(errors, 20)
        np.testing.assert_array_equal(metrics, [[20., 10., 20., 30., 15., 15.]])
        self.assertEqual(curves.shape, (1, 3, 10))

    def test_simulation_never_updates_on_missing_or_future_feedback(self):
        stimulus = np.zeros((3, 4), dtype='int64')
        probe = np.ones((3, 4), dtype='int64')
        feedback = np.zeros((3, 4))
        mask = np.zeros((3, 4), dtype=bool)
        first = learning.simulate(stimulus, probe, feedback, mask, 1, 11)
        feedback[:] = 1.
        second = learning.simulate(stimulus, probe, feedback, mask, 1, 11)
        np.testing.assert_array_equal(first, second)
        mask[-1, -1] = True
        third = learning.simulate(stimulus, probe, feedback, mask, 1, 11)
        np.testing.assert_array_equal(first, third)  # final feedback cannot affect any earlier prediction.

    def test_simulation_step_matches_finite_difference_gradient(self):
        seed = 31
        rng = np.random.default_rng(seed)
        first = rng.normal(0., .001, (50, 12))
        second = rng.normal(0., .001, (4, 50))
        target = np.array([np.sin(.7), np.cos(.7)])
        def loss(w, v):
            return np.mean((v[2:4] @ w[:, 0] - target) ** 2)
        epsilon = 1e-6
        grad_first, grad_second = np.zeros_like(first), np.zeros_like(second)
        for i in range(50):
            a, b = first.copy(), first.copy(); a[i, 0] += epsilon; b[i, 0] -= epsilon
            grad_first[i, 0] = (loss(a, second) - loss(b, second)) / (2 * epsilon)
            for output in (2, 3):
                a, b = second.copy(), second.copy(); a[output, i] += epsilon; b[output, i] -= epsilon
                grad_second[output, i] = (loss(first, a) - loss(first, b)) / (2 * epsilon)
        predicted = (second - .1 * grad_second)[2:4] @ (first - .1 * grad_first)[:, 0]
        expected = np.arctan2(predicted[0], predicted[1])
        stimulus = np.zeros((3, 2), dtype='int64'); probes = np.ones_like(stimulus)
        feedback = np.full((3, 2), .7); present = np.zeros((3, 2), dtype=bool); present[0, 0] = True
        actual = learning.simulate(stimulus, probes, feedback, present, 1, seed)
        self.assertAlmostEqual(actual[0, 1], expected, places=7)

    def test_learning_equal_exposure_audit_and_paired_differences(self):
        p = fixture(self.root / 'e', 'E')
        summary, _, conclusion = learning.compute(p, default_plan('E'))
        self.assertEqual(conclusion['exposure_matched'], {'once': True})
        self.assertTrue(summary['exposure']['once']['feedback_only_updates'])
        for group in summary['groups'].values():
            np.testing.assert_allclose(group['model_minus_human'], 0., atol=1e-12)

    def test_f_scores_real_selection_not_agreement_with_reference(self):
        p = fixture(self.root / 'f', 'F'); plan = default_plan('F')
        saved, replay = self.root / 'saved', self.root / 'replay'
        run(p['root'], saved, plan); run(p['root'], replay, plan)
        meta = p['metadata']; ids = meta['candidate_ids']
        choices = {'drive': ids[:5] + ids[20:25], 'suppress': ids[5:10] + ids[25:30]}
        self.assertNotEqual(choices, selection.compute(p, plan)[0]['selection'])
        for root in (saved, replay):
            summary = read_json(root / 'results/summary.json'); summary['selection'] = choices
            write_json(root / 'results/summary.json', summary)
        y = np.zeros((40, 2)); y[[ids.index(s) for s in choices['drive']]] = [2., 4.]
        owner = {'candidate_ids': ids, 'subjects': ['x', 'y'], 'responses': y, 'manifest_sha256': 'owner'}
        grade = selection.grade_selection(p, owner, replay, saved, plan, {'analyze.py': 'hash'}, self.root / 'ledger')
        self.assertEqual(grade['selection_effect'], 3.)
        self.assertEqual(grade['subject_effects'], {'x': 2., 'y': 4.})
        self.assertFalse(grade['random_reference_is_significance_test'])

    def test_f_freeze_is_idempotent_but_rejects_second_query(self):
        key = 'a' * 64
        first = selection.freeze(self.root / 'ledger', key, {'selection': ['a']})
        self.assertEqual(first, selection.freeze(self.root / 'ledger', key, {'selection': ['a']}))
        with self.assertRaisesRegex(AnalysisFailure, 'frozen'):
            selection.freeze(self.root / 'ledger', key, {'selection': ['b']})

    def test_f_rejects_duplicates_overlap_and_quota_violations(self):
        p = fixture(self.root / 'f', 'F'); plan = default_plan('F')
        output = self.root / 'results'; run(p['root'], output, plan)
        original = read_json(output / 'results/summary.json')
        for kind in ('duplicate', 'overlap', 'quota'):
            value = copy.deepcopy(original)
            if kind == 'duplicate': value['selection']['drive'][1] = value['selection']['drive'][0]
            elif kind == 'overlap': value['selection']['drive'] = value['selection']['suppress']
            else: value['selection']['drive'] = p['metadata']['candidate_ids'][:10]
            write_json(output / 'results/summary.json', value)
            with self.assertRaises(AnalysisFailure): selection.validate_selection(p, output, plan)

    def test_pickle_and_packet_mutation_rejected(self):
        path = self.root / 'unsafe.npy'; np.save(path, {'secret': 'never unpickle'})
        with self.assertRaisesRegex(ExpansionError, 'unsafe'): array(path)
        p = fixture(self.root / 'c', 'C')
        (p['root'] / 'unlisted.txt').write_text('changed')
        with self.assertRaisesRegex(ExpansionError, 'inventory'): load(p['root'])

    def test_b_c_d_e_source_replays_and_forged_outputs_fail(self):
        for task in 'BCDE':
            with self.subTest(task=task):
                p = fixture(self.root / (task + '-input'), task)
                source = self.root / (task + '-submission')
                reference_submission(task, source)
                saved = self.root / (task + '-saved'); run(p['root'], saved, default_plan(task))
                with patch.dict(os.environ, {'BPB_ALIGNMENT_TRUSTED_LOCAL': '1'}):
                    grade = evaluate(p['root'], source, self.root / (task + '-grade'), isolation='process', saved_results=saved)
                self.assertEqual(grade['state'], 'scored', grade)
                self.assertEqual(grade['analysis_success'], 1, grade)
                conclusion = read_json(saved / 'conclusion.json'); conclusion['unsupported_causality'] = True
                write_json(saved / 'conclusion.json', conclusion)
                self.assertFalse(compare(saved, self.root / (task + '-grade') / 'worker-output')['passed'])

    def test_infrastructure_failure_has_no_agent_score(self):
        p = fixture(self.root / 'c', 'C'); source = self.root / 'source'
        reference_submission('C', source)
        with patch('expansion.evaluation.Executor.preflight', side_effect=InfrastructureError('test unavailable')):
            grade = evaluate(p['root'], source, self.root / 'grade')
        self.assertEqual(grade['state'], 'scoring_failed')
        self.assertIsNone(grade['analysis_success'])

    def test_f_ledger_cannot_be_placed_in_agent_inputs(self):
        p = fixture(self.root / 'f', 'F'); source = self.root / 'source'
        reference_submission('F', source)
        with patch('expansion.evaluation.Executor.preflight') as preflight:
            grade = evaluate(p['root'], source, self.root / 'grade', hidden=self.root / 'hidden', ledger=p['root'] / 'ledger')
        preflight.assert_not_called()
        self.assertEqual(grade['state'], 'scoring_failed')
        self.assertIsNone(grade['analysis_success'])

    def test_source_lock_rejects_same_size_corruption(self):
        import hashlib
        from expansion.sources import verify_source
        path = self.root / 'data'; path.write_bytes(b'original')
        entry = {'file': 'data', 'bytes': 8, 'sha256': hashlib.sha256(b'original').hexdigest()}
        self.assertEqual(verify_source(self.root, entry), path)
        path.write_bytes(b'changed!')
        with self.assertRaisesRegex(ExpansionError, 'mismatched'):
            verify_source(self.root, entry)

    def test_source_download_resumes_exact_range_and_checks_digest(self):
        import hashlib
        import io
        from expansion.sources import download
        data = b'authenticated author data'
        entry = {'task': 'E', 'file': 'source.csv', 'url': 'https://example.invalid/source',
                 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (self.root / 'source.csv.part').write_bytes(data[:7])
        response = io.BytesIO(data[7:]); response.status = 206
        response.headers = {'Content-Range': 'bytes 7-%d/%d' % (len(data) - 1, len(data))}
        with patch('expansion.sources.entries', return_value=[entry]), patch('expansion.sources.urllib.request.urlopen', return_value=response) as request:
            result = download(self.root, 'E')
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=7-')
        self.assertEqual((self.root / 'source.csv').read_bytes(), data)
        self.assertFalse((self.root / 'source.csv.part').exists())
        self.assertEqual(result['verified_sources'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
