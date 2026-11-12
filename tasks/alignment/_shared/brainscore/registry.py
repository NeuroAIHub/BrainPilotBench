"""Explicit instance whitelist and readiness diagnostics; standard library only."""
from pathlib import Path
import re

from real_brainscore.common import read_json
from . import ScaleUpError

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'brainscore'
ADAPTERS = {'vision-neural', 'language-neural', 'language-behavior'}
EVIDENCE = {'cache_manifest_sha256', 'official_equivalence_sha256', 'isolated_grading_sha256',
            'resource_report_sha256', 'agent_validation_sha256'}


def require(condition, message):
    if not condition:
        raise ScaleUpError(message)


def digest(value, label, size=64):
    require(value is None or isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % size, value),
            label + ': expected null or immutable digest')


def index(rows, label):
    require(isinstance(rows, list) and rows, label + ': expected nonempty list')
    result = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get('id'), str) and row['id'], label + ': missing id')
        require(row['id'] not in result, label + ': duplicate id ' + row['id'])
        result[row['id']] = row
    return result


def distinct(values, allowed, label):
    require(isinstance(values, list) and values and all(isinstance(v, str) for v in values), label + ': expected ids')
    require(len(values) == len(set(values)) and set(values) <= set(allowed), label + ': duplicate/unknown ids')


def candidate_definition(candidate):
    fields = ('id', 'ecosystem', 'model_name', 'binding', 'requires_weights', 'weight_revision',
              'tokenizer_revision', 'layer_mapping', 'preprocessing')
    return {key: candidate[key] for key in fields} | ({'weight_artifact': candidate['weight_artifact']}
                                                     if 'weight_artifact' in candidate else {})


