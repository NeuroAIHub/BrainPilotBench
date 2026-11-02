"""Dependency-free configuration, manifests and runtime provenance."""
import hashlib
import importlib.metadata
import json
import os
import re
import sys
from pathlib import Path

from . import BENCHMARK, CACHE_SCHEMA, COMMIT, BackendError


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BackendError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def reject(value):
        raise BackendError('nonfinite JSON: ' + value)
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_000_000:
        raise BackendError('expected a bounded regular JSON file: ' + str(path))
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=reject)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def outside_repository(path):
    path = Path(path).expanduser().resolve()
    repository = next((parent for parent in Path(__file__).resolve().parents
                       if (parent / 'package.json').is_file() and (parent / 'tasks/alignment').is_dir()), None)
    if repository is not None and (path == repository or repository in path.parents):
        raise BackendError('server data/output must live outside the Git checkout')
    return path


def new_directory(path, allow_empty=False):
    path = outside_repository(path)
    if path.exists():
        if allow_empty and path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
            return path
        raise BackendError('refusing to overwrite output; use a fresh directory: ' + str(path))
    path.mkdir(parents=True, mode=0o700)
    return path


def separate_paths(first, second):
    first, second = (Path(path).expanduser().resolve() for path in (first, second))
    if first == second or first in second.parents or second in first.parents:
        raise BackendError('inputs, submitted source and operator outputs must use disjoint directories')


def config(path, require_revision=True):
    value = read_json(path)
    if not isinstance(value, dict) or value.get('schema') != 'bpb-brainscore-server-config/1' or value.get('upstream_commit') != COMMIT or value.get('benchmark') != BENCHMARK:
        raise BackendError('unsupported config/benchmark/upstream commit')
    model = value.get('model', {})
    if not isinstance(model, dict) or not isinstance(model.get('id'), str) or not model['id']:
        raise BackendError('model.id is required')
    for field in ('revision', 'tokenizer_revision'):
        if require_revision and not re.fullmatch('[0-9a-f]{40}', model.get(field) or ''):
            raise BackendError('resolve immutable model/tokenizer revisions on the server first')
    layers = value.get('layers')
    if not isinstance(layers, list) or not layers or len(layers) > 128 or not all(isinstance(x, str) and x for x in layers) or len(set(layers)) != len(layers):
        raise BackendError('layers must be distinct module paths in model depth order')
    if value.get('task1_layer') not in layers or value.get('baseline_layer') != layers[-1]:
        raise BackendError('task1_layer must be cached and baseline_layer must be the final declared layer')
    if model.get('dtype') != 'float32':
        raise BackendError('server draft currently requires float32 model features; no quantization')
    return value


def runtime(device='cpu', online=False):
    """Called only by explicit server commands, before importing Torch/Brain-Score."""
    if sys.platform != 'linux' or sys.version_info < (3, 11):
        raise BackendError('real execution targets Linux with Python >=3.11; Mac development is static only')
    if device not in ('cpu', 'cuda'):
        raise BackendError('device must be cpu or cuda')
    if device == 'cpu':
        if 'torch' in sys.modules:
            raise BackendError('select CPU in a fresh process before importing torch')
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
    os.environ['BS_INSTALL_DEPENDENCIES'] = 'no'
    os.environ['HF_HUB_OFFLINE'] = '0' if online else '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '0' if online else '1'
    versions = {}
    for name in ('brainscore-language', 'brainscore-core', 'numpy', 'scipy', 'pandas', 'scikit-learn', 'torch', 'transformers', 'xarray'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise BackendError('missing server dependency: ' + name) from exc
    if versions['brainscore-language'] != '2.3.0' or int(versions['numpy'].split('.')[0]) >= 2:
        raise BackendError('expected Brain-Score Language 2.3.0 and numpy <2')
    distribution = importlib.metadata.distribution('brainscore-language')
    direct = json.loads(distribution.read_text('direct_url.json') or '{}')
    if direct.get('vcs_info', {}).get('commit_id') != COMMIT:
        raise BackendError('install Brain-Score from the pinned Git commit; version number alone is insufficient')
    import torch
    if device == 'cuda' and not torch.cuda.is_available():
        raise BackendError('CUDA requested but unavailable; no silent CPU fallback')
    return {'python': sys.version, 'packages': versions, 'upstream_commit': COMMIT,
            'device': device, 'cuda': torch.version.cuda,
            'adapter_sources': {path.name: sha256(path) for path in sorted(Path(__file__).parent.glob('*.py'))},
            'acceptance': 'server-validation-pending'}


def seal(root, manifest):
    root = Path(root)
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name != 'manifest.json':
            files[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha256(path)}
    write_json(root / 'manifest.json', {**manifest, 'files': files})


def load_cache(root):
    root = Path(root).resolve()
    manifest = read_json(root / 'manifest.json')
    if not isinstance(manifest, dict) or manifest.get('schema') != CACHE_SCHEMA or manifest.get('synthetic_only') is not False or manifest.get('upstream_commit') != COMMIT or manifest.get('benchmark') != BENCHMARK:
        raise BackendError('expected a real, pinned Pereira cache; synthetic inputs are not accepted')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise BackendError('missing cache file inventory')
    actual_files = set()
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise BackendError('cache contains nonregular entries')
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
    if actual_files != set(files) | {'manifest.json'}:
        raise BackendError('cache inventory differs; do not put reference answers or logs in public inputs')
    for rel, expected in files.items():
        if not isinstance(rel, str) or Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise BackendError('unsafe cache path')
        path = root / rel
        if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
            raise BackendError('missing/nonregular cache member: ' + rel)
        if expected != {'bytes': path.stat().st_size, 'sha256': sha256(path)}:
            raise BackendError('cache hash mismatch: ' + rel)
    required = {'config.json', 'stimuli.json', 'brain.nc', 'ceiling.json', 'runtime.json', 'protocol.json'}
    if not required.issubset(files):
        raise BackendError('cache is incomplete')
    configuration = config(root / 'config.json')
    if manifest.get('layers') != configuration['layers']:
        raise BackendError('manifest/config layer binding differs')
    expected_files = required | {'features/layer-%03d.npy' % i for i in range(len(configuration['layers']))}
    if set(files) != expected_files:
        raise BackendError('cache must contain only the declared public inputs, without weights or references')
    return root, manifest, configuration
