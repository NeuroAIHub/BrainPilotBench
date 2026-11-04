"""Scientific and evaluator regressions for Task A; entirely offline."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from incremental import PROTOCOL, IncrementalError
from incremental.analysis import compute, reference_submission, ridge_path, run_analysis, summarize
from incremental.data import controls_from_stimuli, load_inputs, response_qc
from incremental.evaluation import compare, evaluate, read_predictions
from incremental.protocol import expected_conclusion, make_splits, specification
from real_brainscore.common import read_json, seal, write_json
from context_pilot import context_design, matched_rows
from execution import AnalysisFailure, InfrastructureError


def fixture(root):
    root = Path(root)
    root.mkdir()
    rng = np.random.default_rng(6)
    stimuli = []
    for passage in range(12):
        for pos in range(4):
            i = passage * 4 + pos
            stimuli.append({'stimulus_id': 's%d' % i, 'stimulus': 'word ' * (2 + i % 7),
                            'story': 'story-%02d' % passage, 'passage_label': 'p%d' % passage,
                            'passage_index': passage + 1, 'stimulus_num': i})
    c = controls_from_stimuli(stimuli)
    x = rng.normal(size=(48, 6))
    y = x @ rng.normal(size=(6, 4)) + c @ rng.normal(size=(5, 4)) + rng.normal(size=(48, 4)) * .3
    for name, value in [('features', x), ('brain', y), ('controls', c)]:
        np.save(root / (name + '.npy'), value, allow_pickle=False)
    write_json(root / 'protocol.json', specification())
    write_json(root / 'provenance.json', {'fixture': True})
    write_json(root / 'stimuli.json', stimuli)
    write_json(root / 'neuroids.json', [{'neuroid_id': 'n%d' % i, 'subject_id': 'u%d' % (i // 2)} for i in range(4)])
    write_json(root / 'splits.json', make_splits(stimuli))
    seal(root, {'schema': 'bpb-incremental-inputs/1', 'protocol_id': PROTOCOL, 'synthetic_only': True})
    return root


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bpb-incremental-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = fixture(self.root / 'inputs')
        self.plan = {'protocol_id': PROTOCOL, 'control_set': 'word_count+position', 'rationale': 'Test both declared controls.'}

    def test_positions_follow_original_order_not_passage_index_or_row_order(self):
        stimuli = read_json(self.inputs / 'stimuli.json')
        base = controls_from_stimuli(stimuli)
        order = np.random.default_rng(9).permutation(len(stimuli))
        np.testing.assert_array_equal(controls_from_stimuli([stimuli[i] for i in order]), base[order])
        self.assertTrue(np.array_equal(base[:4, 1:], np.eye(4)))
        stimuli[0]['story'] = 'wrong-story'
        with self.assertRaises(IncrementalError):
            controls_from_stimuli(stimuli)

    def test_context_conditions_use_identical_targets_and_only_prior_sentences(self):
        stimuli = read_json(self.inputs / 'stimuli.json')
        mapping = {r['stimulus_id']: r for r in stimuli}
        design = context_design(stimuli)
        self.assertEqual(len(design), 24)
        for row in design:
            target = mapping[row['stimulus_id']]
            self.assertIn(row['position'], (3, 4))
            self.assertTrue(all(mapping[s]['stimulus_num'] < target['stimulus_num'] for s in row['history_ids']))
            self.assertTrue(all(mapping[s]['passage_label'] == target['passage_label'] for s in row['history_ids']))
            c = row['conditions']
            self.assertEqual(c['sentence_only'], [target['stimulus']])
            self.assertEqual(c['normal_prefix'][-1], c['reversed_prefix'][-1])
            self.assertEqual(c['normal_prefix'][:-1], c['reversed_prefix'][:-1][::-1])

    def test_context_matching_uses_input_token_counts_only(self):
        rows = [{'stimulus_id': 'a', 'token_lengths': {'normal_prefix': 20, 'reversed_prefix': 20}},
                {'stimulus_id': 'b', 'token_lengths': {'normal_prefix': 20, 'reversed_prefix': 21}}]
        self.assertEqual(matched_rows(rows), [0])

    def test_ridge_matches_independent_sklearn_implementation(self):
        rng = np.random.default_rng(8)
        x, y = rng.normal(size=(21, 30)), rng.normal(size=(21, 3))
        x[:, 2] = 5  # constant features and a rank-deficient wide design
        scaler = StandardScaler().fit(x[:15])
        for alpha, pred in zip([.1, 10, 1000], ridge_path(x[:15], y[:15], x[15:], [.1, 10, 1000])):
            independent = Ridge(alpha=alpha, solver='svd').fit(scaler.transform(x[:15]), y[:15])
            np.testing.assert_allclose(pred, independent.predict(scaler.transform(x[15:])), atol=1e-11)

    def test_constant_response_qc_is_explicit_and_preserves_subjects(self):
        packet = load_inputs(self.inputs)
        y = packet['brain'].copy()
        y[:, 0] = 0
        y[:, 2] = 5
        filtered, units, excluded = response_qc(y, packet['neuroids'])
        self.assertEqual(filtered.shape, (48, 2))
        self.assertEqual([n['neuroid_id'] for n in excluded], ['n0', 'n2'])
        self.assertEqual({n['reason'] for n in excluded}, {'constant_full_dataset'})
        self.assertEqual({n['subject_id'] for n in units}, {'u0', 'u1'})
        y[:, 1] = 0
        with self.assertRaisesRegex(IncrementalError, 'entire subject'):
            response_qc(y, packet['neuroids'])

    def test_nested_results_match_independent_sklearn_pipeline(self):
        packet = load_inputs(self.inputs)
        predictions, traces, _ = compute(packet, self.plan)
        ids = [s['stimulus_id'] for s in packet['stimuli']]
        subjects = np.array([n['subject_id'] for n in packet['neuroids']])
        matrices = {'control': packet['controls'], 'model': packet['features'],
                    'joint': np.column_stack([packet['controls'], packet['features']])}
        y = packet['brain']
        alphas = packet['protocol']['alphas']
        for outer, trace in zip(packet['splits'], traces):
            a, b = [[ids.index(s) for s in outer[k]] for k in ('train_ids', 'test_ids')]
            for name, x in matrices.items():
                scores = []
                for alpha in alphas:
                    errors, baseline = np.zeros(y.shape[1]), np.zeros(y.shape[1])
                    for inner in outer['inner']:
                        train, test = [[ids.index(s) for s in inner[k]] for k in ('train_ids', 'test_ids')]
                        scaler = StandardScaler().fit(x[train])
                        model = Ridge(alpha=alpha, solver='svd').fit(scaler.transform(x[train]), y[train])
                        pred = model.predict(scaler.transform(x[test]))
                        errors += np.sum((pred-y[test])**2, axis=0)
                        baseline += np.sum((y[test]-y[train].mean(axis=0))**2, axis=0)
                    r2 = 1-errors/baseline
                    scores.append(np.mean([r2[subjects==s].mean() for s in set(subjects)]))
                alpha = alphas[int(np.argmax(scores))]
                self.assertEqual(alpha, trace['readouts'][name]['alpha'])
                np.testing.assert_allclose(scores, trace['readouts'][name]['inner_r2'], atol=1e-11)
                scaler = StandardScaler().fit(x[a])
                model = Ridge(alpha=alpha, solver='svd').fit(scaler.transform(x[a]), y[a])
                np.testing.assert_allclose(predictions[name][b], model.predict(scaler.transform(x[b])), atol=1e-11)

    def test_nested_story_disjointness_and_exact_outer_coverage(self):
        packet = load_inputs(self.inputs)
        groups = {s['stimulus_id']: s['story'] for s in packet['stimuli']}
        covered = []
        for outer in packet['splits']:
            self.assertFalse({groups[s] for s in outer['train_ids']} & {groups[s] for s in outer['test_ids']})
            covered.extend(outer['test_ids'])
            inner_tests = []
            for inner in outer['inner']:
                self.assertEqual(set(inner['train_ids']) | set(inner['test_ids']), set(outer['train_ids']))
                self.assertFalse({groups[s] for s in inner['train_ids']} & {groups[s] for s in inner['test_ids']})
                inner_tests.extend(inner['test_ids'])
            self.assertCountEqual(inner_tests, outer['train_ids'])
        self.assertCountEqual(covered, list(groups))

    def test_outer_test_responses_cannot_affect_predictions_or_alpha(self):
        packet = load_inputs(self.inputs)
        predictions, trace, _ = compute(packet, self.plan)
        altered = copy.deepcopy(packet)
        ids = [s['stimulus_id'] for s in packet['stimuli']]
        test = [ids.index(s) for s in packet['splits'][0]['test_ids']]
        altered['brain'][test] += 5000
        other, other_trace, _ = compute(altered, self.plan)
        self.assertEqual(trace[0], other_trace[0])
        for name in predictions:
            np.testing.assert_array_equal(predictions[name][test], other[name][test])

    def test_negative_increment_is_preserved_and_has_valid_conclusion(self):
        packet = load_inputs(self.inputs)
        y = packet['brain']
        predictions = {'control': y.copy(), 'model': y.copy(), 'joint': y + 20}
        result = summarize(packet, self.plan, predictions)
        self.assertLess(result['increment']['mean_delta_r2'], 0)
        self.assertLess(result['scores']['joint']['mean_r2'], 0)
        self.assertEqual(expected_conclusion(result)['interval_result'], 'negative_interval')
        self.assertFalse(expected_conclusion(result)['causal_effect_established'])

    def test_hash_binding_and_split_binding(self):
        path = self.inputs / 'controls.npy'
        c = np.load(path)
        c[0, 0] += 1
        np.save(path, c)
        with self.assertRaisesRegex(IncrementalError, 'hash'):
            load_inputs(self.inputs)

    def test_alternative_control_choices_have_separate_references(self):
        packet = load_inputs(self.inputs)
        results = []
        for control in ('word_count', 'position', 'word_count+position'):
            plan = {**self.plan, 'control_set': control}
            _, _, summary = compute(packet, plan)
            self.assertEqual(summary['control_set'], control)
            results.append(summary['scores']['control']['mean_r2'])
        self.assertEqual(len(set(results)), 3)

    def test_output_reordering_is_valid_forged_claim_and_predictions_fail(self):
        expected, actual = self.root / 'expected', self.root / 'actual'
        run_analysis(self.inputs, expected, self.plan)
        run_analysis(self.inputs, actual, self.plan)
        arrays = read_predictions(actual, (48, 4))
        arrays['stimulus_ids'] = arrays['stimulus_ids'][::-1]
        arrays['neuroid_ids'] = arrays['neuroid_ids'][::-1]
        for name in ('control', 'model', 'joint'):
            arrays[name] = arrays[name][::-1, ::-1]
        np.savez(actual / 'results/predictions.npz', **arrays)
        self.assertTrue(compare(actual, expected, (48, 4))['passed'])
        conclusion = read_json(actual / 'conclusion.json')
        conclusion['causal_effect_established'] = True
        write_json(actual / 'conclusion.json', conclusion)
        self.assertIn('conclusion.json mismatch', compare(actual, expected, (48, 4))['errors'])
        arrays['joint'] += .2
        np.savez(actual / 'results/predictions.npz', **arrays)
        self.assertIn('joint predictions mismatch', compare(actual, expected, (48, 4))['errors'])

    def test_object_arrays_are_rejected_without_unpickling(self):
        root = self.root / 'bad'
        (root / 'results').mkdir(parents=True)
        values = {name: np.zeros((48, 4)) for name in ('control', 'model', 'joint')}
        np.savez(root / 'results/predictions.npz', **values, stimulus_ids=np.array([object()] * 48), neuroid_ids=np.array(['a','b','c','d']))
        with self.assertRaises(IncrementalError):
            read_predictions(root, (48, 4))

    def test_real_process_lifecycle_is_explicitly_trusted(self):
        reference_submission(self.root / 'submission')
        with patch.dict(os.environ, {'BPB_ALIGNMENT_TRUSTED_LOCAL': '1', 'BPB_OFFICIAL_SCORING': '0'}):
            grade = evaluate(self.inputs, self.root / 'submission', self.root / 'grade', isolation='process', timeout=30)
        self.assertEqual(grade['analysis_success'], 1, grade)
        with patch.dict(os.environ, {'BPB_ALIGNMENT_TRUSTED_LOCAL': '0'}):
            grade = evaluate(self.inputs, self.root / 'submission', self.root / 'untrusted', isolation='process')
        self.assertEqual(grade['state'], 'scoring_failed')
        self.assertIsNone(grade['analysis_success'])

    def test_infrastructure_failure_is_not_an_agent_zero(self):
        reference_submission(self.root / 'submission')
        for number, (exception, state, score) in enumerate([
            (InfrastructureError('container did not start'), 'scoring_failed', None),
            (AnalysisFailure('started program failed'), 'scored', 0),
        ]):
            with patch.dict(os.environ, {'BPB_ALIGNMENT_TRUSTED_LOCAL': '1', 'BPB_OFFICIAL_SCORING': '0'}), \
                 patch('incremental.evaluation.Executor.run', side_effect=exception):
                grade = evaluate(self.inputs, self.root / 'submission', self.root / ('failure-%d' % number), isolation='process')
            self.assertEqual(grade['state'], state)
            self.assertEqual(grade['analysis_success'], score)


if __name__ == '__main__':
    unittest.main()
