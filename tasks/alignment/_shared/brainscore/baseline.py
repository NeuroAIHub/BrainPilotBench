"""Explicit maintainer baseline export. Never installed by task setup."""
from pathlib import Path
import shutil

from real_brainscore.common import new_directory


def export(output, registry):
    root = new_directory(output)
    shared = Path(__file__).resolve().parents[1]
    library = root / 'library'
    (library / 'brainscore').mkdir(parents=True)
    for name in ('__init__.py', 'registry.py', 'runtime.py', 'protocols.py', 'packet.py', 'bundle.py', 'official.py', 'analysis.py', 'models.py'):
        shutil.copyfile(shared / 'brainscore' / name, library / 'brainscore' / name)
    shutil.copytree(shared / 'brainscore/adapters', library / 'brainscore/adapters', ignore=shutil.ignore_patterns('__pycache__'))
    (library / 'real_brainscore').mkdir()
    for name in ('__init__.py', 'common.py'):
        shutil.copyfile(shared / 'real_brainscore' / name, library / 'real_brainscore' / name)
    (root / 'registry').mkdir()
    for name in ('sources.json', 'candidates.json', 'instances.json', 'software-lock.json'):
        shutil.copyfile(registry['root'] / name, root / 'registry' / name)
    (root / 'analyze.py').write_text(
        '"""MAINTAINER BASELINE ONLY: never copied into an Agent development workspace."""\n'
        'import argparse\nfrom pathlib import Path\nimport sys\n'
        'here = Path(__file__).resolve().parent\nsys.path.insert(0, str(here / "library"))\n'
        'from brainscore.registry import load\nfrom brainscore.analysis import run\n'
        'p=argparse.ArgumentParser()\np.add_argument("--inputs", required=True)\np.add_argument("--output", required=True)\n'
        'a=p.parse_args()\nrun(a.inputs, a.output, load(here / "registry"))\n')
    return {'submission': str(root), 'purpose': 'maintainer-baseline-only'}
