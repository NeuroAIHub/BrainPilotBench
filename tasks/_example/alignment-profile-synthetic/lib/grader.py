"""Data-only scorer: reads structured answers and replays an operator-owned journal.

No submitted code is executed. Free prose is not scored or declared verified.
"""
import argparse
import math
import os
from pathlib import Path
import sys
from core import (ANSWER_SCHEMA, ContractError, PROFILE, TASK_ID, VERSION, digest, expected_answers,
                  load_packet, read_json, write_json)
from service import replay


def equivalent(actual, expected):
    if isinstance(expected, float):
        return type(actual) in (int, float) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-9)
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all(equivalent(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        if all(isinstance(v, str) for v in expected):
            return isinstance(actual, list) and all(isinstance(v, str) for v in actual) and len(actual) == len(expected) and set(actual) == set(expected)
        return isinstance(actual, list) and len(actual) == len(expected) and all(equivalent(a, b) for a, b in zip(actual, expected))
    return type(actual) is type(expected) and actual == expected


def score(bundle, evidence_root):
    bundle = Path(bundle).resolve()
    report = {'schema': 'bpb-profile-grade/1', 'synthetic_only': True, 'state': 'scoring_failed',
              'profile_analysis_success': None, 'question_results': [], 'prose_review': 'not_assessed'}
    artifacts = bundle / 'artifacts'
    try:
        meta = read_json(bundle / 'meta.json')
        if meta.get('taskId') != TASK_ID or meta.get('taskVersion') != VERSION or not meta.get('agent'):
            raise ContractError('submission identity mismatch')
        if artifacts.is_symlink():
            raise ContractError('artifact directory symlink')
        for path in artifacts.rglob('*'):
            if path.is_symlink():
                raise ContractError('artifact symlink')
        answers = read_json(artifacts / 'answers.json')
        prose = artifacts / 'report.md'
        if not prose.is_file() or not 0 < prose.stat().st_size <= 200_000:
            raise ContractError('missing or oversized report')
        if not isinstance(answers, dict) or set(answers) != {'schema', 'protocol_id', 'packet_sha256', 'questions'}:
            raise ContractError('invalid answer envelope')
        if answers['schema'] != ANSWER_SCHEMA or answers['protocol_id'] != PROFILE or not isinstance(answers['questions'], dict) or set(answers['questions']) != {'q1', 'q2', 'q3', 'q4'}:
            raise ContractError('all four questions are required')
    except (ContractError, ValueError, TypeError, AttributeError, OSError) as exc:
        report.update(state='submission_invalid', error=str(exc))
        return report
    try:
        if not evidence_root:
            raise ContractError('operator evidence directory is required')
        root = Path(evidence_root).resolve()
        if root == bundle or bundle in root.parents:
            raise ContractError('authoritative evidence cannot come from the submitted bundle')
        packet = load_packet(root / 'packet.json')
        engine, records = replay(packet, root / 'journal.jsonl')
        by_id = {r['run_id']: r for r in records}
        expected = expected_answers(packet, engine.selected or packet['baseline_layer'])
        top = expected['q1']['highest_layers'][0]
        bindings = {
            'q1': ('profile', {'dataset_id': packet['source_id']}),
            'q2': ('compare', {'layer_a': top, 'layer_b': packet['baseline_layer']}),
            'q3': ('stability', {'layer': top}),
            'q4': ('generalization', {}),
        }
        for key, truth in expected.items():
            answer = answers['questions'][key]
            valid_shape = isinstance(answer, dict) and set(answer) == {'answer', 'evidence'}
            evidence = answer.get('evidence') if valid_shape else None
            valid_evidence = (isinstance(evidence, list) and len(evidence) >= 1 and
                              all(isinstance(i, str) and i in by_id for i in evidence))
            name, args = bindings[key]
            matched = valid_evidence and any(by_id[i]['tool'] == name and by_id[i]['arguments'] == args for i in evidence)
            content_ok = valid_shape and equivalent(answer['answer'], truth)
            passed = answers['packet_sha256'] == digest(packet) and bool(matched) and content_ok
            if key == 'q4' and engine.selected is None:
                passed = False
            report['question_results'].append({'question': key, 'passed': passed,
                                                'content_matches': content_ok, 'evidence_matches': bool(matched)})
        passed = sum(r['passed'] for r in report['question_results'])
        report.update(state='scored', profile_analysis_success=int(passed == 4), four_question_score=passed / 4,
                      packet_sha256=digest(packet), journal_sha256=digest(records),
                      frozen_layer=engine.selected, evidence_source='operator_directory_not_submission',
                      journal_authentication='not_provided_by_hash_chain; operator must isolate directory')
    except Exception as exc:
        report.update(state='scoring_failed', error=f'{type(exc).__name__}: {exc}')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    report = score(args.bundle, os.environ.get('BPB_ALIGNMENT_PROFILE_EVIDENCE_DIR'))
    write_json(args.bundle / 'alignment-profile-score.json', report)
    if report['state'] == 'scored':
        print('>>>>> BPB_SCORES')
        print('{"profile_analysis_success": %d, "four_question_score": %.2f}' % (report['profile_analysis_success'], report['four_question_score']))
        print('<<<<< BPB_SCORES')
    else:
        print('alignment profile evaluator: ' + report['state'], file=sys.stderr)


if __name__ == '__main__':
    main()
