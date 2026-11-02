"""Draft real Task1 comparison, with submitted code executed only in Docker."""
import json
import math
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from . import BackendError
from .common import load_cache, new_directory, read_json, separate_paths, sha256, write_json
from .pipeline import score_fixed


def _tree(root):
    result = {}
    for path in Path(root).rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise BackendError('submission/input contains nonregular files')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def compare_results(actual, expected, atol=1e-6, rtol=1e-5):
    import csv
    import numpy as np
    def same(left, right):
        if type(right) in (int, float):
            return type(left) in (int, float) and math.isfinite(left) and math.isclose(left, right, abs_tol=atol, rel_tol=rtol)
        if isinstance(right, dict):
            return isinstance(left, dict) and set(left) == set(right) and all(same(left[k], v) for k, v in right.items())
        if isinstance(right, list):
            return isinstance(left, list) and len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
        return type(left) is type(right) and left == right
    errors = []
    try:
        _tree(actual)
        size = sum(p.stat().st_size for p in Path(actual).rglob('*') if p.is_file())
        if size > 512 * 1024 * 1024:
            raise BackendError('submitted results exceed draft 512 MiB output limit')
        for rel in ('analysis_config.json', 'results/summary.json'):
            if not same(read_json(Path(actual) / rel), read_json(Path(expected) / rel)):
                errors.append(rel + ' mismatch')
        def rows(root):
            with (Path(root) / 'results/fold_scores.csv').open(newline='') as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != ['fold_id', 'subject_id', 'neuroid_id', 'pearson_r']:
                    raise BackendError('fold score columns differ')
                output = {}
                for row in reader:
                    key = tuple(row[k] for k in reader.fieldnames[:3])
                    if key in output:
                        raise BackendError('duplicate fold score')
                    output[key] = float(row['pearson_r'])
                return output
        if not same(rows(actual), rows(expected)):
            errors.append('fold scores mismatch')
        # Bound expanded NPZ members before NumPy loads submitted arrays.
        import zipfile
        def predictions(root, expected_shape=None):
            path = Path(root) / 'results/predictions.npz'
            with zipfile.ZipFile(path) as archive:
                if set(archive.namelist()) != {'values.npy', 'fold_ids.npy', 'stimulus_ids.npy', 'neuroid_ids.npy'} or len(archive.namelist()) != 4:
                    raise BackendError('invalid NPZ members')
                if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
                    raise BackendError('expanded predictions too large')
                for name in archive.namelist():
                    with archive.open(name) as member:
                        version = np.lib.format.read_magic(member)
                        if version not in ((1, 0), (2, 0)):
                            raise BackendError('unsupported NPY header version')
                        reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
                        shape, _, dtype = reader(member)
                        if dtype.hasobject or math.prod(shape) * dtype.itemsize > 512 * 1024 * 1024:
                            raise BackendError('unsafe NPY shape/dtype')
                        if name == 'values.npy' and (dtype != np.dtype('float64') or (expected_shape is not None and shape != expected_shape)):
                            raise BackendError('prediction value dtype/shape differs')
                        if name != 'values.npy' and (len(shape) != 1 or dtype.kind != 'U'):
                            raise BackendError('prediction IDs must be one-dimensional Unicode arrays')
            with np.load(path, allow_pickle=False) as arrays:
                if set(arrays.files) != {'values', 'fold_ids', 'stimulus_ids', 'neuroid_ids'}:
                    raise BackendError('prediction fields differ')
                values, folds, stimuli, units = (arrays[k] for k in ('values', 'fold_ids', 'stimulus_ids', 'neuroid_ids'))
                if values.ndim != 2 or values.shape != (len(stimuli), len(units)) or len(folds) != len(stimuli) or not np.isfinite(values).all():
                    raise BackendError('prediction shape/values invalid')
                keys = [(str(f), str(s)) for f, s in zip(folds, stimuli)]
                names = [str(u) for u in units]
                if len(set(keys)) != len(keys) or len(set(names)) != len(names):
                    raise BackendError('duplicate prediction IDs')
                order, columns = sorted(range(len(keys)), key=keys.__getitem__), sorted(range(len(names)), key=names.__getitem__)
                return sorted(keys), sorted(names), values[np.ix_(order, columns)]
        ref_keys, ref_units, ref_values = predictions(expected)
        keys, units, values = predictions(actual, expected_shape=ref_values.shape)
        if keys != ref_keys or units != ref_units or not np.allclose(values, ref_values, atol=atol, rtol=rtol):
            errors.append('predictions mismatch')
        report = Path(actual) / 'report.md'
        if not report.is_file() or report.stat().st_size == 0:
            errors.append('missing report.md')
    except Exception as exc:
        errors.append(str(exc))
    return {'passed': not errors, 'errors': errors, 'atol': atol, 'rtol': rtol}