def load(root=DEFAULT_ROOT):
    from .protocols import fingerprint, specification
    root = Path(root)
    sources, candidates, instances = [read_json(root / (name + '.json')) for name in ('sources', 'candidates', 'instances')]
    for document, schema in zip((sources, candidates, instances), ('sources', 'candidates', 'instances')):
        require(isinstance(document, dict) and document.get('schema') == 'bpb-bs-' + schema + '/1', 'unsupported ' + schema + ' schema')
    envs = sources.get('environments')
    require(isinstance(envs, dict) and set(envs) == {'vision', 'language'}, 'separate vision/language environments required')
    for ecosystem, env in envs.items():
        require(env.get('repository') == 'brain-score/' + ecosystem, 'upstream repository differs')
        require(env.get('upstream_commit') is not None, 'upstream commit required')
        digest(env['upstream_commit'], 'upstream commit', 40)
        for field in ('python_version', 'dependency_lock_sha256', 'image_digest'):
            require(field in env, 'missing environment field: ' + field)
        digest(env['dependency_lock_sha256'], 'dependency lock')
        require(env['python_version'] is None or isinstance(env['python_version'], str) and env['python_version'], 'invalid Python version')
        require(env['image_digest'] is None or re.fullmatch('sha256:[0-9a-f]{64}', env['image_digest']), 'invalid image digest')
    candidate_map = index(candidates.get('candidates'), 'candidates')
    for candidate in candidate_map.values():
        require(candidate.get('ecosystem') in envs, 'unknown candidate ecosystem')
        for field in ('requires_weights', 'binding_verified'):
            require(type(candidate.get(field)) is bool, 'missing candidate boolean: ' + field)
        for field in ('model_name', 'binding'):
            require(isinstance(candidate.get(field), str) and candidate[field], 'missing candidate ' + field)
        for field in ('weight_revision', 'tokenizer_revision', 'weight_files_sha256', 'preprocessing_sha256', 'configuration_sha256'):
            require(field in candidate, 'missing candidate field: ' + field)
            digest(candidate[field], field, 40 if field.endswith('revision') else 64)
        require('layer_mapping' in candidate, 'missing layer_mapping')
        mapping = candidate['layer_mapping']
        require(mapping is None or isinstance(mapping, dict) and mapping and all(isinstance(v, str) and v for v in mapping.values()),
                'invalid layer_mapping')
        require(candidate['preprocessing_sha256'] == fingerprint(candidate.get('preprocessing')), 'preprocessing fingerprint differs')
        require(candidate['configuration_sha256'] == fingerprint(candidate_definition(candidate)), 'candidate definition fingerprint differs')
    family_map = index(sources.get('families'), 'families')
    benchmark_map = {}
    for family in family_map.values():
        require(family.get('ecosystem') in envs, 'unknown family ecosystem')
        require(family.get('upstream_commit') == envs[family['ecosystem']]['upstream_commit'], 'family/environment commit mismatch')
        for field in ('dataset_family_id', 'stimulus_family_id'):
            require(isinstance(family.get(field), str) and family[field], 'missing ' + field)
        require(family.get('data_status') in ('deferred-no-download', 'partial-local-verified', 'local-verified'), 'invalid data_status')
        require(family.get('license_status') in ('pending', 'reviewed'), 'invalid license_status')
        require('source_files' in family and 'observed_counts' in family, 'missing source audit fields')
        if family['source_files'] is not None:
            require(isinstance(family['source_files'], dict) and family['source_files'], 'source_files must contain original file hashes')
            for name, value in family['source_files'].items():
                require(isinstance(name, str) and name and value is not None, 'missing source hash')
                digest(value, name)
        require(family['observed_counts'] is None or isinstance(family['observed_counts'], dict) and family['observed_counts']
                and all(type(v) is int and v > 0 for v in family['observed_counts'].values()), 'invalid observed counts')
        distinct(family.get('candidate_ids'), candidate_map, 'family candidates')
        require(all(candidate_map[c]['ecosystem'] == family['ecosystem'] for c in family['candidate_ids']), 'candidate ecosystem mismatch')
        for bid, benchmark in index(family.get('benchmarks'), 'benchmarks').items():
            require(bid not in benchmark_map, 'duplicate benchmark id')
            require(benchmark.get('adapter') in ADAPTERS, 'unknown adapter')
            require(benchmark['adapter'].split('-')[0] == family['ecosystem'], 'adapter ecosystem mismatch')
            for field in ('endpoint', 'measurement_unit'):
                require(isinstance(benchmark.get(field), str) and benchmark[field], 'missing benchmark ' + field)
            require(benchmark.get('readout') in ('pls', 'ridge', 'none'), 'invalid readout')
            behavior = benchmark['adapter'] == 'language-behavior'
            require((benchmark['readout'] == 'none') == behavior, 'behavior has no fitted readout')
            require('split_group' in benchmark and (benchmark['split_group'] is None or isinstance(benchmark['split_group'], str)), 'invalid split_group')
            require(not behavior or benchmark['split_group'] is None, 'behavior has no regression folds')
            expected = 'vision-explained-variance' if family['ecosystem'] == 'vision' else 'language-ceiling'
            require(benchmark.get('normalization') == expected, 'normalization differs from selected adapter')
            require('runtime_version' in benchmark and (benchmark['runtime_version'] is None or type(benchmark['runtime_version']) is int
                    and benchmark['runtime_version'] > 0), 'invalid runtime version')
            require('protocol_sha256' in benchmark, 'missing frozen protocol hash')
            digest(benchmark['protocol_sha256'], 'protocol')
            spec = specification(bid)
            require(benchmark['source_declared_version'] == spec['benchmark_version'] and
                    benchmark['runtime_version'] in (None, spec['benchmark_version']), 'benchmark version differs from frozen protocol')
            require(benchmark['protocol_sha256'] in (None, fingerprint(spec)), 'protocol fingerprint differs')
            benchmark_map[bid] = {**benchmark, 'family_id': family['id']}
    require(instances.get('category') == 'alignment-analysis' and instances.get('metric') == 'analysis_success', 'analysis metric differs')
    instance_map = index(instances.get('instances'), 'instances')
    signatures = set()
    for instance in instance_map.values():
        require(re.fullmatch('alignment-bs-[a-z0-9-]+', instance['id']), 'unsafe task id')
        require(instance.get('family_id') in family_map, 'unknown instance family')
        family = family_map[instance['family_id']]
        distinct(instance.get('benchmark_ids'), [b['id'] for b in family['benchmarks']], 'instance benchmarks')
        distinct(instance.get('candidate_ids'), family['candidate_ids'], 'instance candidates')
        require(instance.get('template') in ('t1-reproduce', 't2-compare'), 'unknown template')
        t1 = instance['template'] == 't1-reproduce'
        require((len(instance['benchmark_ids']) == len(instance['candidate_ids']) == 1) if t1
                else len(instance['candidate_ids']) == 2 and set(instance['benchmark_ids']) == {b['id'] for b in family['benchmarks']},
                'template cardinality differs')
        require(instance.get('phase') in (('P1', 'P2', 'P3') if t1 else ('P4',)), 'invalid implementation phase')
        # This registry revision is a planning whitelist, never a promotion mechanism.
        require(instance.get('status') == 'planned', 'promotion requires a separately validated runnable task')
        require(isinstance(instance.get('acceptance'), dict) and set(instance['acceptance']) == EVIDENCE, 'acceptance fields differ')
        for field, value in instance['acceptance'].items():
            digest(value, field)
        signature = (instance['template'], tuple(sorted(instance['benchmark_ids'])), tuple(sorted(instance['candidate_ids'])))
        require(signature not in signatures, 'duplicate scientific instance')
        signatures.add(signature)
    for migration in instances.get('migrations', []):
        require(migration.get('target_instance_id') in instance_map, 'unknown migration target')
        digest(migration.get('legacy_upstream_commit'), 'legacy commit', 40)
        require(migration.get('status') == 'equivalence-review-pending', 'legacy scores cannot be silently migrated')
    return {'root': root, 'environments': envs, 'families': family_map, 'benchmarks': benchmark_map,
            'candidates': candidate_map, 'instances': instance_map, 'migrations': instances.get('migrations', [])}


