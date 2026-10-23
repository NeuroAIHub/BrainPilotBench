"""Fixture tool service plus a small newline-JSON MCP stdio adapter.

Protocol subset: initialize, initialized notification, ping, tools/list, tools/call.
The operator owns the packet and journal; a hash chain is not authentication.
"""
import argparse
import json
import sys
from pathlib import Path
from core import (ContractError, MAX_BYTES, PROFILE, VERSION, canonical, comparison, digest,
                  load_packet, parse_json, profile, stability, transfer)
from fixtures import public_context

PROTOCOL_VERSION = '2025-06-18'
MAX_CALLS = 256


def schema(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}


TOOL_SPECS = [
    {'name': 'describe', 'description': 'Describe the synthetic experiment, units, and confirmation availability.', 'inputSchema': schema()},
    {'name': 'profile', 'description': 'Read all development-layer scores and observed subject/block summaries. Does not interpret the curve.', 'inputSchema': schema({'dataset_id': {'type': 'string'}}, ['dataset_id'])},
    {'name': 'compare', 'description': 'Paired descriptive differences on the development set. No significance test.', 'inputSchema': schema({'layer_a': {'type': 'string'}, 'layer_b': {'type': 'string'}}, ['layer_a', 'layer_b'])},
    {'name': 'stability', 'description': 'Per-subject highest/near-top layers and score gaps, plus leave-one-subject-out removal sensitivity. Describes observed subjects, not unseen-subject generalization.', 'inputSchema': schema({'layer': {'type': 'string'}}, ['layer'])},
    {'name': 'commit_selection', 'description': 'Irreversibly fix one layer for this session before viewing confirmation results.', 'inputSchema': schema({'layer': {'type': 'string'}}, ['layer'])},
    {'name': 'generalization', 'description': 'After selection, compare the frozen layer with the baseline on disjoint confirmation materials from the same subjects. Returns development/confirmation differences, their change and gap to the confirmation maximum, or not_evaluated. Does not establish OOD.', 'inputSchema': schema()},
]
for spec in TOOL_SPECS:
    spec['outputSchema'] = schema({'run_id': {'type': 'string'}, 'packet_sha256': {'type': 'string'}, 'result': {'type': 'object'}}, ['run_id', 'packet_sha256', 'result'])
    spec['annotations'] = {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False, 'openWorldHint': False}


class Engine:
    def __init__(self, packet):
        self.packet = packet
        self.selected = None

    def call(self, name, args):
        spec = next((s for s in TOOL_SPECS if s['name'] == name), None)
        if spec is None or not isinstance(args, dict) or set(args) != set(spec['inputSchema']['required']):
            raise ContractError('unknown tool or unexpected arguments')
        for key, value in args.items():
            if not isinstance(value, str):
                raise ContractError('tool arguments must be strings')
            if key.startswith('layer') and value not in self.packet['layers']:
                raise ContractError('unknown layer')
        if name == 'describe':
            return public_context(self.packet) | {'scope': 'synthetic_only', 'inference': 'descriptive_only'}
        if name == 'profile':
            if args['dataset_id'] != self.packet['source_id']:
                raise ContractError('confirmation is only accessible through generalization after commitment')
            return profile(self.packet, args['dataset_id'])
        if name == 'compare':
            return comparison(self.packet, args['layer_a'], args['layer_b'])
        if name == 'stability':
            return stability(self.packet, args['layer'])
        if name == 'commit_selection':
            if self.selected is not None and self.selected != args['layer']:
                raise ContractError('selection is already frozen')
            self.selected = args['layer']
            return {'selected_layer': self.selected, 'frozen': True}
        if self.selected is None:
            raise ContractError('commit a layer before confirmation')
        return transfer(self.packet, self.selected)


