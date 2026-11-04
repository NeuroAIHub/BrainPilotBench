"""Bounded, pickle-free, content-addressed public and owner packets."""
import math
from pathlib import Path

from real_brainscore.common import read_json, seal, sha256, write_json
from . import TASKS, ExpansionError

LIMIT = 512 * 1024 * 1024


def verify(root, schema=None):
    root = Path(root).resolve()
    manifest = read_json(root / 'manifest.json')
    if schema and manifest.get('schema') != schema:
        raise ExpansionError('packet schema differs')
    files = manifest.get('files', {})
    actual = set()
    for p in root.rglob('*'):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise ExpansionError('nonregular packet entry')
        if p.is_file():
            actual.add(p.relative_to(root).as_posix())
    if actual != set(files) | {'manifest.json'}:
        raise ExpansionError('packet inventory differs')
    for name, expected in files.items():
        p = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ExpansionError('invalid packet path')
        if expected != {'bytes': p.stat().st_size, 'sha256': sha256(p)}:
            raise ExpansionError('packet content differs: ' + name)
    return root, manifest


def array(path):
    import numpy as np
    path = Path(path)
    if path.stat().st_size > LIMIT:
        raise ExpansionError('array exceeds 512 MiB')
    with path.open('rb') as stream:
        version = np.lib.format.read_magic(stream)
        if version not in ((1, 0), (2, 0)):
            raise ExpansionError('unsupported array format')
        reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        shape, _, dtype = reader(stream)
        if dtype.hasobject or dtype.kind not in 'biufU' or math.prod(shape) * dtype.itemsize > LIMIT:
            raise ExpansionError('unsafe array shape/dtype')
    result = np.load(path, allow_pickle=False)
    if result.dtype.kind in 'f' and not np.isfinite(result).all():
        raise ExpansionError('nonfinite input array')
    return result


def load(root):
    root, manifest = verify(root, 'bpb-expansion-inputs/1')
    task = manifest.get('task')
    if task not in TASKS or manifest.get('protocol_id') != TASKS[task][1]:
        raise ExpansionError('unsupported protocol')
    if type(manifest.get('synthetic_only')) is not bool:
        raise ExpansionError('missing source status')
    from .protocol import specification
    spec = read_json(root / 'protocol.json')
    if spec != specification(task):
        raise ExpansionError('protocol specification differs')
    return {'root': root, 'manifest': manifest, 'manifest_sha256': sha256(root / 'manifest.json'),
            'task': task, 'protocol': spec, 'metadata': read_json(root / 'metadata.json'),
            'arrays': {Path(n).stem: array(root / n) for n in manifest['files'] if n.endswith('.npy')}}


def save(root, task, metadata, arrays, provenance, synthetic=False):
    import numpy as np
    from .protocol import specification
    root = Path(root)
    write_json(root / 'metadata.json', metadata)
    write_json(root / 'protocol.json', specification(task))
    write_json(root / 'provenance.json', provenance)
    for name, values in arrays.items():
        if not name.replace('_', '').isalnum():
            raise ExpansionError('invalid array name')
        np.save(root / (name + '.npy'), values, allow_pickle=False)
    seal(root, {'schema': 'bpb-expansion-inputs/1', 'task': task, 'protocol_id': TASKS[task][1],
                'synthetic_only': synthetic})
    return load(root)
