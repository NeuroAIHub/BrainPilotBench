"""Export already-installed software and a no-fetch Docker build context."""
import importlib
import importlib.metadata
from pathlib import Path
import shutil

from real_brainscore.common import new_directory, write_json
from .registry import require
from .runtime import offline, check


def export(ecosystem, output, registry, base_image):
    require(base_image.startswith('sha256:') and len(base_image) == 71, 'pin an existing base image by full sha256 digest')
    with offline():
        runtime = check(ecosystem, registry['root'])
        import numpy
        package = importlib.import_module('brainscore_' + ecosystem)
    root = new_directory(output)
    overlay = root / 'overlay'
    base_packages = Path(numpy.__file__).parent.parent
    shutil.copytree(base_packages, overlay, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pth'))
    # Language uses an isolated overlay over the old numerical environment. Remove
    # old package/metadata before installing the current package into the context.
    for path in list(overlay.glob('brainscore_language*')) + list(overlay.glob('brainscore_vision*')):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    distribution = importlib.metadata.distribution('brainscore-' + ecosystem)
    shutil.copytree(Path(package.__file__).parent, overlay / ('brainscore_' + ecosystem), ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    info = Path(distribution._path)
    shutil.copytree(info, overlay / info.name)
    shared = Path(__file__).resolve().parents[1]
    shutil.copyfile(shared / 'worker.py', root / 'worker.py')
    (root / 'Dockerfile').write_text(
        'FROM ' + base_image + '\nUSER root\n'
        'RUN rm -rf /opt/alignment && mkdir -p /opt/alignment\n'
        'COPY overlay/ /opt/alignment/site-packages/\nCOPY worker.py /opt/alignment/worker.py\n'
        'ENV PYTHONPATH=/opt/alignment/site-packages PYTHONDONTWRITEBYTECODE=1 '
        'BS_INSTALL_DEPENDENCIES=no HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 '
        'RESULTCACHING_DISABLE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES=""\n'
        'WORKDIR /tmp\nENTRYPOINT ["python", "/opt/alignment/worker.py"]\n')
    names = sorted({dist.metadata['Name'] for dist in importlib.metadata.distributions()})
    versions = {name: importlib.metadata.version(name) for name in names}
    write_json(root / 'environment.json', {'schema': 'bpb-bs-environment/1', 'runtime': runtime, 'packages': versions,
               'base_image': base_image, 'data_and_weights_included': False, 'owner_analysis_code_included': False})
    lines = []
    for name, version in versions.items():
        normalized = name.lower().replace('_', '-')
        if normalized == 'brainscore-' + ecosystem:
            lines.append('brainscore-' + ecosystem + ' @ git+https://github.com/brain-score/' + ecosystem + '.git@' + runtime['upstream_commit'])
        elif normalized not in ('brainscore-vision', 'brainscore-language'):
            lines.append(name + '==' + version)
    (root / 'requirements.lock.txt').write_text('\n'.join(lines) + '\n')
    # BuildKit treats a bare local image ID as a registry name. The local legacy
    # builder accepts the immutable ID without trying to resolve it remotely.
    return {'context': str(root), 'runtime': runtime,
            'build': 'DOCKER_BUILDKIT=0 docker build --network=none --pull=false -t LOCAL_TAG ' + str(root)}