def evaluate(cache, submission, output, image, saved_results=None, timeout=900, memory='8g'):
    root, _, _ = load_cache(cache)
    source = Path(submission).resolve()
    separate_paths(root, output)
    separate_paths(source, output)
    separate_paths(root, source)
    destination = new_directory(output)
    report = {'schema': 'bpb-real-alignment-grade/1', 'synthetic_only': False,
              'acceptance': 'server-validation-pending', 'state': 'scoring_failed',
              'analysis_success': None, 'isolation': 'docker', 'prose_review': 'not_assessed'}
    try:
        if not (source / 'analyze.py').is_file() or not image:
            raise BackendError('submission/analyze.py and a prebuilt local image are required')
        if os.getuid() == 0:
            raise BackendError('run the draft evaluator as a non-root owner user')
        inspection = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                                    capture_output=True, text=True, check=True, timeout=15)
        immutable_image = inspection.stdout.strip()
        if not immutable_image.startswith('sha256:'):
            raise BackendError('could not resolve local immutable image ID')
        before = (_tree(source), _tree(root))
        report['image'] = immutable_image
        with tempfile.TemporaryDirectory(prefix='bpb-real-reference-') as temporary:
            reference = Path(temporary) / 'reference'
            score_fixed(root, reference, device='cpu')
            probe = subprocess.run(
                ['docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
                 '--tmpfs=/tmp:rw,nosuid,nodev,size=512m', '--entrypoint=python', immutable_image, '-c',
                 'import json; from pathlib import Path; from real_brainscore.common import runtime; '
                 'assert Path("/opt/alignment/worker.py").is_file(); print(json.dumps(runtime("cpu")))'],
                capture_output=True, text=True, timeout=60, check=True)
            image_runtime = json.loads(probe.stdout)
            parent_runtime = read_json(reference / 'runtime.json')
            if any(image_runtime[key] != parent_runtime[key] for key in ('packages', 'adapter_sources')):
                raise BackendError('worker/server numerical versions or adapter sources differ; rebuild the image before evaluating an Agent')
            worker_output = destination / 'worker-output'
            worker_output.mkdir()
            for path in (source, root, worker_output):
                if ',' in str(path) or '\n' in str(path):
                    raise BackendError('Docker mount paths cannot contain commas or newlines')
            name = 'bpb-real-alignment-' + uuid.uuid4().hex
            command = ['docker', 'run', '--pull=never', '--name', name, '--network=none', '--read-only',
                       '--cap-drop=ALL', '--security-opt=no-new-privileges', '--cpus=4', '--memory=' + memory,
                       '--pids-limit=128', '--user=%d:%d' % (os.getuid(), os.getgid()),
                       '--tmpfs=/tmp:rw,nosuid,nodev,size=512m',
                       '--mount=type=bind,src=%s,dst=/submission,readonly' % source,
                       '--mount=type=bind,src=%s,dst=/inputs,readonly' % root,
                       '--mount=type=bind,src=%s,dst=/output' % worker_output,
                       '--env=BS_INSTALL_DEPENDENCIES=no', '--env=HF_HUB_OFFLINE=1',
                       '--env=TRANSFORMERS_OFFLINE=1', '--env=CUDA_VISIBLE_DEVICES=',
                       '--entrypoint=python', immutable_image, '/opt/alignment/worker.py',
                       '--submission', '/submission', '--inputs', '/inputs', '--output', '/output']
            try:
                process = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
                if process.returncode:
                    report.update(state='scored', analysis_success=0, error='submitted program failed')
                else:
                    comparisons = [compare_results(worker_output, reference)]
                    if saved_results is not None:
                        comparisons.append(compare_results(saved_results, reference))
                    unchanged = before == (_tree(source), _tree(root))
                    report.update(state='scored', analysis_success=int(unchanged and all(x['passed'] for x in comparisons)),
                                  comparisons=comparisons, inputs_unchanged=unchanged)
            except subprocess.TimeoutExpired:
                report.update(state='scored', analysis_success=0, error='submitted program timed out')
            finally:
                subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except Exception as exc:
        report.update(state='scoring_failed', analysis_success=None, error='%s: %s' % (type(exc).__name__, exc))
    write_json(destination / 'grade.json', report)
    return report
