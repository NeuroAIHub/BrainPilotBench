"""Shared packet and submission contract for open single-cell and circuit discovery."""
from contextlib import contextmanager
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from expansion.packet import verify
from real_brainscore.common import read_json, seal, sha256, write_json


@contextmanager
def prepare_packet(destination, protocol, packet_class):
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise ValueError('preparation requires a fresh destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as tmp:
        root = Path(tmp) / 'packet'
        for name in ('public', 'owner/dev', 'owner/test'):
            (root / name).mkdir(parents=True)
        yield root
        write_json(root / 'public/protocol.json', protocol)
        task = protocol['task']
        seal(root / 'public', {'schema': task + '/public'})
        seal(root / 'owner', {'schema': task + '/owner', 'public_sha256': sha256(root / 'public/manifest.json')})
        packet_class(root)
        root.rename(destination)


class SelectionPacket:
    extra_fields = set()

    def __init__(self, root, task, metric):
        self.root = Path(root).resolve()
        public, inventory = verify(self.root / 'public', task + '/public')
        if set(inventory['files']) != self.public_files:
            raise ValueError('unexpected public files for this task')
        owner, manifest = verify(self.root / 'owner', task + '/owner')
        self.identity = sha256(public / 'manifest.json')
        self.owner_identity = sha256(owner / 'manifest.json')
        self.protocol = read_json(public / 'protocol.json')
        self.metric = metric
        if (manifest.get('public_sha256') != self.identity or self.protocol.get('task') != task
                or self.protocol.get('primary_metric') != metric):
            raise ValueError('packet, model or protocol binding differs')

    def selection(self, raw, field):
        keys = {'packet_sha256', field}
        allowed = keys | {'predicted_score'} | self.extra_fields
        if (not isinstance(raw, dict) or not keys <= set(raw) <= allowed
                or raw['packet_sha256'] != self.identity):
            raise ValueError('invalid choice fields or public packet fingerprint')
        return raw[field]

    def choice(self, raw):
        choice = self.query_choice(raw)
        value = raw.get('predicted_score')
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('final submission requires a finite predicted_score')
        if self.protocol['unit'] == 'correlation' and not -1 <= value <= 1:
            raise ValueError('predicted correlation must be in [-1,1]')
        return {**choice, 'predicted_score': round(value, 6)}

    def development_feedback(self, choice):
        return {'dev_score': self.scores('dev', choice)[self.metric]}


def index(value, size):
    return type(value) is int and 0 <= value < size
