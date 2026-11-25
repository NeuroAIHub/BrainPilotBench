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


def record(packet, actor, choice, source_digest=None):
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError('an operator-assigned actor is required')
    selection = packet.choice(choice)
    key = fingerprint([packet.identity, packet.owner_identity])
    with closing(sqlite3.connect(packet.root / 'sessions.sqlite3', timeout=60)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS events (
            packet TEXT, actor TEXT, kind TEXT, slot INTEGER, response TEXT,
            PRIMARY KEY (packet, actor, kind, slot))''')
        rows = db.execute('SELECT kind, response FROM events WHERE packet=? AND actor=? ORDER BY slot',
                          (key, actor)).fetchall()
        queries = [json.loads(reply) for kind, reply in rows if kind == 'query']
        frozen = next((json.loads(reply) for kind, reply in rows if kind == 'freeze'), None)
        if source_digest is not None:
            receipt = {'choice': selection, 'strategy_sha256': source_digest, 'feedback': queries,
                       'owner_sha256': packet.owner_identity}
            receipt['freeze_sha256'] = fingerprint(receipt)
            if frozen is not None:
                if frozen != receipt:
                    raise ValueError('this actor already froze a different submission')
                return frozen
            kind, slot = 'freeze', 0
        else:
            if frozen is not None:
                raise ValueError('submission already frozen')
            for query in queries:
                if query['choice'] == selection:
                    return query
            if len(queries) >= INSPECTIONS:
                raise ValueError('development query budget exhausted')
            kind, slot = 'query', len(queries) + 1
            receipt = {'query': slot, 'choice': selection, 'dev_delta_r': packet.scores('dev', selection)['delta_r']}
        db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (key, actor, kind, slot, json.dumps(receipt, allow_nan=False)))
    return receipt


def benchmark_rows(packet):
    rows = {}
    for policy in ('random', 'top8'):
        choice = packet.choice(select(packet.root / 'public', policy))
        rows[policy] = {'choice': choice, 'scores': packet.results(choice)}
    return rows


def grade(packet, actor, choice, code):
    path = Path(code)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError('expected a nonempty strategy.py of at most 1 MiB')
    source = path.read_bytes()
    receipt = record(packet, actor, choice, hashlib.sha256(source).hexdigest())
    verified = replay(packet, source, receipt)
    scores = packet.results(receipt['choice'])
    return {'model': packet.protocol['model']['id'], 'actor': actor, 'freeze': receipt, 'replay': verified,
            'results': {'agent': {'choice': receipt['choice'], 'scores': scores}, **benchmark_rows(packet)}}
