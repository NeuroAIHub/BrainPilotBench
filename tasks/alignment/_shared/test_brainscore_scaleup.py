"""Offline contract regression checks. Fixtures are not Brain-Score acceptance evidence."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from brainscore import ScaleUpError
from brainscore.adapters import align_rows, validate
from brainscore.fixtures import create
from brainscore.packet import load as load_packet, array
from brainscore.registry import DEFAULT_ROOT, blockers, load, summary
from brainscore.scores import normalize
from brainscore.templates import draft
from real_brainscore.common import read_json, write_json

CLI = Path(__file__).with_name('brainscore_cli.py')


class ScaleUpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bpb-bs-contract-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = load()
        for name in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection', 'socket.getaddrinfo'):
            guard = patch(name, side_effect=AssertionError('network forbidden in offline checks'))
            guard.start()
            self.addCleanup(guard.stop)

    def changed_registry(self, name, change):
        destination = self.root / 'registry'
        shutil.copytree(DEFAULT_ROOT, destination)
        path = destination / (name + '.json')
        document = read_json(path)
        change(document)
        write_json(path, document)
        return destination

    def test_vectorized_descriptions_match_scalar_pearson_with_missingness(self):
        from brainscore.analysis import column_correlations, signed_correlation
        rng = np.random.default_rng(17)
        x, y = rng.normal(size=(30, 8)), rng.normal(size=(30, 8))
        x[::3, 0] = np.nan
        y[::5, 0] = np.nan
        x[:, 1] = 4
        y[2:, 2] = np.nan
        actual = column_correlations(x, y)
        for column, value in enumerate(actual):
            expected, count = signed_correlation(x[:, column], y[:, column])
            if expected is None:
                self.assertIsNone(value)
            else:
                self.assertAlmostEqual(value, expected, places=12)

    def test_exact_planned_inventory_and_pilot(self):
        counts = summary(self.registry)
        self.assertEqual((counts['families'], counts['benchmarks'], counts['planned_t1'], counts['planned_t2'], counts['runnable']), (6, 9, 18, 6, 0))
        self.assertEqual(counts['phase_counts'], {'P1': 2, 'P2': 6, 'P3': 10, 'P4': 6})
        pilot = [i for i in self.registry['instances'].values() if i['phase'] == 'P1']
        self.assertEqual({i['candidate_ids'][0] for i in pilot}, {'pixels', 'alexnet'})
        self.assertTrue(all(i['benchmark_ids'] == ['MajajHong2015public.IT-pls'] for i in pilot))

    def test_all_instances_blocked_and_migration_explicit(self):
        for instance in self.registry['instances'].values():
            reasons = blockers(self.registry, instance)
            self.assertIn('acceptance:agent_validation_sha256', reasons)
            self.assertNotIn('environment:dependency_lock_sha256', reasons)
            self.assertNotIn('runtime:official-adapter-and-isolated-grader-pending', reasons)
        migration, = self.registry['migrations']
        target = self.registry['instances'][migration['target_instance_id']]
        self.assertEqual(target['benchmark_ids'], ['Pereira2018.384sentences-ridge'])
        self.assertNotEqual(migration['legacy_upstream_commit'], self.registry['environments']['language']['upstream_commit'])

    def test_commit_mismatch_rejected(self):
        root = self.changed_registry('sources', lambda d: d['families'][0].update(upstream_commit='f' * 40))
        with self.assertRaisesRegex(ScaleUpError, 'commit mismatch'):
            load(root)

    def test_duplicate_scientific_instance_cannot_inflate_count(self):
        def duplicate(document):
            row = copy.deepcopy(document['instances'][0])
            row['id'] += '-copy'
            document['instances'].append(row)
        root = self.changed_registry('instances', duplicate)
        with self.assertRaisesRegex(ScaleUpError, 'duplicate scientific'):
            load(root)

    def test_unknown_candidate_and_fake_promotion_rejected(self):
        root = self.changed_registry('instances', lambda d: d['instances'][0].update(candidate_ids=['unregistered']))
        with self.assertRaisesRegex(ScaleUpError, 'unknown ids'):
            load(root)
        path = root / 'instances.json'
        original = read_json(DEFAULT_ROOT / 'instances.json')
        original['instances'][0]['status'] = 'ready'
        write_json(path, original)
        with self.assertRaisesRegex(ScaleUpError, 'promotion requires'):
            load(root)

    def test_omitted_unresolved_field_cannot_disappear_from_preflight(self):
        root = self.changed_registry('candidates', lambda d: d['candidates'][0].pop('configuration_sha256'))
        with self.assertRaisesRegex(ScaleUpError, 'missing candidate field'):
            load(root)

    def test_registry_cli_needs_no_site_packages(self):
        # -S removes installed site packages, including NumPy, Torch and Brain-Score.
        run = subprocess.run([sys.executable, '-B', '-S', str(CLI), 'validate'], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['planned_t1'], 18)
        probe = subprocess.run([sys.executable, '-B', '-S', '-c',
                                'import sys; sys.path.insert(0, ' + repr(str(CLI.parent)) + '); '
                                'import brainscore_cli; brainscore_cli.load(); '
                                'assert not {"torch", "numpy", "brainscore_vision", "brainscore_language", "transformers"} & set(sys.modules)'],
                               capture_output=True, text=True, timeout=15)
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_preflight_exit_is_distinct_from_structural_failure(self):
        run = subprocess.run([sys.executable, '-B', '-S', str(CLI), 'preflight', '--require-ready'],
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(len(json.loads(run.stdout)['instances']), 24)
        self.assertNotIn('BPB_SCORES', run.stdout)

    def test_drafts_are_reviewable_without_runnable_task_or_answers(self):
        destination = self.root / 'drafts'
        result = draft(self.registry, destination)
        self.assertEqual(result['drafts'], 24)
        self.assertFalse(list(destination.rglob('task.yaml')))
        self.assertFalse(list(destination.rglob('analyze.py')))
        for path in destination.glob('*/contract.draft.json'):
            value = read_json(path)
            self.assertEqual(value['state'], 'draft-not-runnable')
            self.assertTrue(value['blockers'])
            if 'futrell' in value['task_id']:
                self.assertNotIn('fold_ids', value['required_trace'])
                self.assertIn('model_reading_times', value['required_trace'])
            if value['template'] == 't2-compare':
                self.assertEqual(value['comparison']['scope'], 'descriptive')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            draft(self.registry, destination)

    def test_three_local_adapter_contracts_and_missing_value_roundtrip(self):
        for adapter in ('vision-neural', 'language-neural', 'language-behavior'):
            packet = create(self.root / adapter, self.registry, adapter)
            loaded = load_packet(packet['root'], self.registry)
            self.assertTrue(loaded['manifest']['synthetic_only'])
            self.assertEqual(loaded['official_equivalence'], 'not-verified')
            self.assertTrue(np.isnan(loaded['aligned']['responses'][3, 1]))
            self.assertFalse(loaded['aligned']['response_valid'][3, 1])
            expected = np.arange(8.) if adapter == 'language-behavior' else np.arange(24.).reshape(8, 3)
            np.testing.assert_array_equal(loaded['aligned']['candidate'], expected)

    def test_identity_reorder_invariant_and_duplicate_unknown_ids_fail(self):
        values = np.asarray([[3.], [1.], [2.]])
        np.testing.assert_array_equal(align_rows(values, ['c', 'a', 'b'], ['a', 'b', 'c']), [[1.], [2.], [3.]])
        for ids in (['c', 'c', 'b'], ['c', 'a', 'unknown']):
            with self.assertRaises(ScaleUpError):
                align_rows(values, ids, ['a', 'b', 'c'])

    def test_false_missingness_mask_and_silent_zero_fill_fail(self):
        packet = create(self.root / 'inputs', self.registry, 'vision-neural')
        benchmark = self.registry['benchmarks'][packet['manifest']['benchmark_id']]
        arrays = copy.deepcopy(packet['arrays'])
        arrays['response_valid'][3, 1] = True
        with self.assertRaisesRegex(ScaleUpError, 'missingness'):
            validate(packet['metadata'], arrays, benchmark)
        arrays = copy.deepcopy(packet['arrays'])
        arrays['responses'][3, 1] = 0.
        with self.assertRaisesRegex(ScaleUpError, 'missingness'):
            validate(packet['metadata'], arrays, benchmark)

    def test_group_leakage_rejected_without_changing_sample_coverage(self):
        packet = create(self.root / 'inputs', self.registry, 'language-neural')
        benchmark = self.registry['benchmarks'][packet['manifest']['benchmark_id']]
        metadata = copy.deepcopy(packet['metadata'])
        fold = metadata['protocol']['folds'][0]
        fold['train_ids'][0], fold['test_ids'][0] = fold['test_ids'][0], fold['train_ids'][0]
        with self.assertRaisesRegex(ScaleUpError, 'group leakage'):
            validate(metadata, packet['arrays'], benchmark)

    def test_original_integer_groups_and_repeated_stimuli_are_preserved(self):
        packet = create(self.root / 'inputs', self.registry, 'language-neural')
        metadata = copy.deepcopy(packet['metadata'])
        for i, row in enumerate(metadata['presentations']):
            row['source_coordinates']['story'] = i // 2
            row['stimulus_id'] = 'same-stimulus-different-context'
        aligned = validate(metadata, packet['arrays'], self.registry['benchmarks'][packet['manifest']['benchmark_id']])
        self.assertEqual(len(aligned['presentation_ids']), 8)

    def test_behavior_refuses_regression_folds_or_invalid_included_predictions(self):
        packet = create(self.root / 'inputs', self.registry, 'language-behavior')
        benchmark = self.registry['benchmarks'][packet['manifest']['benchmark_id']]
        metadata = copy.deepcopy(packet['metadata'])
        metadata['protocol']['folds'] = [{'id': 'invented'}]
        with self.assertRaisesRegex(ScaleUpError, 'must not invent'):
            validate(metadata, packet['arrays'], benchmark)
        arrays = copy.deepcopy(packet['arrays'])
        arrays['candidate'][0] = np.nan  # reverse row zero is included word seven
        arrays['candidate_valid'][0] = False
        with self.assertRaisesRegex(ScaleUpError, 'included words'):
            validate(packet['metadata'], arrays, benchmark)

    def test_unknown_measurement_semantics_rejected(self):
        packet = create(self.root / 'inputs', self.registry, 'language-neural')
        metadata = copy.deepcopy(packet['metadata'])
        metadata['units'][0]['kind'] = 'neuron'
        with self.assertRaisesRegex(ScaleUpError, 'unit semantics'):
            validate(metadata, packet['arrays'], self.registry['benchmarks'][packet['manifest']['benchmark_id']])

    def test_hash_corruption_extra_files_and_symlinks_rejected(self):
        packet = create(self.root / 'inputs', self.registry, 'vision-neural')
        target = packet['root'] / 'candidate.npy'
        original = target.read_bytes()
        target.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaisesRegex(ScaleUpError, 'content differs'):
            load_packet(packet['root'], self.registry)
        target.write_bytes(original)
        extra = packet['root'] / 'owner-answer.json'
        extra.write_text('{}')
        with self.assertRaisesRegex(ScaleUpError, 'inventory'):
            load_packet(packet['root'], self.registry)
        extra.unlink()
        target.unlink()
        other = self.root / 'external.npy'
        other.write_bytes(original)
        target.symlink_to(other)
        with self.assertRaisesRegex(ScaleUpError, 'regular files'):
            load_packet(packet['root'], self.registry)

    def test_pickle_and_trailing_payload_rejected(self):
        path = self.root / 'object.npy'
        np.save(path, np.asarray([{'unsafe': 'object'}], dtype=object))
        with self.assertRaisesRegex(ScaleUpError, 'unsafe array'):
            array(path)
        np.save(path, np.zeros((2, 2)))
        with path.open('ab') as stream:
            stream.write(b'unexpected trailing payload')
        with self.assertRaisesRegex(ScaleUpError, 'header'):
            array(path)

    def test_fixture_cannot_claim_real_inputs_without_provenance(self):
        packet = create(self.root / 'inputs', self.registry, 'vision-neural')
        manifest = read_json(packet['root'] / 'manifest.json')
        manifest['synthetic_only'] = False
        write_json(packet['root'] / 'manifest.json', manifest)
        with self.assertRaisesRegex(ScaleUpError, 'upstream commit'):
            load_packet(packet['root'], self.registry)

    def test_normalization_preserves_raw_and_unclipped_values(self):
        vision = normalize(-.4, .5, 'vision-explained-variance')
        self.assertAlmostEqual(vision['normalized'], .32)
        self.assertEqual(vision['raw'], -.4)
        language = normalize(-.4, .5, 'language-ceiling')
        self.assertEqual(language['normalized'], 0.)
        self.assertEqual(language['unclipped'], -.8)
        self.assertEqual(normalize(.8, .5, 'language-ceiling')['normalized'], 1.)
        self.assertAlmostEqual(normalize(.8, .5, 'vision-explained-variance')['normalized'], 1.28)
        for raw, ceiling in ((float('nan'), 1.), (.5, 0.), (.5, float('inf')), (1e308, 1e-308)):
            with self.assertRaises(ScaleUpError):
                normalize(raw, ceiling, 'language-ceiling')


if __name__ == '__main__':
    unittest.main()
