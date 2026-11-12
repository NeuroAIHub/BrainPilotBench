"""One explicit T1/T2 instance binds an exact set of prepared public caches."""
from pathlib import Path
import shutil

from real_brainscore.common import new_directory, read_json, seal, separate_paths, sha256, write_json
from .packet import load as load_packet
from .registry import require
from .protocols import specification


def load(root, registry):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'bundle must be a regular directory')
    root = root.resolve()
    manifest = read_json(root / 'manifest.json')
    require(manifest.get('schema') == 'bpb-bs-instance-inputs/1', 'invalid instance input schema')
    instance = registry['instances'].get(manifest.get('instance_id'))
    require(instance is not None, 'instance is not whitelisted')
    public_instance = {key: instance[key] for key in ('id', 'template', 'benchmark_ids', 'candidate_ids')}
    require(read_json(root / 'instance.json') == public_instance, 'public instance protocol differs from whitelist')
    entries = read_json(root / 'bundle.json')
    require(isinstance(entries, list) and entries, 'missing cache bindings')
    wanted = {(bid, cid) for bid in instance['benchmark_ids'] for cid in instance['candidate_ids']}
    require(len(entries) == len(wanted), 'instance cache count differs')
    actual, packets = set(), []
    for number, entry in enumerate(entries):
        require(entry.get('directory') == 'case-%02d' % number, 'cache directory binding differs')
        packet = load_packet(root / entry['directory'], registry)
        identity = packet['manifest']['benchmark_id'], packet['manifest']['candidate_id']
        require(identity not in actual and identity in wanted, 'duplicate or unexpected instance cache')
        require(entry.get('manifest_sha256') == packet['manifest_sha256'], 'cache binding hash differs')
        require(packet['metadata']['protocol'].get('official_specification') == specification(identity[0]), 'scientific protocol is not frozen')
        require('candidate_configuration' in packet['metadata'], 'candidate configuration is not frozen')
        actual.add(identity)
        packets.append(packet)
    require(type(manifest.get('synthetic_only')) is bool and
            all(p['manifest']['synthetic_only'] == manifest['synthetic_only'] for p in packets), 'mixed synthetic/real caches are forbidden')
    files = manifest.get('files')
    require(isinstance(files, dict), 'missing bundle inventory')
    expected = {'bundle.json', 'instance.json'} | {f"case-{i:02d}/{name}" for i, packet in enumerate(packets)
                                for name in list(packet['manifest']['files']) + ['manifest.json']}
    require(set(files) == expected, 'bundle inventory contains undeclared files')
    observed = set()
    for path in root.rglob('*'):
        require(not path.is_symlink() and (path.is_file() or path.is_dir()), 'nonregular bundle entry')
        if path.is_file() and path != root / 'manifest.json':
            observed.add(path.relative_to(root).as_posix())
    require(observed == expected, 'bundle inventory differs')
    for name, record in files.items():
        path = root / name
        require(record == {'bytes': path.stat().st_size, 'sha256': sha256(path)}, 'bundle hash differs: ' + name)
    if instance['template'] == 't2-compare':
        import numpy as np
        for bid in instance['benchmark_ids']:
            first, second = [p for p in packets if p['manifest']['benchmark_id'] == bid]
            # Paired comparison requires exactly the same prepared targets, groups,
            # exclusions and official split manifest. Candidate features may differ.
            for field in ('presentations', 'units', 'protocol'):
                require(first['metadata'][field] == second['metadata'][field], 'comparison target/protocol mismatch: ' + field)
            require(np.array_equal(first['aligned']['responses'], second['aligned']['responses'], equal_nan=True), 'comparison response mismatch')
    return {'root': root, 'manifest': manifest, 'manifest_sha256': sha256(root / 'manifest.json'),
            'instance': instance, 'packets': packets}


def create(packet_paths, output, instance_id, registry):
    require(instance_id in registry['instances'], 'unknown instance')
    packets = [load_packet(path, registry) for path in packet_paths]
    for packet in packets:
        separate_paths(packet['root'], output)
    packets.sort(key=lambda p: (p['manifest']['benchmark_id'], p['manifest']['candidate_id']))
    root = new_directory(output)
    entries = []
    for i, packet in enumerate(packets):
        name = 'case-%02d' % i
        shutil.copytree(packet['root'], root / name)
        entries.append({'directory': name, 'manifest_sha256': packet['manifest_sha256']})
    write_json(root / 'bundle.json', entries)
    instance = registry['instances'][instance_id]
    write_json(root / 'instance.json', {key: instance[key] for key in ('id', 'template', 'benchmark_ids', 'candidate_ids')})
    # Unlike the legacy seal helper, bundle inventories include child manifests.
    files = {p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha256(p)}
             for p in sorted(root.rglob('*')) if p.is_file()}
    write_json(root / 'manifest.json', {'schema': 'bpb-bs-instance-inputs/1', 'instance_id': instance_id,
               'synthetic_only': all(p['manifest']['synthetic_only'] for p in packets), 'files': files})
    return load(root, registry)
