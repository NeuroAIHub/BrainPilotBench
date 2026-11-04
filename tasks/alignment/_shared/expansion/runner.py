"""Explicit maintainer baselines, separate from task setup and trusted grading."""
from pathlib import Path
import shutil

from real_brainscore.common import new_directory, read_json, separate_paths, write_json
from . import TASKS
from .packet import load
from .protocol import default_plan, validate_plan

MODULES = {'B': 'context', 'C': 'brain_behavior', 'D': 'temporal', 'E': 'learning', 'F': 'selection'}


def run(inputs, output, plan):
    import importlib
    import numpy as np
    packet = load(inputs)
    task = packet['task']
    validate_plan(task, plan, len(packet['metadata'].get('candidates', [])))
    separate_paths(inputs, output)
    summary, arrays, conclusion = importlib.import_module('.' + MODULES[task], __package__).compute(packet, plan)
    destination = new_directory(output, allow_empty=True)
    write_json(destination / 'analysis_plan.json', plan)
    write_json(destination / 'results/summary.json', {'protocol_id': TASKS[task][1],
               'input_manifest_sha256': packet['manifest_sha256'], **summary})
    write_json(destination / 'conclusion.json', conclusion)
    for name, values in arrays.items():
        np.save(destination / 'results' / (name + '.npy'), values, allow_pickle=False)
    (destination / 'report.md').write_text(
        '# Maintainer fixed-script baseline\n\n' + plan['rationale'] + '\n\n'
        + packet['protocol']['interpretation'] + '\n\n'
        'This is an experimental analysis/decision protocol, not an independent Agent run. '
        'Automatic grading does not assess prose quality. See the structured results and conclusion.\n')
    return summary


def reference_submission(task, output):
    root = new_directory(output)
    package = Path(__file__).parent
    target = root / 'expansion'
    target.mkdir()
    for name in ('__init__', 'packet', 'protocol', 'runner', MODULES[task]):
        shutil.copyfile(package / (name + '.py'), target / (name + '.py'))
    if task in ('C', 'D'):
        shutil.copyfile(package / 'rsa.py', target / 'rsa.py')
    shared = package.parent
    # Numerical and serialization helpers only; no grader, hidden packet or reference outputs.
    for directory, names in [('incremental', ['__init__', 'protocol', 'data', 'analysis']),
                              ('real_brainscore', ['__init__', 'common'])]:
        (root / directory).mkdir()
        for name in names:
            shutil.copyfile(shared / directory / (name + '.py'), root / directory / (name + '.py'))
    write_json(root / 'plan.json', default_plan(task))
    (root / 'analyze.py').write_text(
        'import argparse\nfrom pathlib import Path\nfrom expansion.runner import run\n'
        'from real_brainscore.common import read_json\n'
        'p=argparse.ArgumentParser()\np.add_argument("--inputs",required=True)\np.add_argument("--output",required=True)\n'
        'a=p.parse_args()\nrun(a.inputs,a.output,read_json(Path(__file__).with_name("plan.json")))\n')
    return {'task': task, 'submission': str(root), 'baseline': 'maintainer-fixed-script-not-agent'}
