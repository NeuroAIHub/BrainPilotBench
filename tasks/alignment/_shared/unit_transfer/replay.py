"""Adapt a submitted public selection strategy to the existing isolated worker."""
from pathlib import Path
from tempfile import TemporaryDirectory

from execution import Executor
from real_brainscore.common import read_json, write_json

# The worker starts analyze.py with public inputs and an empty output directory.
# Only the frozen development transcript accompanies the submitted source.
LAUNCHER = '''import argparse
from pathlib import Path
import resource
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

parser = argparse.ArgumentParser()
parser.add_argument("--inputs", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
# Present the same relative paths as the research workspace. The public data
# still lives on the worker's read-only input mount.
with TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    (workspace / "public").symlink_to(args.inputs.resolve(), target_is_directory=True)
    for name in ("strategy.py", "feedback.json"):
        shutil.copyfile(name, workspace / name)
    with (args.output / "choice.json").open("xb") as output:
        run = subprocess.run([sys.executable, "-B", "strategy.py", "public", "feedback.json"],
                             cwd=workspace, stdout=output)
sys.exit(run.returncode)
'''


def replay(packet, source, receipt):
    executor = Executor(timeout=120, cpus=2, memory='2g', tmpfs='64m')
    executor.preflight()
    with TemporaryDirectory() as tmp:
        submission, output = Path(tmp) / 'submission', Path(tmp) / 'output'
        submission.mkdir()
        (submission / 'analyze.py').write_text(LAUNCHER)
        (submission / 'strategy.py').write_bytes(source)
        write_json(submission / 'feedback.json', receipt['feedback'])
        executor.run(submission, packet.root / 'public', output)
        if packet.choice(read_json(output / 'choice.json')) != receipt['choice']:
            raise ValueError('replayed choice differs from frozen submission')
    return {'verified': True, 'isolation': executor.mode, 'image': executor.image if executor.mode == 'docker' else None}