def blockers(registry, instance):
    family = registry['families'][instance['family_id']]
    env = registry['environments'][family['ecosystem']]
    result = []
    local_sources_ready = family['data_status'] == 'local-verified' or all(
        registry['benchmarks'][bid].get('local_source_status') == 'local-verified' for bid in instance['benchmark_ids'])
    for field, ready in (('data_status', local_sources_ready),
                         ('license_status', family['license_status'] == 'reviewed'),
                         ('source_files', family['source_files'] is not None), ('observed_counts', family['observed_counts'] is not None)):
        if not ready:
            result.append('source:' + field)
    if str(family.get('data_version_review', '')).startswith('pending:'):
        result.append('source:data_version_review')
    for field in ('python_version', 'dependency_lock_sha256', 'image_digest'):
        if env[field] is None:
            result.append('environment:' + field)
    for bid in instance['benchmark_ids']:
        for field in ('runtime_version', 'protocol_sha256'):
            if registry['benchmarks'][bid][field] is None:
                result.append(bid + ':' + field)
    for cid in instance['candidate_ids']:
        candidate = registry['candidates'][cid]
        fields = ['binding_verified', 'configuration_sha256', 'preprocessing_sha256']
        if candidate['requires_weights']:
            fields += ['weight_files_sha256']
            if not candidate.get('weight_artifact'):
                fields.append('weight_revision')
        if candidate['ecosystem'] == 'language':
            fields.append('tokenizer_revision')
        if any(registry['benchmarks'][bid]['readout'] != 'none' for bid in instance['benchmark_ids']):
            fields.append('layer_mapping')
        result += [cid + ':' + field for field in fields if not candidate[field]]
    result += ['acceptance:' + field for field, value in instance['acceptance'].items() if value is None]
    return result


def summary(registry):
    instances = list(registry['instances'].values())
    return {'families': len(registry['families']), 'benchmarks': len(registry['benchmarks']),
            'planned_t1': sum(i['template'] == 't1-reproduce' for i in instances),
            'planned_t2': sum(i['template'] == 't2-compare' for i in instances), 'runnable': 0,
            'phase_counts': {phase: sum(i['phase'] == phase for i in instances) for phase in ('P1', 'P2', 'P3', 'P4')},
            'data_downloaded_by_this_workflow': False}
