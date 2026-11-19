"""Export a portable replay from two completed, verified journals."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from real_brainscore.common import read_json, sha256, write_json
from . import PROTOCOL
from .session import STAGES, check_event, history, journal, perform, replay_events


def export_replay(packet, actor, output):
    db = journal(packet.root)
    try:
        histories = {label: history(db, name, packet.digest) for label, name in
                     [('agent', actor), ('baseline', 'fixed-top-k')]}
    finally:
        db.close()
    return write_replay(packet, actor, histories, output)


def restore_replay(packet, record_path, model_dir, output):
    """Recreate a historical demonstration from decisions and receipts without a live session database."""
    record = read_json(record_path)
    if record['protocol'] != PROTOCOL or record['packet_sha256'] != packet.digest:
        raise ValueError('decision record and experiment differ')
    researcher = record['actor']
    histories = {}
    for label, actor in [('agent', researcher), ('baseline', 'fixed-top-k')]:
        events = []
        for row in record['runs'][label]:
            index = len(events)
            if index >= len(STAGES) or row['stage'] != STAGES[index]:
                raise ValueError('unexpected recorded stage')
            response, artifact = perform(packet, row['stage'], row['request'], events, model_dir)
            event = {'actor': actor, 'stage': row['stage'], 'at': row['at'], 'packet': packet.digest,
                     'request': row['request'], 'response': response, 'artifact': artifact,
                     'prev': events[-1]['hash'] if events else None, 'hash': row['hash']}
            check_event(event, events, actor, packet.digest)
            events.append(event)
        histories[label] = events
    return write_replay(packet, researcher, histories, output)


def write_replay(packet, actor, histories, output):
    dest = Path(output).resolve()
    if dest.exists() or actor == 'fixed-top-k':
        raise ValueError('provide a fresh output directory and the independent researcher identity')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as tmp:
        out = Path(tmp) / 'replay'
        out.mkdir()
        runs = {}
        for label, events in histories.items():
            if [e['stage'] for e in events] != list(STAGES):
                raise ValueError('incomplete journal: ' + label)
            write_json(out / (label + '-frozen.json'), events[STAGES.index('freeze')]['artifact'])
            runs[label] = [{k: v for k, v in e.items() if k != 'artifact'} for e in events]
        data = {'protocol': PROTOCOL, 'actor': actor, 'source_sha256': packet.meta['source_csv_sha256'],
                'hidden_manifest_sha256': sha256(packet.root / 'hidden/manifest.json'),
                'runtime': packet.meta['runtime'], 'runs': runs}
        write_json(out / 'events.json', data)
        template = Path(__file__).with_name('replay.html').read_text()
        safe_json = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).replace('<', '\\u003c')
        (out / 'demo.html').write_text(template.replace('<!--EXPERIMENT_DATA-->', safe_json))
        hashes = {p.name: sha256(p) for p in out.iterdir()}
        write_json(out / 'sha256.json', hashes)
        out.rename(dest)
    return {'replay': str(dest / 'demo.html'), 'files': hashes}


def verify_export(packet, bundle, model_dir):
    """Recompute an exported session on a newly prepared packet without the operator database."""
    root = Path(bundle)
    hashes = read_json(root / 'sha256.json')
    if set(hashes) != {'agent-frozen.json', 'baseline-frozen.json', 'events.json', 'demo.html'}:
        raise ValueError('incomplete replay bundle')
    if any(sha256(root / name) != digest for name, digest in hashes.items()):
        raise ValueError('exported artifact digest differs')
    data = read_json(root / 'events.json')
    if (data['protocol'] != PROTOCOL or data['source_sha256'] != packet.meta['source_csv_sha256']
            or data['hidden_manifest_sha256'] != sha256(packet.root / 'hidden/manifest.json')):
        raise ValueError('export and prepared experiment differ')
    reports = []
    for label, actor in [('agent', data['actor']), ('baseline', 'fixed-top-k')]:
        events = data['runs'][label]
        maps = read_json(root / (label + '-frozen.json'))
        for event in events:
            event['artifact'] = maps if event['stage'] == 'freeze' else None
        reports.append(replay_events(packet, events, actor, model_dir))
    return reports
