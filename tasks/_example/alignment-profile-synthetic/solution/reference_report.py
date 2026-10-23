"""Maintainer scripted baseline. Obtains evidence through the MCP stdio boundary."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

LIB = Path(__file__).resolve().parents[1] / 'lib'
sys.path.insert(0, str(LIB))
from core import ANSWER_SCHEMA, PROFILE, VERSION, canonical, write_json


class Client:
    def __init__(self, packet, journal):
        self.process = subprocess.Popen([sys.executable, '-B', str(LIB / 'service.py'), '--packet', str(packet), '--journal', str(journal)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.sequence = 0
        result = self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'synthetic-baseline', 'version': VERSION}})
        if result['protocolVersion'] != '2025-06-18':
            raise RuntimeError('unsupported MCP version')
        self.process.stdin.write(canonical({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.sequence += 1
        self.process.stdin.write(canonical({'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params or {}}) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('MCP process ended unexpectedly')
        response = json.loads(line)
        if response.get('id') != self.sequence or 'error' in response:
            raise RuntimeError('MCP request failed')
        return response['result']

    def call(self, name, args=None):
        result = self.request('tools/call', {'name': name, 'arguments': args or {}})
        if result.get('isError'):
            raise RuntimeError(result['content'][0]['text'])
        return result['structuredContent']

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()


def run(packet, journal, output, selected=None):
    client = Client(packet, journal)
    try:
        context = client.call('describe')['result']
        layers, margin = context['layers'], context['margin']
        p = client.call('profile', {'dataset_id': context['source_id']})
        values = p['result']['layer_means']
        high = max(values.values())
        top = [l for l in layers if high - values[l] <= 1e-12]
        near = [l for l in layers if high - values[l] <= margin + 1e-12]
        span = high - min(values.values())
        indexes = [layers.index(l) for l in near]
        shape = 'flat' if span <= margin else 'single_peak' if len(near) == 1 else 'plateau' if max(indexes) - min(indexes) + 1 == len(indexes) else 'multiple_high_regions'
        c = client.call('compare', {'layer_a': top[0], 'layer_b': context['baseline_layer']})
        differences = list(c['result']['subject_differences'].values())
        state = 'consistent_advantage' if min(differences) > margin else 'mixed' if min(differences) < -margin and max(differences) > margin else 'no_consistent_advantage'
        st = client.call('stability', {'layer': top[0]})
        client.call('commit_selection', {'layer': selected or top[0]})
        g = client.call('generalization')
        result = g['result']
        q4 = {k: v for k, v in result.items() if k != 'target_layer_means'}
        q4['near_optimality'] = 'not_evaluated' if result['status'] == 'not_evaluated' else 'retained_near_optimal' if result['target_gap_to_best'] <= margin + 1e-12 else 'not_retained'
        q4['advantage_conclusion'] = ('not_evaluated' if result['status'] == 'not_evaluated' else
                                     'no_development_advantage' if result['source_difference'] <= margin + 1e-12 else
                                     'advantage_retained' if result['target_difference'] > margin + 1e-12 else
                                     'advantage_reversed' if result['target_difference'] < -margin - 1e-12 else
                                     'advantage_not_retained')
        subject_result = st['result']
        influential = [subject for subject, removal in subject_result['leave_one_subject_out'].items()
                       if removal['selected_layer_gap_to_best'] > margin + 1e-12]
        answers = {'schema': ANSWER_SCHEMA, 'protocol_id': PROFILE, 'packet_sha256': p['packet_sha256'], 'questions': {
            'q1': {'answer': {'dataset_id': context['source_id'], 'layer_means': values, 'highest_layers': top,
                             'near_top_layers': near, 'range': span, 'shape': shape}, 'evidence': [p['run_id']]},
            'q2': {'answer': {'dataset_id': context['source_id'], 'compared_layer': top[0], 'baseline_layer': context['baseline_layer'],
                             'mean_difference': c['result']['mean_difference'], 'subject_differences': c['result']['subject_differences'],
                             'evidence_state': state, 'claim_strength': 'descriptive_only'}, 'evidence': [c['run_id']]},
            'q3': {'answer': {'dataset_id': context['source_id'], 'compared_layer': top[0],
                             'subject_highest_layers': subject_result['subject_highest_layers'],
                             'subject_near_top': subject_result['subject_near_top'],
                             'subject_gap_to_best': subject_result['subject_gap_to_best'],
                             'subject_agreement': subject_result['subject_agreement'],
                             'leave_one_subject_out': subject_result['leave_one_subject_out'],
                             'representativeness': 'broadly_representative' if subject_result['subject_agreement'] >= .75 else 'heterogeneous',
                             'influential_subjects': influential, 'leave_one_out_sensitive': bool(influential),
                             'scope': subject_result['scope']}, 'evidence': [st['run_id']]},
            'q4': {'answer': q4, 'evidence': [g['run_id']]},
        }}
        output = Path(output)
        write_json(output / 'answers.json', answers)
        (output / 'report.md').write_text('# Synthetic profile report\n\nThis is a scripted baseline, not an Agent or biological result.\n\n'
            + '\n\n'.join(f'{key}: {canonical(value["answer"])}' for key, value in answers['questions'].items())
            + '\n\nAll comparisons are descriptive fixture rules. No statistical significance, equivalence, or real OOD conclusion is claimed.\n')
        return answers
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selected-layer')
    args = parser.parse_args()
    run(args.packet, args.journal, args.output, args.selected_layer)


if __name__ == '__main__':
    main()
