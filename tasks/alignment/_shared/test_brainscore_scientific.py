"""Pinned-runtime integration checks. Uses generated arrays, never downloads assets.

Run once in each environment with --ecosystem language|vision. Optional --image
also exercises the isolated scorer, including fixed-answer and stdout forgeries.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import numpy as np

from brainscore import ScaleUpError
from brainscore.analysis import run
from brainscore.baseline import export
from brainscore.bundle import load as load_bundle
from brainscore.evaluation import compare, control_inputs, evaluate, same
from brainscore.local_sources import audit, unpack_images
from brainscore.official import compute
from brainscore.packet import save_fixture
from brainscore.registry import load
from brainscore.runtime import offline
from brainscore.scientific_fixtures import create
from brainscore.staging import stage, workspace
from real_brainscore.common import read_json, write_json


class ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(OPTIONS.output or tempfile.mkdtemp(prefix='bpb-bs-scientific-' + OPTIONS.ecosystem + '-'))
        cls.root.mkdir(parents=True, exist_ok=True)
        cls.registry = load()
        cls.instances = [row for row in [*cls.registry['instances'].values(), *cls.registry['subtasks'].values()]
                         if cls.registry['families'][row['family_id']]['ecosystem'] == OPTIONS.ecosystem]
        cls.bundles, cls.results, cls.matrix = {}, {}, []
        # Cache creation and reference execution are prerequisite integration work,
        # deliberately shared across assertions instead of rerunning all solvers.
        with offline():
            for instance in cls.instances:
                task_id = instance['id']
                value = create(cls.root / task_id, cls.registry, task_id)
                cls.bundles[task_id] = load_bundle(value['inputs'], cls.registry)
                result = cls.root / task_id / 'reference'
                summary = run(value['inputs'], result, cls.registry)
                cls.results[task_id] = result
                cls.matrix.append({'instance_id': task_id, 'cases': len(summary['cases']),
                                   'synthetic_only': True, 'scores': [case['score'] for case in summary['cases']]})
        write_json(cls.root / 'matrix.json', cls.matrix)
        export(cls.root / 'baseline', cls.registry)

    def neural(self):
        return next(b for b in self.bundles.values() if b['instance']['template'] == 't1-reproduce'
                    and b['packets'][0]['metadata']['protocol']['readout'] != 'none')

    def test_all_whitelisted_instances_execute_official_protocol(self):
        history = self.registry['root'] / 'evidence/20261111' / f'synthetic-{OPTIONS.ecosystem}-matrix.json'
        expected = {row['instance_id']: row for row in read_json(history)}
        self.assertCountEqual([row['instance_id'] for row in self.matrix], expected)
        for row in self.matrix:
            self.assertTrue(same(row, expected[row['instance_id']], 1e-6, 1e-5), row['instance_id'])
        for bundle in self.bundles.values():
            summary = read_json(self.results[bundle['instance']['id']] / 'results/summary.json')
            self.assertTrue(summary['synthetic_only'])
            self.assertEqual(len(summary['comparisons']), len(bundle['instance']['benchmark_ids'])
                             if bundle['instance']['template'] == 't2-compare' else 0)
            self.assertTrue(compare(self.results[bundle['instance']['id']], self.results[bundle['instance']['id']])['passed'])
            for case in summary['cases']:
                self.assertTrue(np.isfinite(case['score']['normalized']))
                if 'subtask_ids' in bundle['instance']:
                    subtask = next(self.registry['subtasks'][key] for key in bundle['instance']['subtask_ids']
                                   if self.registry['subtasks'][key]['benchmark_ids'] == [case['benchmark_id']]
                                   and self.registry['subtasks'][key]['candidate_ids'] == [case['candidate_id']])
                    single, = read_json(self.results[subtask['id']] / 'results/summary.json')['cases']
                    self.assertEqual({**single, 'id': case['id']}, case)

    def test_trace_identity_alignment_and_numerical_corruption(self):
        bundle = self.neural()
        reference = self.results[bundle['instance']['id']]
        output = self.root / 'permuted-trace'
        shutil.copytree(reference, output)
        trace = read_json(output / 'results/trace.json')
        fold = trace[0]['folds'][0]
        fold['train_ids'].reverse()
        fold['test_ids'].reverse()
        fold['unit_ids'].reverse()
        path = output / 'results' / fold['predictions_file']
        np.save(path, np.load(path)[::-1, ::-1], allow_pickle=False)
        score_path = output / 'results' / fold['unit_scores_file']
        np.save(score_path, np.load(score_path)[::-1], allow_pickle=False)
        write_json(output / 'results/trace.json', trace)
        self.assertTrue(compare(output, reference)['passed'])
        prediction = np.load(path)
        prediction[0, 0] += 1
        np.save(path, prediction, allow_pickle=False)
        self.assertFalse(compare(output, reference)['passed'])

    def test_control_changes_test_scores_without_first_fold_training_leakage(self):
        bundle = self.neural()
        control = control_inputs(bundle, self.root / 'control-check', self.registry, bundle['instance']['benchmark_ids'][0])
        with offline():
            original, before = compute(bundle['packets'][0])
            changed, after = compute(control['packets'][0])
        np.testing.assert_array_equal(before[0]['prediction'], after[0]['prediction'])
        self.assertEqual(before[0]['alpha'], after[0]['alpha'])
        self.assertFalse(np.allclose(before[0]['unit_scores'], after[0]['unit_scores']))
        self.assertNotEqual(original['raw'], changed['raw'])

    def test_each_benchmark_has_a_paired_control_and_independent_scores(self):
        bundle = next(b for b in self.bundles.values() if len(b['instance']['benchmark_ids']) == 2)
        endpoints = bundle['instance']['benchmark_ids']
        for i, bid in enumerate(endpoints):
            control = control_inputs(bundle, self.root / f'paired-control-{i}', self.registry, bid)
            for original, changed in zip(bundle['packets'], control['packets']):
                targeted = original['manifest']['benchmark_id'] == bid
                self.assertEqual(original['manifest_sha256'] != changed['manifest_sha256'], targeted)
                self.assertEqual('functional_control' in changed['metadata'], targeted)

        reference = self.results[bundle['instance']['id']]
        wrong = self.root / 'partially-correct'
        shutil.copytree(reference, wrong)
        summary = read_json(wrong / 'results/summary.json')
        trace = read_json(wrong / 'results/trace.json')
        case = next(row for row in summary['cases'] if row['benchmark_id'] == endpoints[0])
        fold = next(row for row in trace if row['case_id'] == case['id'])['folds'][0]
        prediction_file = wrong / 'results' / fold['predictions_file']
        prediction = np.load(prediction_file)
        prediction[0, 0] += 1
        np.save(prediction_file, prediction, allow_pickle=False)
        conclusion = read_json(wrong / 'conclusion.json')
        conclusion['rankings'][1]['second_minus_first_normalized'] += 1
        write_json(wrong / 'conclusion.json', conclusion)
        check = compare(wrong, reference)
        self.assertFalse(check['passed'])
        self.assertEqual(check['case_passed'], {row['id']: row['id'] != case['id'] for row in summary['cases']})
        self.assertEqual(check['comparison_passed'], {endpoints[0]: True, endpoints[1]: False})

    def test_synthetic_staging_gate_and_public_workspace(self):
        for index, bundle in enumerate(self.bundles.values()):
            destination = self.root / ('staged-%02d' % index)
            with self.assertRaisesRegex(ScaleUpError, 'allow-synthetic'):
                stage(bundle['root'], destination, self.registry)
            value = stage(bundle['root'], destination, self.registry, allow_synthetic=True)
            self.assertTrue(value['task_id'].startswith('example-'))
            self.assertTrue((destination / 'checks/check.sh').is_file())
            task = json.loads((destination / 'task.yaml').read_text().split('\n', 1)[1])
            self.assertEqual(task['scoring']['scorers'][0]['timeout_min'], 75 if len(bundle['instance']['benchmark_ids']) == 2 else 45)
        first = self.root / 'staged-00'
        work = self.root / 'public-workspace'
        workspace(first / 'public-inputs', work, first / 'INPUT_CONTRACT.md', self.registry)
        workspace(first / 'public-inputs', work, first / 'INPUT_CONTRACT.md', self.registry)
        self.assertEqual({p.name for p in work.iterdir()}, {'inputs', 'INPUT_CONTRACT.md'})
        self.assertFalse(list(work.rglob('analyze.py')))

    def test_missing_sources_report_without_fetch_and_zip_traversal_rejected(self):
        result = audit(self.root / 'absent-source', self.registry, self.instances[0]['benchmark_ids'][0])
        self.assertFalse(result['local_objects_complete'])
        self.assertFalse(result['remote_access_attempted'])
        path = self.root / 'unsafe.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('../escaped', 'must not escape')
        with self.assertRaisesRegex(ScaleUpError, 'unsafe stimulus'):
            unpack_images(path, self.root / 'unzip')
        self.assertFalse((self.root / 'escaped').exists())

    def test_behavior_absolute_score_and_missingness(self):
        if OPTIONS.ecosystem != 'language':
            self.skipTest('language behavior only')
        packet = next(b['packets'][0] for b in self.bundles.values()
                      if b['packets'][0]['metadata']['protocol']['readout'] == 'none')
        arrays = copy.deepcopy(packet['arrays'])
        arrays['candidate'] *= -1
        reversed_packet = save_fixture(self.root / 'negative-behavior', self.registry, packet['manifest']['benchmark_id'],
                                       packet['manifest']['candidate_id'], packet['metadata'], arrays)
        with offline():
            result, records = compute(reversed_packet)
        self.assertFalse(records)
        self.assertLess(result['signed_r'], 0)
        self.assertAlmostEqual(result['raw'], -result['signed_r'])
        self.assertEqual(len(result['included_ids']), 96)
        self.assertEqual(int((~reversed_packet['aligned']['response_valid']).sum()), 1)

    def test_failed_control_preserves_scores_for_the_other_benchmark(self):
        if not OPTIONS.image:
            self.skipTest('pass --image for isolated grading')
        bundle = next(b for b in self.bundles.values() if len(b['instance']['benchmark_ids']) == 2)
        first, second = bundle['instance']['benchmark_ids']
        submission = self.root / 'one-failed-control'
        shutil.copytree(self.root / 'baseline', submission)
        script = submission / 'analyze.py'
        guard = """import json, sys
