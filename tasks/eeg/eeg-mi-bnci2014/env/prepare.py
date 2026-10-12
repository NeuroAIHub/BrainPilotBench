"""Stage only the hash-bound public train/valid package. No private Test input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

p = argparse.ArgumentParser()
p.add_argument('--task', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
task, out = Path(a.task), Path(a.output)
contract = json.loads((task / 'contract.json').read_text())
direct = os.environ.get('BPB_EEG_PUBLIC_DATA_DIR')
cache = Path(os.environ.get('BPB_CACHE_ROOT', str(Path(os.environ.get('XDG_CACHE_HOME', str(Path.home()/'.cache'))) / 'brainpilot-bench')))
sources = {}
for name, expected in contract['data_hashes'].items():
    source = Path(direct)/name if direct else cache/expected/'data'
    if not source.is_file() or source.is_symlink():
        raise ValueError(f'Missing public {name}; fetch data or set BPB_EEG_PUBLIC_DATA_DIR')
    if hashlib.file_digest(source.open('rb'), 'sha256').hexdigest() != expected:
        raise ValueError(f'Public data hash mismatch: {name}')
    sources[name] = source
out.mkdir(parents=True, exist_ok=True)
for name, source in sources.items():
    dest = out/name
    if dest.exists() and hashlib.file_digest(dest.open('rb'), 'sha256').hexdigest() != contract['data_hashes'][name]:
        raise ValueError(f'Refusing to overwrite different data: {dest}')
    if not dest.exists():
        shutil.copyfile(source, dest)
shutil.copyfile(task/'contract.json', out/'task_spec.json')
print(json.dumps({'public_files': list(sources), 'private_test': False}))
