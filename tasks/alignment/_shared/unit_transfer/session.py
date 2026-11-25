"""Per-packet, operator-assigned researcher sessions, with atomic budget and freeze."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from multiscale import fingerprint
from . import INSPECTIONS
from .reference import select
from .replay import replay


def _history(db, key, actor, kind):
    rows = db.execute('SELECT response FROM events WHERE packet=? AND actor=? AND kind=? ORDER BY slot',
                      (key, actor, kind))
    return [json.loads(row[0]) for row in rows]


def _available(db, key, actor, kind, selection):
    if _history(db, key, actor, 'freeze'):
        raise ValueError('submission already frozen')
    history = _history(db, key, actor, kind)
    for reply in history:
        if reply['choice'] == selection:
            return reply, None
    if kind == 'query' and len(history) >= INSPECTIONS:
        raise ValueError('development query budget exhausted')
    return None, len(history) + 1


def record(packet, actor, choice, source_digest=None, *, training=False):
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError('an operator-assigned actor is required')
    if training and (source_digest is not None or not hasattr(packet, 'training_feedback')):
        raise ValueError('unsupported training probe')
    selection = packet.choice(choice) if source_digest is not None else packet.query_choice(choice)
    key = fingerprint([packet.identity, packet.owner_identity])
    kind = 'probe' if training else 'query'
    with closing(sqlite3.connect(packet.root / 'sessions.sqlite3', timeout=60)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS events (
                packet TEXT, actor TEXT, kind TEXT, slot INTEGER, response TEXT,
                PRIMARY KEY (packet, actor, kind, slot))''')
            if source_digest is not None:
                receipt = {'choice': selection, 'strategy_sha256': source_digest,
                           'feedback': _history(db, key, actor, 'query'), 'owner_sha256': packet.owner_identity}
                probes = _history(db, key, actor, 'probe')
                if probes:
                    receipt['training_feedback'] = probes
                receipt['freeze_sha256'] = fingerprint(receipt)
                frozen = _history(db, key, actor, 'freeze')
                if frozen:
                    if frozen[0] != receipt:
                        raise ValueError('this actor already froze a different submission')
                    return frozen[0]
                db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                           (key, actor, 'freeze', 0, json.dumps(receipt, allow_nan=False)))
                return receipt
            cached, _ = _available(db, key, actor, kind, selection)
            if cached is not None:
                return cached

        # Model inference can take minutes. Other researchers can query or freeze during it.
        feedback = packet.training_feedback(selection) if training else packet.development_feedback(selection)
        with db:
            db.execute('BEGIN IMMEDIATE')
            cached, slot = _available(db, key, actor, kind, selection)
            if cached is not None:
                return cached
            receipt = {kind: slot, 'choice': selection, **feedback}
            db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (key, actor, kind, slot, json.dumps(receipt, allow_nan=False)))
            return receipt


def benchmark_rows(packet):
    rows = {}
    for policy in ('random', 'top8'):
        choice = packet.choice(select(packet.root / 'public', policy))
        rows[policy] = {'choice': choice, 'scores': packet.results(choice)}
    return rows


def freeze_and_replay(packet, actor, choice, code):
    path = Path(code)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError('expected a nonempty strategy.py of at most 1 MiB')
    source = path.read_bytes()
    receipt = record(packet, actor, choice, hashlib.sha256(source).hexdigest())
    return receipt, replay(packet, source, receipt)


def grade(packet, actor, choice, code):
    receipt, verified = freeze_and_replay(packet, actor, choice, code)
    scores = packet.results(receipt['choice'])
    return {'model': packet.protocol['model']['id'], 'actor': actor, 'freeze': receipt, 'replay': verified,
            'results': {'agent': {'choice': receipt['choice'], 'scores': scores}, **benchmark_rows(packet)}}
