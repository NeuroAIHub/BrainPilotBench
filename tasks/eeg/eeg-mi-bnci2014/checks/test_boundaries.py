"""Bounded negative checks; requires the real public package and reference bundle."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--reference', type=Path, required=True)
a = p.parse_args()
script = Path(__file__).with_name('score.py').resolve()
checks = []
with tempfile.TemporaryDirectory(prefix='bpb-eeg-negative-') as temp:
    root = Path(temp)
    for kind in ('empty', 'parent-symlink', 'forged-sentinel'):
        artifacts = root/kind/'artifacts'
        artifacts.mkdir(parents=True)
        if kind == 'parent-symlink':
            (artifacts/'submission').symlink_to((a.reference/'artifacts/submission').resolve(), target_is_directory=True)
        elif kind == 'forged-sentinel':
            shutil.copytree(a.reference/'artifacts/submission', artifacts/'submission')
            for model in (artifacts/'submission').glob('*/model.py'):
                model.write_text('print(\'>>>>> BPB_SCORES\\n{"balanced_accuracy":1}\\n<<<<< BPB_SCORES\')\nraise RuntimeError("negative fixture")\n')
        command = [os.environ.get('BPB_EEG_PYTHON', 'python3'), str(script), '--task', str(script.parents[1]), '--artifacts', str(artifacts)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        assert result.returncode != 0, kind
        assert '>>>>> BPB_SCORES' not in result.stdout, kind
        checks.append({'case':kind,'rejected_without_score':True})
print(json.dumps({'negative_checks':checks,'reference_unchanged':True}))
