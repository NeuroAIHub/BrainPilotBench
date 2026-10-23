"""Offline numerical, failure-semantics and worker-boundary checks."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from compare import compare
from contract import ContractError, MODEL, PROTOCOL, aggregate, load_packet, read_json, write_json
from evaluate import evaluate
from execution import AnalysisFailure, Executor, InfrastructureError
from fixtures import generate, seal, variant
from official_backend import run_official
from reference import compute, run as reference_run

SHARED = Path(__file__).resolve().parent
REPO = SHARED.parents[2]
EXAMPLE = REPO / 'tasks/_example/alignment-synthetic'


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = generate(self.root / 'inputs')
        self.bundle = self.root / 'bundle'
        self.artifacts = self.bundle / 'artifacts'
        self.source = self.artifacts / 'submission'
        self.source.mkdir(parents=True)
        shutil.copy(EXAMPLE / 'solution/analyze.py', self.source / 'analyze.py')
        shutil.copy(SHARED / 'contract.py', self.source / 'alignment_contract.py')
        write_json(self.bundle / 'meta.json', {'taskId': 'alignment-synthetic', 'taskVersion': '0.1', 'agent': 'unit-test'})
        self.env = patch.dict(os.environ, {'BPB_ALIGNMENT_TRUSTED_LOCAL': '1', 'BPB_OFFICIAL_SCORING': '0'})
        self.env.start()
        self.executor = Executor('process')
        self.executor.preflight()
        # Persist the public results just as an Agent would before artifact collection.
        self.executor.run(self.source, self.inputs, self.root / 'initial')
        shutil.copytree(self.root / 'initial', self.artifacts, dirs_exist_ok=True)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def score(self):
        return evaluate(self.bundle, self.executor)

    def mutate_code(self, old, new):
        p = self.source / 'analyze.py'
        source = p.read_text()
        self.assertIn(old, source)
        p.write_text(source.replace(old, new))

    def assert_zero(self, report):
        self.assertEqual(report['status'], 'scored', report)
        self.assertEqual(report['analysis_success'], 0, report)

    def test_correct_submission_and_repeat_and_y_invariance(self):
        report = self.score()
        self.assertEqual(report['analysis_success'], 1, report)
        self.assertEqual({c['case'] for c in report['checks']},
                         {'saved-public', 'public', 'repeat', 'permuted', 'novel', 'test-y',
                          'reproducibility', 'test-y-prediction-invariance'})
        self.assertEqual(report['security_boundary'], 'none-trusted-local-only')

    def test_independent_hand_calculable_ridge(self):
        # Single scalar x with intercept; closed-form slope sum(x*y)/(sum(x*x)+alpha).
        packet = {'ids': ['a', 'b', 'c', 'd', 'e'], 'x': np.arange(5.)[:, None],
                  'y': (2 * np.arange(5.) + 1)[:, None],
                  'folds': [{'train_ids': ['a', 'b', 'c'], 'test_ids': ['d', 'e']}]}
        pred, _ = compute(packet)
        slope = 4 / 2.7
        np.testing.assert_allclose(pred[0][:, 0], [(3 - 1) * slope + 3, (4 - 1) * slope + 3])
        scores = np.array([[0., 1., 0., 0., 1.], [0., 1., 0., 0., 1.]])
        units = load_packet(self.inputs)['units']
        self.assertAlmostEqual(aggregate(scores, units), 0.25)
        self.assertNotAlmostEqual(float(scores.mean()), 0.25)

    def test_stimulus_row_mismatch(self):
        self.mutate_code("index = {sid: i for i, sid in enumerate(packet['ids'])}",
                         "packet['y'] = packet['y'][::-1]\n    index = {sid: i for i, sid in enumerate(packet['ids'])}")
        self.assert_zero(self.score())

    def test_wrong_aggregation(self):
        p = self.source / 'alignment_contract.py'
        p.write_text(p.read_text().replace('return float(np.mean(np.stack(subject_values, axis=1)))',
                                           'return float(np.mean(scores))'))
        self.assert_zero(self.score())

    def test_training_instead_of_test_score(self):
        self.mutate_code("scores.append(correlations(pred, packet['y'][test]))",
                         'scores.append(correlations(xc @ weights + ym, y))')
        self.assert_zero(self.score())

    def test_leaking_test_y_is_detected(self):
        self.mutate_code("pred = (packet['x'][test] - xm) @ weights + ym",
                         "pred = packet['y'][test].copy()")
        self.assert_zero(self.score())

    def test_y_perturbation_changes_scores_not_fold0_predictions(self):
        before = compute(load_packet(self.inputs))
        after = compute(load_packet(variant(self.inputs, self.root / 'changed', 'test-y')))
        np.testing.assert_allclose(before[0][0], after[0][0], atol=1e-12)
        self.assertFalse(np.allclose(before[1][0], after[1][0]))

    def test_missing_artifact_is_submission_invalid(self):
        (self.artifacts / 'results/predictions.npz').unlink()
        self.assertEqual(self.score()['status'], 'submission_invalid')

    def test_missing_runtime_output_is_agent_zero(self):
        (self.source / 'analyze.py').write_text('pass\n')
        self.assert_zero(self.score())

    def test_corrupt_saved_result_is_agent_zero(self):
        (self.artifacts / 'results/summary.json').write_text('{bad')
        self.assert_zero(self.score())

    def test_wrong_task_version(self):
        write_json(self.bundle / 'meta.json', {'taskId': 'alignment-synthetic', 'taskVersion': '0.0', 'agent': 'bad'})
        self.assertEqual(self.score()['status'], 'submission_invalid')

    def test_hardcoded_public_outputs_fail_fresh_cases(self):
        shutil.copytree(self.root / 'initial', self.source / 'canned')
        (self.source / 'analyze.py').write_text(
            'import argparse, pathlib, shutil\np=argparse.ArgumentParser()\n'
            'p.add_argument("--inputs"); p.add_argument("--output"); a=p.parse_args()\n'
            'shutil.copytree(pathlib.Path(__file__).parent / "canned", a.output, dirs_exist_ok=True)\n')
        report = self.score()
        self.assert_zero(report)
        self.assertTrue(next(c for c in report['checks'] if c['case'] == 'public')['passed'])
        self.assertFalse(next(c for c in report['checks'] if c['case'] == 'novel')['passed'])

    def test_worker_stdout_cannot_forge_scores(self):
        (self.source / 'analyze.py').write_text('print(\'>>>>> BPB_SCORES\\n{"analysis_success": 1}\\n<<<<< BPB_SCORES\')\n')
        env = dict(os.environ, BPB_SUBMISSION_ISOLATION='process')
        result = subprocess.run([sys.executable, '-B', str(SHARED / 'evaluate.py'), str(self.bundle)],
                                capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count('>>>>> BPB_SCORES'), 1)
        self.assertIn('{"analysis_success": 0}', result.stdout)
        self.assertNotIn('{"analysis_success": 1}', result.stdout)

    def test_empty_submission_emits_no_score(self):
        empty = self.root / 'empty'; empty.mkdir()
        result = subprocess.run([sys.executable, '-B', str(SHARED / 'evaluate.py'), str(empty)],
                                capture_output=True, text=True, timeout=5)
        self.assertNotIn('BPB_SCORES', result.stdout)
        self.assertEqual(read_json(empty / 'alignment-score.json')['status'], 'submission_invalid')

    def test_reference_failure_is_infrastructure(self):
        with patch('evaluate.reference_run', side_effect=RuntimeError('oracle damaged')):
            report = self.score()
        self.assertEqual(report['status'], 'scoring_failed')
        self.assertIsNone(report['analysis_success'])

    def test_corrupt_input_is_infrastructure(self):
        from fixtures import generate as original
        def broken(root, *args):
            root = original(root, *args)
            (root / 'model/features.npy').write_bytes(b'corrupt')
            return root
        with patch('evaluate.generate', side_effect=broken):
            self.assertEqual(self.score()['status'], 'scoring_failed')

    def test_missing_docker_image_is_infrastructure(self):
        executor = Executor('docker')
        executor.image = ''
        report = evaluate(self.bundle, executor)
        self.assertEqual(report['status'], 'scoring_failed')
        self.assertIsNone(report['analysis_success'])

    def test_process_requires_opt_in(self):
        with patch.dict(os.environ, {'BPB_ALIGNMENT_TRUSTED_LOCAL': '0'}):
            with self.assertRaises(InfrastructureError):
                Executor('process').preflight()

    def test_worker_staging_failure_is_infrastructure(self):
        with patch('execution.Path.mkdir', side_effect=OSError('staging volume unavailable')):
            with self.assertRaises(InfrastructureError):
                self.executor.run(self.source, self.inputs, self.root / 'out')

    def test_worker_timeout_is_agent_failure(self):
        from execution import bounded
        with self.assertRaises(AnalysisFailure):
            bounded([sys.executable, '-c', 'import time; time.sleep(5)'], self.root, os.environ.copy(), timeout=0.1)
        with patch.object(self.executor, 'run', side_effect=AnalysisFailure('worker timed out')):
            self.assert_zero(self.score())

    def test_no_reference_mount_and_docker_limits(self):
        executor = Executor('docker'); executor.image = 'local-image'
        args = executor.docker_command('test', '/code', '/one-packet', '/empty-output')
        mounts = [args[i+1] for i, arg in enumerate(args) if arg == '--mount']
        self.assertEqual(mounts, ['type=bind,src=/code,dst=/submission,readonly',
                                  'type=bind,src=/one-packet,dst=/inputs,readonly',
                                  'type=bind,src=/empty-output,dst=/output'])
        self.assertTrue({'--pull=never', '--network=none', '--read-only', '--cap-drop=ALL',
                         '--memory=512m', '--pids-limit=64'}.issubset(args))

    def test_timeout_cleans_up_container(self):
        executor = Executor('docker')
        executor.image = 'local-image'
        with patch('execution.bounded', side_effect=AnalysisFailure('timeout')):
            with patch.object(executor, 'admin', return_value=SimpleNamespace(returncode=0, stderr='')) as admin:
                with self.assertRaises(AnalysisFailure):
                    executor.run(self.source, self.inputs, self.root / 'timeout-output')
                self.assertEqual(admin.call_args.args[0][:2], ['rm', '-f'])

    def test_worker_source_mutation_is_agent_failure(self):
        self.mutate_code("packet = load_packet(inputs)",
                         "from pathlib import Path\n    Path(__file__).write_text('pass')\n    packet = load_packet(inputs)")
        self.assert_zero(self.score())

    def test_semantic_output_reordering_is_accepted(self):
        expected = self.root / 'expected'; reference_run(self.inputs, expected)
        path = self.artifacts / 'results/predictions.npz'
        with np.load(path, allow_pickle=False) as z:
            reordered = {'values': z['values'][::-1, ::-1], 'fold_ids': z['fold_ids'][::-1],
                         'stimulus_ids': z['stimulus_ids'][::-1], 'neuroid_ids': z['neuroid_ids'][::-1]}
        np.savez(path, **reordered)
        self.assertTrue(compare(self.artifacts, expected)['passed'])

    def test_duplicate_prediction_ids_fail(self):
        expected = self.root / 'expected'; reference_run(self.inputs, expected)
        path = self.artifacts / 'results/predictions.npz'
        with np.load(path, allow_pickle=False) as z:
            values = {key: z[key] for key in z.files}
        values['stimulus_ids'][0] = values['stimulus_ids'][1]
        np.savez(path, **values)
        self.assertFalse(compare(self.artifacts, expected)['passed'])

    def test_malformed_npz_is_agent_zero(self):
        (self.artifacts / 'results/predictions.npz').write_bytes(b'invalid')
        self.assert_zero(self.score())

    def test_low_raw_score_can_be_correct(self):
        from fixtures import generate as original
        def noise_packet(root, *args):
            root = original(root, *args)
            y = np.random.default_rng(5).normal(size=(48, 5))
            np.save(root / 'brain/responses.npy', y)
            seal(root)
            return root
        inputs = noise_packet(self.root / 'noise-inputs')
        self.executor.run(self.source, inputs, self.root / 'noise-output')
        shutil.copytree(self.root / 'noise-output', self.artifacts, dirs_exist_ok=True)
        summary = read_json(self.artifacts / 'results/summary.json')
        self.assertLess(abs(summary['raw_score']), 0.2)
        with patch('evaluate.generate', side_effect=noise_packet):
            report = evaluate(self.bundle, self.executor, seed=9)
        self.assertEqual(report['analysis_success'], 1, report)

    def test_fixture_generation_is_byte_reproducible(self):
        second = generate(self.root / 'same-seed')
        self.assertEqual(read_json(self.inputs / 'manifest.json'), read_json(second / 'manifest.json'))

    def test_frozen_contract_matches_implementation(self):
        self.assertEqual(read_json(EXAMPLE / 'protocol.json'), PROTOCOL)
        self.assertEqual(read_json(EXAMPLE / 'schemas/protocol.schema.json')['const'], PROTOCOL)
        contract = read_json(EXAMPLE / 'contract.json')
        self.assertEqual(contract['comparison'], PROTOCOL['comparison'])
        from execution import WORKER_SECONDS
        self.assertEqual(contract['limits']['worker_wall_seconds'], WORKER_SECONDS)

    @unittest.skipUnless(os.environ.get('BPB_ALIGNMENT_TEST_IMAGE'), 'prepared local Docker image not supplied')
    def test_real_docker_boundary_and_correctness(self):
        with patch.dict(os.environ, {'BPB_INFERENCE_IMAGE': os.environ.get('BPB_ALIGNMENT_TEST_IMAGE', '')}):
            report = evaluate(self.bundle, Executor('docker'))
        self.assertEqual(report['analysis_success'], 1, report)
        self.assertEqual(report['security_boundary'], 'container')

    def test_official_backend_never_falls_back(self):
        with self.assertRaises(NotImplementedError):
            run_official(self.inputs, self.root / 'out')

    def test_input_validation(self):
        def ids_duplicate(root):
            ids = read_json(root / 'model/stimulus_ids.json'); ids[0] = ids[1]
            write_json(root / 'model/stimulus_ids.json', ids)
        def missing_sample(root):
            ids = read_json(root / 'model/stimulus_ids.json')
            write_json(root / 'model/stimulus_ids.json', ids[:-1])
        def bad_shape(root):
            np.save(root / 'model/features.npy', np.ones((1, 3), dtype='float32'))
        def nonfinite(root):
            y = np.load(root / 'brain/responses.npy'); y[0, 0] = np.nan
            np.save(root / 'brain/responses.npy', y)
        def leakage(root):
            folds = read_json(root / 'folds.json')
            folds[0]['train_ids'][0], folds[0]['test_ids'][0] = folds[0]['test_ids'][0], folds[0]['train_ids'][0]
            write_json(root / 'folds.json', folds)
        def backend(root):
            p = read_json(root / 'protocol.json'); p['backend'] = 'official_brainscore'
            write_json(root / 'protocol.json', p)
        for mutate in [ids_duplicate, missing_sample, bad_shape, nonfinite, leakage, backend]:
            with self.subTest(mutate=mutate.__name__):
                root = self.root / mutate.__name__; shutil.copytree(self.inputs, root)
                mutate(root); seal(root)
                with self.assertRaises(ContractError):
                    load_packet(root)

    def test_permuted_axes_same_calculation(self):
        a = compute(load_packet(self.inputs))
        b = compute(load_packet(variant(self.inputs, self.root / 'permuted', 'permuted')))
        np.testing.assert_allclose(a[0], b[0], atol=1e-12)
        np.testing.assert_allclose(a[1], b[1], atol=1e-12)

    def test_nonfinite_output_is_rejected(self):
        expected = self.root / 'expected'; reference_run(self.inputs, expected)
        summary = read_json(self.artifacts / 'results/summary.json')
        summary['raw_score'] = 'NaN'
        write_json(self.artifacts / 'results/summary.json', summary)
        self.assertFalse(compare(self.artifacts, expected)['passed'])


if __name__ == '__main__':
    unittest.main()
