"""Public-valid scorer. Labels stay outside submitted-program containers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--task', required=True)
p.add_argument('--artifacts', required=True)
a = p.parse_args()
task = Path(a.task).resolve()
raw_artifacts = Path(a.artifacts).absolute()
if raw_artifacts.is_symlink() or (raw_artifacts/'submission').is_symlink():
    raise ValueError('Submission directories must not be symbolic links')
artifacts = raw_artifacts.resolve()
contract = json.loads((task/'contract.json').read_text())
if os.environ.get('BPB_OFFICIAL_SCORING') == '1':
    raise ValueError('This entry provides public validation, not official private Test scoring')
data = Path(os.environ['BPB_EEG_PUBLIC_DATA_DIR'])/'val.npz'
if hashlib.file_digest(data.open('rb'), 'sha256').hexdigest() != contract['data_hashes']['val.npz']:
    raise ValueError('Public validation hash mismatch')
with np.load(data, allow_pickle=False) as d:
    x, y = d['x'], d['y']
if x.shape != (1152,22,480) or y.shape != (1152,) or not np.isfinite(x).all() or set(np.unique(y)) != {0,1,2,3}:
    raise ValueError('Public validation shape/labels invalid')
image = os.environ.get('BPB_INFERENCE_IMAGE') or os.environ['BPB_EEG_IMAGE']
if not (image.startswith('sha256:') or '@sha256:' in image):
    raise ValueError('BPB_EEG_IMAGE must use an immutable local image ID or repository digest')
scores, hashes = [], {}
with tempfile.TemporaryDirectory(prefix='bpb-eeg-') as temp:
    root = Path(temp)
    np.save(root/'x.npy', x, allow_pickle=False)
    for seed in range(3):
        source = artifacts/'submission'/f'seed-{seed}'
        bundle, output = root/f'seed-{seed}', root/f'out-{seed}'
        bundle.mkdir(); output.mkdir()
        for name, limit in [('model.py',1_000_000),('config.json',256_000),('weights.safetensors',100_000_000)]:
            f = source/name
            if f.is_symlink() or not f.is_file() or not 0 < f.stat().st_size <= limit or source.is_symlink():
                raise ValueError(f'Invalid required submission file {seed}/{name}')
            hashes[f'{seed}/{name}'] = hashlib.file_digest(f.open('rb'),'sha256').hexdigest()
            shutil.copyfile(f,bundle/name)
        # Output alone is writable to the fixed, unprivileged inference identity.
        output.chmod(0o777)
        container = 'bpb-eeg-' + uuid.uuid4().hex
        cmd = ['docker','run','--rm','--name',container,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','2','--memory','4g','--pids-limit','128','--user','65534:65534','--tmpfs','/tmp:rw,noexec,nosuid,size=256m',
               '-v',f'{bundle}:/submission:ro','-v',f'{root/"x.npy"}:/input/x.npy:ro','-v',f'{task/"checks/worker.py"}:/worker.py:ro','-v',f'{output}:/output',image,'python','/worker.py','--submission','/submission','--x','/input/x.npy','--output','/output/predictions.npy']
        try:
            # Submitted stdout is never a trusted scoring channel.
            subprocess.run(cmd,check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        finally:
            subprocess.run(['docker','rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        f = output/'predictions.npy'
        if f.is_symlink() or f.stat().st_size > 1_000_000:
            raise ValueError('Invalid predictions artifact')
        # Validate the array header before NumPy can allocate from untrusted dimensions.
        with f.open('rb') as stream:
            version = np.lib.format.read_magic(stream)
            if version == (1, 0):
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
            elif version == (2, 0):
                shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
            else:
                raise ValueError('Unsupported prediction file version')
            if shape != (len(y),4) or fortran or dtype not in (np.dtype('float32'),np.dtype('float64')) or f.stat().st_size != stream.tell() + len(y)*4*dtype.itemsize:
                raise ValueError('Invalid prediction array header')
        pred = np.load(f,allow_pickle=False)
        if pred.shape != (len(y),4) or not np.isfinite(pred).all() or (pred < 0).any() or (pred > 1).any() or not np.allclose(pred.sum(1),1,atol=1e-4):
            raise ValueError('Invalid class probabilities')
        labels = pred.argmax(1)
        scores.append(float(np.mean([np.mean(labels[y==c]==c) for c in range(4)])))
report = {'scope':'public-validation-only','private_test':False,'samples':len(y),'seed_scores':scores,'balanced_accuracy':float(np.mean(scores)),'submission_sha256':hashes,'image':image}
(artifacts.parent/'eeg-public-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print('>>>>> BPB_SCORES')
print(json.dumps({'balanced_accuracy':report['balanced_accuracy'],'seeds':3,'validation_samples':len(y)}))
print('<<<<< BPB_SCORES')
