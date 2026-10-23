import copy
import io
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / 'lib'))
sys.path.insert(0, str(TASK / 'solution'))
from core import ContractError, PROFILE, TASK_ID, VERSION, canonical, digest, expected_answers, profile, read_json, stability, transfer, validate_packet, write_json
from fixtures import SCENARIOS, generate
from grader import score
from official_backend import load_official_profile
from reference_report import run
from service import Engine, Service, replay, serve


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bpb-profile-test-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def bundle(self, scenario='peak', seed=7, packet=None, selected=None):
        root = self.root / ('case-' + str(len(list(self.root.iterdir()))))
        evidence, bundle = root / 'operator', root / 'bundle'
        packet = packet or generate(seed, scenario)
        write_json(evidence / 'packet.json', packet)
        run(evidence / 'packet.json', evidence / 'journal.jsonl', bundle / 'artifacts', selected=selected)
        write_json(bundle / 'meta.json', {'taskId': TASK_ID, 'taskVersion': VERSION, 'agent': 'scripted-fixture'})
        return bundle, evidence

    def alter_answer(self, bundle, question, field, value):
        path = bundle / 'artifacts/answers.json'
        answer = read_json(path)
        answer['questions'][question]['answer'][field] = value
        write_json(path, answer)

    def test_hand_computed_mean(self):
        packet = generate()
        for ds in packet['datasets'].values():
            for row in ds['rows']:
                row['score'] = int(row['subject'][-1]) / 10 + int(row['block'][-1]) / 100
        p = profile(validate_packet(packet), 'development')
        self.assertAlmostEqual(p['layer_means']['block-0'], .165)
        self.assertAlmostEqual(p['subject_means']['sub-2']['block-0'], .215)

    def test_row_order_does_not_change_profile(self):
        packet = generate()
        other = copy.deepcopy(packet)
        random.Random(99).shuffle(other['datasets']['development']['rows'])
        self.assertEqual(profile(packet, 'development'), profile(other, 'development'))

    def test_fixture_shapes_and_subject_disagreement(self):
        self.assertEqual(expected_answers(generate(scenario='peak'), 'block-3')['q1']['shape'], 'single_peak')
        self.assertEqual(expected_answers(generate(scenario='plateau'), 'block-3')['q1']['shape'], 'plateau')
        self.assertEqual(expected_answers(generate(scenario='flat'), 'block-3')['q1']['shape'], 'flat')
        self.assertEqual(expected_answers(generate(scenario='heterogeneous'), 'block-1')['q3']['representativeness'], 'heterogeneous')
        self.assertEqual(expected_answers(generate(scenario='transfer_change'), 'block-3')['q4']['near_optimality'], 'not_retained')

    def test_hand_computed_subject_gaps_and_removal_influence(self):
        packet = generate()
        for row in packet['datasets']['development']['rows']:
            values = {'block-1': .9, 'block-3': .1} if row['subject'] == 'sub-0' else {'block-1': .2, 'block-3': .4}
            row['score'] = values.get(row['layer'], .1)
        result = stability(packet, 'block-1')
        self.assertEqual(result['subject_highest_layers']['sub-0'], ['block-1'])
        self.assertEqual(result['subject_near_top']['sub-1'], ['block-3'])
        self.assertAlmostEqual(result['subject_gap_to_best']['sub-1'], .2)
        self.assertEqual(result['subject_agreement'], .25)
        removal = result['leave_one_subject_out']['sub-0']
        self.assertEqual(removal['highest_layers'], ['block-3'])
        self.assertAlmostEqual(removal['selected_layer_gap_to_best'], .2)
        self.assertEqual(result['leave_one_subject_out']['sub-1']['selected_layer_gap_to_best'], 0)
        answer = expected_answers(packet, 'block-1')['q3']
        self.assertEqual(answer['influential_subjects'], ['sub-0'])
        self.assertTrue(answer['leave_one_out_sensitive'])
        self.assertEqual(answer['scope'], ['observed_subjects'])

    def test_plateau_winner_flip_is_not_removal_sensitivity(self):
        packet = generate()
        for row in packet['datasets']['development']['rows']:
            values = {'block-1': .41, 'block-3': .40} if row['subject'] == 'sub-0' else {'block-1': .40, 'block-3': .401}
            row['score'] = values.get(row['layer'], .1)
        answer = expected_answers(packet, 'block-1')['q3']
        self.assertEqual(answer['compared_layer'], 'block-1')
        self.assertEqual(answer['subject_highest_layers']['sub-1'], ['block-3'])
        self.assertEqual(answer['leave_one_subject_out']['sub-0']['highest_layers'], ['block-3'])
        self.assertAlmostEqual(answer['leave_one_subject_out']['sub-0']['selected_layer_gap_to_best'], .001)
        self.assertFalse(answer['leave_one_out_sensitive'])
        self.assertEqual(answer['representativeness'], 'broadly_representative')
        self.assertEqual(answer['subject_agreement'], 1)

    def test_hand_computed_confirmation_baseline_difference_and_change(self):
        packet = generate()
        for name, dataset in packet['datasets'].items():
            values = {'block-3': .5, 'block-5': .15} if name == 'development' else {'block-1': .6, 'block-3': .3, 'block-5': .1}
            for row in dataset['rows']:
                row['score'] = values.get(row['layer'], .05)
        result = transfer(packet, 'block-3')
        self.assertAlmostEqual(result['source_difference'], .35)
        self.assertAlmostEqual(result['target_score'], .3)
        self.assertAlmostEqual(result['target_baseline_score'], .1)
        self.assertAlmostEqual(result['target_difference'], .2)
        self.assertAlmostEqual(result['difference_change'], -.15)
        self.assertAlmostEqual(result['target_gap_to_best'], .3)
        answer = expected_answers(packet, 'block-3')['q4']
        self.assertEqual(answer['advantage_conclusion'], 'advantage_retained')
        self.assertEqual(answer['near_optimality'], 'not_retained')
        self.assertEqual(answer['scope'], 'same_subjects_new_material')

    def test_near_optimality_does_not_imply_baseline_advantage(self):
        answer = expected_answers(generate(scenario='advantage_lost'), 'block-3')['q4']
        self.assertEqual(answer['advantage_conclusion'], 'advantage_not_retained')
        self.assertEqual(answer['near_optimality'], 'retained_near_optimal')
        reversed_answer = expected_answers(generate(scenario='advantage_reversed'), 'block-3')['q4']
        self.assertEqual(reversed_answer['advantage_conclusion'], 'advantage_reversed')

    def test_no_development_advantage_cannot_be_called_retained(self):
        packet = generate()
        for row in packet['datasets']['development']['rows']:
            row['score'] = .1
        answer = expected_answers(packet, 'block-3')['q4']
        self.assertGreater(answer['target_difference'], packet['margin'])
        self.assertEqual(answer['advantage_conclusion'], 'no_development_advantage')

    def test_confirmation_threshold_is_not_a_significance_test(self):
        packet = generate()
        for row in packet['datasets']['confirmation']['rows']:
            row['score'] = .22 if row['layer'] == 'block-3' else .2
        answer = expected_answers(packet, 'block-3')['q4']
        self.assertAlmostEqual(answer['target_difference'], .02)
        self.assertEqual(answer['advantage_conclusion'], 'advantage_not_retained')

    def test_confirmation_scores_the_frozen_layer_not_the_development_winner(self):
        bundle, evidence = self.bundle(selected='block-0')
        result = score(bundle, evidence)
        self.assertEqual(result['profile_analysis_success'], 1, result)
        questions = read_json(bundle / 'artifacts/answers.json')['questions']
        self.assertEqual(questions['q3']['answer']['compared_layer'], 'block-3')
        self.assertEqual(questions['q4']['answer']['selected_layer'], 'block-0')
        self.assertLess(questions['q4']['answer']['source_difference'], 0)
        self.assertEqual(questions['q4']['answer']['advantage_conclusion'], 'no_development_advantage')

    def test_subject_and_material_identity_scope_is_enforced(self):
        for mutation in ('subjects', 'blocks', 'shift', 'baseline'):
            packet = generate()
            dataset = packet['datasets']['confirmation']
            if mutation == 'shift':
                packet['shift']['kind'] = 'none'
            elif mutation == 'baseline':
                packet['baseline_layer'] = packet['layers'][0]
            else:
                axis = mutation
                key = 'subject' if axis == 'subjects' else 'block'
                old = dataset[axis][0]
                new = 'unseen-subject' if axis == 'subjects' else packet['datasets']['development']['blocks'][0]
                dataset[axis][0] = new
                for row in dataset['rows']:
                    if row[key] == old:
                        row[key] = new
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_packet(packet)
        packet = generate()
        packet['datasets']['confirmation']['subjects'].reverse()
        validate_packet(packet)  # identities, not array ordering, define the cohort

    def test_q3_q4_forged_new_measurements_fail_separately(self):
        bundle, evidence = self.bundle('subject_driven')
        self.alter_answer(bundle, 'q3', 'influential_subjects', [])
        self.alter_answer(bundle, 'q4', 'target_difference', 99)
        result = score(bundle, evidence)
        self.assertEqual(result['four_question_score'], .5)
        self.assertFalse(result['question_results'][2]['passed'])
        self.assertFalse(result['question_results'][3]['passed'])

    def test_existing_subjects_cannot_be_claimed_as_unseen_subject_generalization(self):
        bundle, evidence = self.bundle()
        self.alter_answer(bundle, 'q3', 'scope', ['unseen_subjects'])
        self.assertEqual(score(bundle, evidence)['four_question_score'], .75)

    def test_previous_protocol_and_answer_versions_are_rejected(self):
        packet = generate()
        packet['protocol_id'] = 'synthetic-profile-descriptive-v1'
        with self.assertRaises(ContractError): validate_packet(packet)
        bundle, evidence = self.bundle()
        path = bundle / 'artifacts/answers.json'
        answer = read_json(path)
        answer['schema'] = 'bpb-profile-answers/1'
        write_json(path, answer)
        self.assertEqual(score(bundle, evidence)['state'], 'submission_invalid')

    def test_all_scenarios_through_mcp_and_grader(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                bundle, evidence = self.bundle(scenario)
                result = score(bundle, evidence)
                self.assertEqual(result['profile_analysis_success'], 1, result)
                self.assertEqual(result['four_question_score'], 1)

    def test_low_alignment_can_be_analyzed_correctly(self):
        packet = generate()
        for ds in packet['datasets'].values():
            for row in ds['rows']:
                row['score'] -= .7
        bundle, evidence = self.bundle(packet=packet)
        self.assertEqual(score(bundle, evidence)['profile_analysis_success'], 1)

    def test_missing_duplicate_nonfinite_or_real_data_rejected(self):
        for mutation in ('missing', 'duplicate', 'nan', 'bool', 'real'):
            packet = generate()
            rows = packet['datasets']['development']['rows']
            if mutation == 'missing': rows.pop()
            if mutation == 'duplicate': rows[0] = rows[1].copy()
            if mutation == 'nan': rows[0]['score'] = float('nan')
            if mutation == 'bool': rows[0]['score'] = True
            if mutation == 'real': packet['synthetic_only'] = False
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_packet(packet)

    def test_confirmation_requires_commit_and_selection_cannot_change(self):
        engine = Engine(generate())
        with self.assertRaises(ContractError): engine.call('generalization', {})
        with self.assertRaises(ContractError): engine.call('profile', {'dataset_id': 'confirmation'})
        engine.call('commit_selection', {'layer': 'block-2'})
        self.assertEqual(engine.call('generalization', {})['selected_layer'], 'block-2')
        with self.assertRaises(ContractError): engine.call('commit_selection', {'layer': 'block-3'})
        with self.assertRaises(ContractError): engine.call('profile', {'dataset_id': 'confirmation'})

    def test_session_resume_preserves_commit(self):
        packet, ledger = self.root / 'packet.json', self.root / 'journal.jsonl'
        write_json(packet, generate())
        service = Service(packet, ledger)
        service.call('commit_selection', {'layer': 'block-1'})
        resumed = Service(packet, ledger, resume=True)
        with self.assertRaises(ContractError): resumed.call('commit_selection', {'layer': 'block-2'})
        self.assertEqual(resumed.call('generalization', {})['result']['selected_layer'], 'block-1')

    def test_reported_number_cannot_override_reference(self):
        bundle, evidence = self.bundle()
        self.alter_answer(bundle, 'q2', 'mean_difference', 99)
        result = score(bundle, evidence)
        self.assertEqual(result['state'], 'scored')
        self.assertEqual(result['four_question_score'], .75)

    def test_significance_claim_and_unmeasured_generalization_rejected(self):
        bundle, evidence = self.bundle()
        self.alter_answer(bundle, 'q2', 'claim_strength', 'statistically_significant')
        self.alter_answer(bundle, 'q4', 'status', 'not_evaluated')
        self.assertEqual(score(bundle, evidence)['four_question_score'], .5)

    def test_no_confirmation_is_a_correct_answer(self):
        bundle, evidence = self.bundle('no_confirmation')
        self.assertEqual(score(bundle, evidence)['profile_analysis_success'], 1)
        answer = read_json(bundle / 'artifacts/answers.json')['questions']['q4']['answer']
        for key in ('target_score', 'target_baseline_score', 'target_difference', 'difference_change', 'target_gap_to_best'):
            self.assertIsNone(answer[key])
        self.assertEqual(answer['advantage_conclusion'], 'not_evaluated')
        self.assertEqual(answer['near_optimality'], 'not_evaluated')
        self.alter_answer(bundle, 'q4', 'advantage_conclusion', 'advantage_retained')
        self.assertEqual(score(bundle, evidence)['four_question_score'], .75)

    def test_ood_cannot_be_inferred_from_layer_outlier(self):
        bundle, evidence = self.bundle()
        self.alter_answer(bundle, 'q4', 'declared_shift', 'layer_outlier')
        self.assertEqual(score(bundle, evidence)['four_question_score'], .75)

    def test_wrong_evidence_type_or_forged_run_id_rejected(self):
        for refs in (['run-9999'], ['run-0001']):
            bundle, evidence = self.bundle()
            path = bundle / 'artifacts/answers.json'
            answer = read_json(path)
            answer['questions']['q2']['evidence'] = refs
            write_json(path, answer)
            self.assertEqual(score(bundle, evidence)['four_question_score'], .75)

    def test_set_order_and_free_prose_not_exact_matched(self):
        bundle, evidence = self.bundle('plateau')
        path = bundle / 'artifacts/answers.json'
        answer = read_json(path)
        answer['questions']['q1']['answer']['near_top_layers'].reverse()
        write_json(path, answer)
        (bundle / 'artifacts/report.md').write_text('A different wording. Free prose still requires human review.\n')
        result = score(bundle, evidence)
        self.assertEqual(result['profile_analysis_success'], 1)
        self.assertEqual(result['prose_review'], 'not_assessed')

    def test_authoritative_journal_tampering_is_infrastructure_failure(self):
        bundle, evidence = self.bundle()
        path = evidence / 'journal.jsonl'
        records = [json.loads(line) for line in path.read_text().splitlines()]
        records[-1]['result']['target_score'] = 99
        path.write_text('\n'.join(canonical(r) for r in records) + '\n')
        self.assertEqual(score(bundle, evidence)['state'], 'scoring_failed')

    def test_rehashed_forged_results_are_recomputed(self):
        packet = generate()
        write_json(self.root / 'packet.json', packet)
        service = Service(self.root / 'packet.json', self.root / 'journal.jsonl')
        service.call('profile', {'dataset_id': 'development'})
        record = service.records[0]
        record['result']['layer_means']['block-0'] = 99
        record['record_sha256'] = digest({k: v for k, v in record.items() if k != 'record_sha256'})
        service.journal.write_text(canonical(record) + '\n')
        with self.assertRaises(ContractError): replay(packet, service.journal)

    def test_no_commit_does_not_become_unscored(self):
        bundle, evidence = self.bundle()
        (evidence / 'journal.jsonl').write_text('')
        result = score(bundle, evidence)
        self.assertEqual(result['state'], 'scored')
        self.assertEqual(result['four_question_score'], 0)

    def test_missing_operator_evidence_is_not_agent_zero(self):
        bundle, _ = self.bundle()
        result = score(bundle, None)
        self.assertEqual(result['state'], 'scoring_failed')
        self.assertIsNone(result['profile_analysis_success'])

    def test_missing_question_or_artifact_is_invalid(self):
        bundle, evidence = self.bundle()
        path = bundle / 'artifacts/answers.json'
        answer = read_json(path)
        del answer['questions']['q4']
        write_json(path, answer)
        self.assertEqual(score(bundle, evidence)['state'], 'submission_invalid')
        path.unlink()
        self.assertEqual(score(bundle, evidence)['state'], 'submission_invalid')

    def test_packet_bound_answers_cannot_be_reused(self):
        a, _ = self.bundle(seed=3)
        b, evidence = self.bundle(seed=99)
        (b / 'artifacts/answers.json').write_bytes((a / 'artifacts/answers.json').read_bytes())
        self.assertEqual(score(b, evidence)['four_question_score'], 0)

    def test_json_nonfinite_duplicate_keys_and_symlinks_rejected(self):
        path = self.root / 'bad.json'
        for text in ('{"score":NaN}', '{"x":1,"x":2}'):
            path.write_text(text)
            with self.assertRaises(ContractError): read_json(path)
        path.write_text('{}')
        link = self.root / 'linked.json'
        link.symlink_to(path)
        with self.assertRaises(ContractError): read_json(link)

    def test_mcp_initialize_tools_errors_and_notification(self):
        write_json(self.root / 'packet.json', generate())
        service = Service(self.root / 'packet.json', self.root / 'journal.jsonl')
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'generalization'}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'unknown'},
        ]
        output = io.StringIO()
        serve(service, io.StringIO('\n'.join(canonical(r) for r in requests)), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 5)
        self.assertIn('error', responses[0])
        self.assertEqual(len(responses[2]['result']['tools']), 6)
        self.assertTrue(responses[3]['result']['isError'])
        self.assertEqual(responses[4]['error']['code'], -32601)

    def test_unknown_tools_parameters_layers_rejected(self):
        engine = Engine(generate())
        for name, args in [('execute_python', {}), ('describe', {'path': '/tmp'}), ('stability', {'layer': 'missing'})]:
            with self.assertRaises(ContractError): engine.call(name, args)

    def test_declared_shift_must_have_distinct_identities(self):
        packet = generate()
        packet['shift']['kind'] = 'new_subjects'
        with self.assertRaises(ContractError): validate_packet(packet)

    def test_malformed_json_uses_parse_error(self):
        write_json(self.root / 'packet.json', generate())
        service = Service(self.root / 'packet.json', self.root / 'journal.jsonl')
        output = io.StringIO()
        serve(service, io.StringIO('not-json\n'), output)
        self.assertEqual(json.loads(output.getvalue())['error']['code'], -32700)

    def test_real_backend_does_not_fall_back(self):
        with self.assertRaises(NotImplementedError): load_official_profile()


if __name__ == '__main__':
    unittest.main()
