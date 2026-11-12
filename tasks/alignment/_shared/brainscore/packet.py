"""Local, hash-checked cache interchange. No downloading, inference or scoring."""
import math
from pathlib import Path

from real_brainscore.common import new_directory, read_json, seal, sha256, write_json
from .registry import digest, require
from .adapters import validate

LIMIT = 512 * 1024 * 1024
INPUT_LIMIT = 8 * 1024 ** 3
JSON_FILES = {'metadata.json', 'provenance.json'}


def array(path):
    import numpy as np
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= INPUT_LIMIT, 'array missing, unsafe or exceeds 8 GiB')
    with path.open('rb') as stream:
        version = np.lib.format.read_magic(stream)
        require(version in ((1, 0), (2, 0)), 'unsupported numpy format')
        reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        shape, _, dtype = reader(stream)
        require(not dtype.hasobject and dtype.kind in 'bf' and 1 <= len(shape) <= 2
                and all(d > 0 for d in shape) and math.prod(shape) * dtype.itemsize <= INPUT_LIMIT, 'unsafe array shape/dtype')
        require(stream.tell() + math.prod(shape) * dtype.itemsize == path.stat().st_size, 'array size does not match header')
    return np.load(path, allow_pickle=False, mmap_mode='r')


def load(root, registry):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'packet must be a regular directory')
    root = root.resolve()
    manifest = read_json(root / 'manifest.json')
    require(isinstance(manifest, dict) and manifest.get('schema') == 'bpb-bs-cache/1', 'unsupported cache schema')
    require(type(manifest.get('synthetic_only')) is bool, 'explicit synthetic_only required')
    bid, cid = manifest.get('benchmark_id'), manifest.get('candidate_id')
    require(bid in registry['benchmarks'] and cid in registry['candidates'], 'unknown benchmark/candidate')
    benchmark = registry['benchmarks'][bid]
    family = registry['families'][benchmark['family_id']]
    require(cid in family['candidate_ids'], 'candidate is not in the family whitelist')
    for field in ('dataset_family_id', 'stimulus_family_id'):
        require(manifest.get(field) == family[field], 'packet family identity differs')
    behavior = benchmark['adapter'] == 'language-behavior'
    expected = JSON_FILES | {'candidate.npy', 'responses.npy', 'response_valid.npy'}
    if behavior:
        expected |= {'candidate_valid.npy'}
    files = manifest.get('files')
    require(isinstance(files, dict) and set(files) == expected, 'packet inventory must contain only declared public inputs')
    actual = set()
    for path in root.rglob('*'):
        require(not path.is_symlink() and path.is_file(), 'packet entries must be flat regular files')
        actual.add(path.name)
    require(actual == expected | {'manifest.json'}, 'packet inventory differs')
    for name, record in files.items():
        path = root / name
        require(path.stat().st_size <= INPUT_LIMIT, 'packet member exceeds limit')
        require(record == {'bytes': path.stat().st_size, 'sha256': sha256(path)}, 'packet content differs: ' + name)
    provenance = read_json(root / 'provenance.json')
    require(isinstance(provenance, dict), 'invalid provenance')
    fields = {'upstream_commit', 'benchmark_version', 'source_files', 'candidate_configuration_sha256', 'dependency_lock_sha256', 'image_digest'}
    require(set(provenance) == fields, 'provenance fields differ')
    if manifest['synthetic_only']:
        require(all(value is None for value in provenance.values()), 'synthetic fixtures cannot claim official provenance')
    else:
        require(provenance['upstream_commit'] == family['upstream_commit'], 'packet upstream commit differs')
        require(type(provenance['benchmark_version']) is int and provenance['benchmark_version'] > 0, 'missing benchmark version')
        require(isinstance(provenance['source_files'], dict) and provenance['source_files'], 'original file hashes required')
        for field, value in provenance['source_files'].items():
            require(value is not None, 'missing original file hash')
            digest(value, field)
        for field in ('candidate_configuration_sha256', 'dependency_lock_sha256'):
            require(provenance[field] is not None, 'missing ' + field)
            digest(provenance[field], field)
        import re
        require(isinstance(provenance['image_digest'], str) and re.fullmatch('sha256:[0-9a-f]{64}', provenance['image_digest']), 'missing image digest')
    metadata = read_json(root / 'metadata.json')
    require(isinstance(metadata, dict), 'invalid metadata')
    if not manifest['synthetic_only']:
        from .models import configuration
        from .protocols import fingerprint, specification
        spec = specification(bid)
        config = metadata.get('candidate_configuration', {})
        require({key: value for key, value in config.items() if key != 'local_files'} == configuration(registry, bid, cid),
                'candidate configuration differs from fixed binding')
        require(fingerprint(config) == provenance['candidate_configuration_sha256'], 'candidate configuration provenance differs')
        require(metadata.get('protocol', {}).get('official_specification') == spec, 'official protocol provenance differs')
        require(provenance['benchmark_version'] == spec['benchmark_version'], 'benchmark version provenance differs')
        env = registry['environments'][family['ecosystem']]
        require(env['dependency_lock_sha256'] is not None and provenance['dependency_lock_sha256'] == env['dependency_lock_sha256'],
                'dependency lock provenance differs')
        require(env['image_digest'] is not None and provenance['image_digest'] == env['image_digest'], 'worker image provenance differs')
    arrays = {name[:-4]: array(root / name) for name in files if name.endswith('.npy')}
    aligned = validate(metadata, arrays, benchmark)
    return {'root': root, 'manifest': manifest, 'manifest_sha256': sha256(root / 'manifest.json'),
            'metadata': metadata, 'provenance': provenance, 'arrays': arrays, 'aligned': aligned,
            'verification_scope': 'local-cache-contract-only', 'official_equivalence': 'not-verified'}


def save_fixture(root, registry, benchmark_id, candidate_id, metadata, arrays):
    """Test fixture writer only; synthetic caches cannot claim official provenance."""
    provenance = {field: None for field in ('upstream_commit', 'benchmark_version', 'source_files',
                  'candidate_configuration_sha256', 'dependency_lock_sha256', 'image_digest')}
    return save(root, registry, benchmark_id, candidate_id, metadata, arrays, provenance, synthetic=True)


def save(root, registry, benchmark_id, candidate_id, metadata, arrays, provenance, synthetic=False):
    """Seal a prepared local cache. This never grants official or Agent acceptance."""
    import numpy as np
    benchmark = registry['benchmarks'][benchmark_id]
    family = registry['families'][benchmark['family_id']]
    validate(metadata, arrays, benchmark)
    root = new_directory(root)
    write_json(root / 'metadata.json', metadata)
    write_json(root / 'provenance.json', provenance)
    expected = {'candidate', 'responses', 'response_valid'} | ({'candidate_valid'} if benchmark['adapter'] == 'language-behavior' else set())
    require(set(arrays) == expected, 'fixture array inventory differs')
    for name, values in arrays.items():
        np.save(root / (name + '.npy'), values, allow_pickle=False)
    seal(root, {'schema': 'bpb-bs-cache/1', 'synthetic_only': synthetic, 'benchmark_id': benchmark_id, 'candidate_id': candidate_id,
                'dataset_family_id': family['dataset_family_id'], 'stimulus_family_id': family['stimulus_family_id']})
    return load(root, registry)
