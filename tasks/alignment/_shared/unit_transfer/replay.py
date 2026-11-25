"""Adapt a submitted public selection strategy to the existing isolated worker."""
from pathlib import Path
from tempfile import TemporaryDirectory

from execution import Executor
from real_brainscore.common import read_json, write_json

# The worker starts analyze.py with public inputs and an empty output directory.
# Only the frozen development transcript accompanies the submitted source.
LAUNCHER = '''import argparse
import os
from pathlib import Path
import resource
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--inputs", required=True)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
with (args.output / "choice.json").open("xb") as output:
    os.dup2(output.fileno(), 1)
os.execv(sys.executable, [sys.executable, "-B", "strategy.py", args.inputs, "feedback.json"])
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