def replay(packet, journal):
    path = Path(journal)
    engine, records = Engine(packet), []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20 * MAX_BYTES:
        raise ContractError('missing or oversized authoritative journal')
    previous = '0' * 64
    for line in path.read_text().splitlines():
        if len(line.encode()) > MAX_BYTES or not line:
            raise ContractError('invalid journal line')
        record = parse_json(line)
        if not isinstance(record, dict):
            raise ContractError('invalid journal record')
        unsigned = {k: v for k, v in record.items() if k != 'record_sha256'}
        expected_id = 'run-%04d' % (len(records) + 1)
        if (set(record) != {'run_id', 'packet_sha256', 'tool', 'arguments', 'result', 'previous_sha256', 'record_sha256'} or
                record['run_id'] != expected_id or record['packet_sha256'] != digest(packet) or
                record['previous_sha256'] != previous or record['record_sha256'] != digest(unsigned)):
            raise ContractError('journal identity/hash chain mismatch')
        result = engine.call(record['tool'], record['arguments'])
        if canonical(result) != canonical(record['result']):
            raise ContractError('journal result does not match recomputation')
        records.append(record)
        if len(records) > MAX_CALLS:
            raise ContractError('journal call limit exceeded')
        previous = record['record_sha256']
    return engine, records


class Service:
    def __init__(self, packet_path, journal, resume=False):
        self.packet = load_packet(packet_path)
        self.journal = Path(journal)
        if resume:
            self.engine, self.records = replay(self.packet, self.journal)
        else:
            self.engine, self.records = Engine(self.packet), []
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with self.journal.open('x'):
                pass

    def call(self, name, args):
        if len(self.records) >= MAX_CALLS:
            raise ContractError('bounded fixture session exhausted')
        result = self.engine.call(name, args)
        record = {'run_id': 'run-%04d' % (len(self.records) + 1), 'packet_sha256': digest(self.packet),
                  'tool': name, 'arguments': args, 'result': result,
                  'previous_sha256': self.records[-1]['record_sha256'] if self.records else '0' * 64}
        record['record_sha256'] = digest(record)
        with self.journal.open('a') as stream:
            stream.write(canonical(record) + '\n')
        self.records.append(record)
        return {key: record[key] for key in ('run_id', 'packet_sha256', 'result')}


def serve(service, incoming, outgoing):
    initialized = False
    while True:
        line = incoming.readline(MAX_BYTES + 1)
        if not line:
            return
        if len(line.encode()) > MAX_BYTES:
            outgoing.write(canonical({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'oversized message'}}) + '\n')
            outgoing.flush()
            return
        request_id = None
        try:
            request = parse_json(line)
        except ContractError:
            outgoing.write(canonical({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'invalid JSON'}}) + '\n')
            outgoing.flush()
            continue
        try:
            if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
                raise ContractError('invalid JSON-RPC request')
            request_id = request.get('id')
            if 'id' not in request:  # Notifications never receive a response.
                continue
            if type(request_id) not in (int, str):
                raise ContractError('invalid request id')
            method, params = request['method'], request.get('params', {})
            if not isinstance(params, dict):
                raise ContractError('invalid params')
            if method == 'initialize':
                if initialized:
                    raise ContractError('already initialized')
                initialized = True
                result = {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'bpb-alignment-profile-fixture', 'version': VERSION},
                          'instructions': 'Synthetic descriptive measurements only. Commit before confirmation. No significance or OOD inference from a score curve.'}
            elif method == 'ping':
                result = {}
            elif not initialized:
                raise ContractError('initialize first')
            elif method == 'tools/list':
                result = {'tools': TOOL_SPECS}
            elif method == 'tools/call':
                try:
                    envelope = service.call(params.get('name'), params.get('arguments', {}))
                    result = {'content': [{'type': 'text', 'text': canonical(envelope)}], 'structuredContent': envelope, 'isError': False}
                except ContractError as exc:
                    result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
            else:
                outgoing.write(canonical({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'unsupported method'}}) + '\n')
                outgoing.flush()
                continue
            response = {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except ContractError as exc:
            response = {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32600, 'message': str(exc)}}
        outgoing.write(canonical(response) + '\n')
        outgoing.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    serve(Service(args.packet, args.journal, args.resume), sys.stdin, sys.stdout)


if __name__ == '__main__':
    main()
