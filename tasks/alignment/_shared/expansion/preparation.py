"""Owner-only conversion of authenticated author object files in Docker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from execution import Executor, InfrastructureError
from real_brainscore.common import new_directory, read_json, seal, separate_paths, sha256, write_json
from . import ExpansionError
from .packet import array
from .sources import entries, verify_source


def convert_eeg2(raw, output, image):
    raw = Path(raw).resolve()
    separate_paths(raw, output)
    files = {}
    for entry in entries('D'):
        local = verify_source(raw, entry)
        files[local.name] = entry['sha256']
    executor = Executor('docker')
    executor.image = image
    executor.preflight()
    identity = executor.admin(['image', 'inspect', '--format', '{{.Id}}', image])
    if identity.returncode or not identity.stdout.strip().startswith('sha256:'):
        raise InfrastructureError('converter image identity unavailable')
    image = identity.stdout.strip()
    destination = new_directory(output)
    with tempfile.TemporaryDirectory(prefix='bpb-eeg2-converter-') as temp:
        source = Path(temp)
        for name in files:
            # Copy only authenticated source files; no other owner datasets mount.
            try:
                os.link(raw / name, source / name)
            except OSError:
                shutil.copyfile(raw / name, source / name)
        converter = Path(__file__).with_name('convert_eeg2.py')
        shutil.copyfile(converter, source / 'convert.py')
        write_json(source / 'conversion-lock.json', {'sha256': files,
                   'sources': ['https://osf.io/anp5v/', 'https://osf.io/y63gw/'],
                   'converter_sha256': sha256(converter), 'image': image})
        name = 'bpb-eeg2-conversion-' + uuid.uuid4().hex
        command = [executor.docker, '--host', executor.host, 'run', '--name', name, '--pull=never',
                   '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                   '--user', '%d:%d' % (os.getuid(), os.getgid()), '--cpus=2', '--memory=4g', '--pids-limit=64',
                   '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m', '--env', 'OPENBLAS_NUM_THREADS=1', '--env', 'PYTHONDONTWRITEBYTECODE=1',
                   '--mount', 'type=bind,src=%s,dst=/source,readonly' % source,
                   '--mount', 'type=bind,src=%s,dst=/output' % destination,
                   '--entrypoint', 'python', image, '-B', '/source/convert.py', '--source', '/source', '--output', '/output']
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise InfrastructureError('author data conversion failed: ' + result.stderr[-2000:])
        finally:
            executor.cleanup(name)
    # Converted object content is checked before becoming a trusted packet.
    eeg, times = array(destination / 'eeg.npy'), array(destination / 'times.npy')
    meta = read_json(destination / 'metadata.json')
    if eeg.shape != (2, 200, 17, len(times)) or len(meta['concept_ids']) != 200 or len(set(meta['image_ids'])) != 200:
        raise ExpansionError('converted EEG metadata/shape differs')
    seal(destination, {'schema': 'bpb-eeg2-converted/1', 'synthetic_only': False})
    return {'converted': str(destination), 'manifest_sha256': sha256(destination / 'manifest.json')}
