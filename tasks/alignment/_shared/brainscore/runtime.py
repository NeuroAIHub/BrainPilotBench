"""Pinned software identity and a no-network context for maintainer computations."""
from contextlib import contextmanager, ExitStack
import hashlib
import importlib
import importlib.metadata
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch

from . import ScaleUpError
from .registry import DEFAULT_ROOT, require
from real_brainscore.common import read_json, sha256

PACKAGES = ('numpy', 'scipy', 'pandas', 'scikit-learn', 'torch', 'xarray', 'brainscore-core',
            'transformers', 'tokenizers', 'safetensors', 'pillow')


def tree_digest(root):
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file() and p.suffix in ('.py', '.json')):
        digest.update((path.relative_to(root).as_posix() + ':' + sha256(path) + '\n').encode())
    return digest.hexdigest()


@contextmanager
def offline():
    """Guard trusted Python preparation; untrusted submissions additionally need Docker."""
    def denied(*args, **kwargs):
        raise ScaleUpError('network disabled: provide all source data, ceilings and weights locally')
    env = {'BS_INSTALL_DEPENDENCIES': 'no', 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
           'TRANSFORMERS_OFFLINE': '1', 'CUDA_VISIBLE_DEVICES': '', 'RESULTCACHING_DISABLE': '1',
           'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, env))
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection', 'socket.getaddrinfo'):
            stack.enter_context(patch(target, denied))
        from threadpoolctl import threadpool_limits
        stack.enter_context(threadpool_limits(limits=1))
        yield


def check(ecosystem, registry_root=DEFAULT_ROOT):
    require(sys.version_info[:2] == (3, 11), 'official runtime requires Python 3.11')
    lock = read_json(Path(registry_root) / 'software-lock.json')[ecosystem]
    module = importlib.import_module('brainscore_' + ecosystem)
    require(tree_digest(Path(module.__file__).parent) == lock['package_tree_sha256'], 'installed upstream code differs from frozen source')
    names = PACKAGES + (('torchvision', 'result-caching') if ecosystem == 'vision' else ())
    packages = {name: importlib.metadata.version(name) for name in names}
    for name, version in lock['numerical_packages'].items():
        require(packages[name] == version, 'numerical package differs from lock: ' + name)
    return {'ecosystem': ecosystem, 'upstream_commit': lock['upstream_commit'],
            'package_tree_sha256': lock['package_tree_sha256'], 'packages': packages,
            'python': sys.version.split()[0], 'network': 'disabled', 'device': 'cpu'}
