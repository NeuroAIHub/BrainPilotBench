"""Bounded worker interface. Docker is required for untrusted submissions.

The opt-in process backend is only a local test harness, not a security boundary.
"""
import os
import json
from pathlib import Path
import signal
import subprocess
import sys
import uuid

from contract import ContractError, digest

WORKER = Path(__file__).with_name('worker.py').resolve()
WORKER_SECONDS = 8


class InfrastructureError(RuntimeError):
    pass


class AnalysisFailure(RuntimeError):
    pass


def snapshot(root):
    result = {}
    for p in Path(root).rglob('*'):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            raise ContractError('nonregular worker input')
        if p.is_file():
            result[str(p.relative_to(root))] = digest(p)
    return result


def bounded(command, cwd, env, timeout=WORKER_SECONDS):
    # No worker-controlled bytes are forwarded into trusted scorer stdout.
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise InfrastructureError('worker launch failed') from exc
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AnalysisFailure('worker timed out') from exc
    finally:
        # Also clean up descendants after a parent exits successfully.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


class Executor:
    def __init__(self, mode=None):
        self.mode = mode or os.environ.get('BPB_SUBMISSION_ISOLATION', 'docker')
        self.docker = os.environ.get('BPB_DOCKER_BINARY', 'docker')
        self.image = os.environ.get('BPB_INFERENCE_IMAGE', '')
        self.host = None

    def docker_command(self, name, source, inputs, output):
        return [self.docker, *(['--host', self.host] if self.host else []), 'run', '--pull=never', '--name', name,
                '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--cpus=1', '--memory=512m', '--pids-limit=64',
                '--user', f'{os.getuid()}:{os.getgid()}',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m',
                '--mount', f'type=bind,src={source},dst=/submission,readonly',
                '--mount', f'type=bind,src={inputs},dst=/inputs,readonly',
                '--mount', f'type=bind,src={output},dst=/output',
                '--env', 'OPENBLAS_NUM_THREADS=1', '--env', 'OMP_NUM_THREADS=1',
                '--env', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint', 'python', self.image,
                '/opt/alignment/worker.py', '--submission', '/submission', '--inputs', '/inputs', '--output', '/output']

    def admin(self, args):
        try:
            return subprocess.run([self.docker, *(['--host', self.host] if self.host else []), *args], capture_output=True, timeout=10, text=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InfrastructureError('Docker unavailable') from exc

    def preflight(self):
        if self.mode == 'process':
            if os.environ.get('BPB_ALIGNMENT_TRUSTED_LOCAL') != '1' or os.environ.get('BPB_OFFICIAL_SCORING') == '1':
                raise InfrastructureError('process mode requires BPB_ALIGNMENT_TRUSTED_LOCAL=1 and cannot be official')
        elif self.mode == 'docker':
            # Resolve the operator's local context before scrubbing the Docker client's HOME.
            if os.environ.get('DOCKER_HOST') and not os.environ.get('DOCKER_CONTEXT'):
                self.host = os.environ['DOCKER_HOST']
            else:
                endpoint = self.admin(['context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'])
                if endpoint.returncode:
                    raise InfrastructureError('Docker context unavailable')
                self.host = endpoint.stdout.strip()
            if not self.host.startswith('unix://'):
                raise InfrastructureError('this offline worker requires a local Unix Docker endpoint')
            if not self.image or self.admin(['image', 'inspect', self.image]).returncode:
                raise InfrastructureError('local worker image missing (never pulled automatically)')
            # Check dependencies/worker without mounting any submitted code or evaluator files.
            name = 'bpb-alignment-preflight-' + uuid.uuid4().hex
            try:
                if self.admin(['run', '--name', name, '--pull=never', '--network=none', '--read-only',
                               '--entrypoint', 'python', self.image, '-B', '-c',
                               'import numpy; from pathlib import Path; assert Path("/opt/alignment/worker.py").is_file()']).returncode:
                    raise InfrastructureError('worker image runtime check failed')
            finally:
                self.cleanup(name)
        else:
            raise InfrastructureError('unsupported worker mode')

    def cleanup(self, name):
        cleanup = self.admin(['rm', '-f', name])
        if cleanup.returncode and 'No such container' not in cleanup.stderr:
            raise InfrastructureError('worker container cleanup failed')

    def run(self, source, inputs, output):
        source, inputs, output = (Path(p).resolve() for p in [source, inputs, output])
        try:
            output.mkdir(parents=True, exist_ok=False)
            before = (snapshot(source), snapshot(inputs))
        except (OSError, ContractError) as exc:
            raise InfrastructureError('worker staging failed') from exc
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(output),
               'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0',
               'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
               'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'}
        if self.mode == 'process':
            code = bounded([sys.executable, '-B', str(WORKER), '--submission', str(source),
                            '--inputs', str(inputs), '--output', str(output)], output, env)
        else:
            name = 'bpb-alignment-' + uuid.uuid4().hex
            try:
                code = bounded(self.docker_command(name, source, inputs, output), output, env)
                state = self.admin(['inspect', '--format', '{{json .State}}', name])
                if state.returncode:
                    raise InfrastructureError('worker container state unavailable')
                if json.loads(state.stdout).get('Error'):
                    raise InfrastructureError('Docker could not start worker')
            finally:
                self.cleanup(name)
        try:
            after = (snapshot(source), snapshot(inputs))
        except (OSError, ContractError) as exc:
            raise AnalysisFailure('worker inputs/source became unreadable') from exc
        if before != after:
            raise AnalysisFailure('submission modified worker inputs or source')
        if code:
            raise AnalysisFailure(f'worker exited with code {code}')