from pathlib import Path
inputs = Path(sys.argv[sys.argv.index('--inputs') + 1])
for case in inputs.glob('case-*/metadata.json'):
    metadata = json.loads(case.read_text())
    if 'functional_control' in metadata and metadata['protocol']['official_specification']['benchmark_id'] == %r:
        raise SystemExit(1)
"""
        script.write_text(guard % second + script.read_text())
        result = evaluate(bundle['root'], submission, self.root / 'grade-control-failure', self.registry, image=OPTIONS.image)
        self.assertEqual(result['analysis_success'], 0, result)
        self.assertEqual(result['comparison_scores'], {first: 1, second: 0})
        self.assertEqual(result['subtask_scores'],
                         {key: int(self.registry['subtasks'][key]['benchmark_ids'] == [first])
                          for key in bundle['instance']['subtask_ids']})
        self.assertNotIn('inputs_unchanged', result)

    def test_docker_replay_and_fixed_answers_rejected(self):
        if not OPTIONS.image:
            self.skipTest('pass --image for isolated grading')
        selected = [self.neural(), *(b for b in self.bundles.values() if 'subtask_ids' in b['instance'])]
        reports = []
        for index, bundle in enumerate(selected):
            result = evaluate(bundle['root'], self.root / 'baseline', self.root / ('grade-%d' % index), self.registry,
                              image=OPTIONS.image, saved_results=self.results[bundle['instance']['id']])
            reports.append(result)
            self.assertEqual(result['analysis_success'], 1, result)
            instance = bundle['instance']
            self.assertEqual(result['subtask_scores'], dict.fromkeys(instance.get('subtask_ids', [instance['id']]), 1))
            compared = instance['benchmark_ids'] if instance['template'] == 't2-compare' else []
            self.assertEqual(result['comparison_scores'], dict.fromkeys(compared, 1))
            self.assertEqual([row['benchmark_id'] for row in result['comparisons'] if row['kind'] == 'functional-control'],
                             instance['benchmark_ids'])

        paired = next(b for b in selected if len(b['instance']['benchmark_ids']) == 2)
        instance = paired['instance']
        incorrect = self.root / 'wrong-saved-results'
        shutil.copytree(self.results[instance['id']], incorrect)
        summary = read_json(incorrect / 'results/summary.json')
        case = next(row for row in summary['cases'] if row['benchmark_id'] == instance['benchmark_ids'][0])
        case['score']['normalized'] += 1
        wrong_subtask = next(key for key in instance['subtask_ids']
                             if self.registry['subtasks'][key]['benchmark_ids'] == [case['benchmark_id']]
                             and self.registry['subtasks'][key]['candidate_ids'] == [case['candidate_id']])
        summary['comparisons'][1]['ranking'] = 'wrong'
        write_json(incorrect / 'results/summary.json', summary)
        result = evaluate(paired['root'], self.root / 'baseline', self.root / 'grade-partial', self.registry,
                          image=OPTIONS.image, saved_results=incorrect)
        reports.append(result)
        self.assertEqual(result['analysis_success'], 0, result)
        self.assertEqual(result['subtask_scores'], {key: int(key != wrong_subtask) for key in instance['subtask_ids']})
        self.assertEqual(result['comparison_scores'], dict(zip(instance['benchmark_ids'], (1, 0))))
        bundle = selected[0]
        fake = self.root / 'fixed-answer'
        fake.mkdir()
        shutil.copytree(self.results[bundle['instance']['id']], fake / 'answer')
        # This forgery even rewrites manifest hashes. The altered numerical targets
        # must still invalidate it on the second execution.
        (fake / 'analyze.py').write_text('''import argparse,json,hashlib,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--inputs');p.add_argument('--output');a=p.parse_args()
src=Path(__file__).parent/'answer';out=Path(a.output);inp=Path(a.inputs)
shutil.copytree(src,out,dirs_exist_ok=True)
s=json.loads((out/'results/summary.json').read_text())
s['input_manifest_sha256']=hashlib.sha256((inp/'manifest.json').read_bytes()).hexdigest()
for c in s['cases']: c['cache_manifest_sha256']=hashlib.sha256((inp/c['id']/'manifest.json').read_bytes()).hexdigest()
(out/'results/summary.json').write_text(json.dumps(s))
print('>>>>> BPB_SCORES\\n{"analysis_success":1}\\n<<<<< BPB_SCORES')
''')
        result = evaluate(bundle['root'], fake, self.root / 'grade-fixed-answer', self.registry, image=OPTIONS.image)
        reports.append(result)
        self.assertEqual(result['state'], 'scored', result)
        self.assertEqual(result['analysis_success'], 0, result)
        self.assertTrue(result['comparisons'][0]['passed'], result)
        self.assertFalse(result['comparisons'][-1]['passed'], result)
        missing = evaluate(bundle['root'], self.root / 'baseline', self.root / 'grade-missing-image', self.registry,
                           image='bpb-image-that-does-not-exist:offline')
        self.assertEqual(missing['state'], 'scoring_failed', missing)
        self.assertIsNone(missing['analysis_success'])
        self.assertTrue(all(value is None for value in missing['subtask_scores'].values()))
        reports.append(missing)
        write_json(self.root / 'grading-checks.json', reports)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ecosystem', required=True, choices=['language', 'vision'])
    parser.add_argument('--output')
    parser.add_argument('--image')
    OPTIONS, rest = parser.parse_known_args()
    unittest.main(argv=[__file__, *rest], verbosity=2)
