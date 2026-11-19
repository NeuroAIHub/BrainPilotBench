"""Owner-side experiment journal. Each accepted request commits before its successor can run."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import numpy as np

from . import ACT_THRESHOLD, INSPECTIONS, K, LOSS_THRESHOLD, POSITIONS, PROTOCOL, RANDOM_GROUPS, direction, fingerprint
from .analysis import brain_scores, check_group, fit_brain, inspection, scale_on_search, search, site
from .model import LanguageModel

STAGES = ('open', 'inspect1', 'inspect2', 'freeze', 'probe', 'score', 'conclude')


def journal(root):
    db = sqlite3.connect(Path(root) / 'sessions.sqlite3', timeout=180)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS events (
        actor TEXT, stage TEXT, at TEXT, packet TEXT, request TEXT, response TEXT, artifact TEXT,
        prev TEXT, hash TEXT, PRIMARY KEY(actor, stage))''')
    return db


def event_digest(e):
    return fingerprint([e[k] for k in ('actor', 'stage', 'at', 'packet', 'request', 'response', 'artifact', 'prev')])


def check_event(event, prefix, actor, digest):
    if (len(prefix) >= len(STAGES) or event['stage'] != STAGES[len(prefix)]
            or event['actor'] != actor or event['packet'] != digest
            or event['prev'] != (prefix[-1]['hash'] if prefix else None)
            or event_digest(event) != event['hash']):
        raise ValueError('session identity, sequence or event digest differs')


def history(db, actor, digest):
    events = []
    for row in db.execute('SELECT * FROM events WHERE actor=? ORDER BY rowid', (actor,)):
        e = dict(row)
        for k in ('request', 'response', 'artifact'):
            e[k] = json.loads(e[k])
        check_event(e, events, actor, digest)
        events.append(e)
    return events


def opening(packet):
    sample = packet.pairs['search'][0]
    row = sample['row']
    sid = packet.meta['ids'][row]
    audit = {'id': sid, 'human_trial': packet.meta['trials'][sid], 'original': packet.meta['originals'][row],
             'model_only': sample['reverse'], 'eligible_pairs': {k: len(v) for k, v in packet.pairs.items()}}
    return {'protocol': PROTOCOL, 'packet_sha256': packet.digest, 'model_revision': packet.meta['model_revision'],
            'splits': {name: len(v) for name, v in packet.split.items()}, 'k': K, 'inspections': INSPECTIONS,
            'random_groups': RANDOM_GROUPS, 'thresholds': {'activation_z': ACT_THRESHOLD, 'interaction_nats': LOSS_THRESHOLD},
            'audit': audit, 'sites': search(packet)}


def text_field(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 2500


def freeze_request(packet, request, events):
    group = check_group(packet, request)
    if group not in [e['response']['group'] for e in events if e['stage'].startswith('inspect')]:
        raise ValueError('freeze one of the two inspected groups')
    hypotheses = request.get('hypotheses')
    signs = ('up', 'flat', 'down')
    if (not isinstance(hypotheses, list) or len(hypotheses) != 2
            or any(not isinstance(h, dict) or not text_field(h.get('explanation'))
                   or h.get('activation') not in signs for h in hypotheses)
            or hypotheses[0]['activation'] == hypotheses[1]['activation']):
        raise ValueError('two explanations with different prospective activation directions are required')
    interval = request.get('expected_delta_r')
    if (not isinstance(interval, list) or len(interval) != 2
            or any(type(v) not in (float, int) for v in interval) or not -2 <= interval[0] <= interval[1] <= 2):
        raise ValueError('predict a finite pooled delta-r interval per participant within [-2, 2]')
    if (request.get('contrast') not in ('reverse', 'rotate') or request.get('expected_interaction') not in signs
            or not text_field(request.get('reason'))):
        raise ValueError('provide the chosen contrast, prospective intervention direction and selection reason')
    frozen = fit_brain(packet, group)
    ids = [packet.meta['ids'][p['row']] for p in packet.pairs['confirm']]
    registered = [{'id': sid, 'activation': [h['activation'] for h in hypotheses],
                   'interaction': request['expected_interaction']} for sid in ids]
    return {'group': group, 'registered': registered, 'n_brain_predictions': len(frozen['candidate_ids']),
            'mapping_predictions_sha256': fingerprint(frozen)}, frozen


def probe(packet, frozen_event, model_dir):
    request, frozen = frozen_event['request'], frozen_event['artifact']
    group = frozen['group']
    model = LanguageModel(model_dir)
    pairs = packet.pairs['confirm']
    rows = [p['row'] for p in pairs]
    originals = [packet.meta['originals'][i] for i in rows]
    changed = [p[request['contrast']] for p in pairs]
    pos = POSITIONS.index(group['position'])
    layer, chosen = group['layer'], group['units']
    base = site(packet, group)[:, chosen]
    train = packet.split['search']
    scale = scale_on_search(base, train)
    center = base[train].mean(axis=0, dtype='float64')
    z_original = ((base[rows] - center) / scale).mean(axis=1)
    perturbed, _, _ = model.features(changed)
    z_changed = ((perturbed[:, layer, pos, :][:, chosen] - center) / scale).mean(axis=1)
    groups = [chosen, *frozen['random_groups']]
    lp_original = model.target_probabilities(originals, layer, pos, groups)
    lp_changed = model.target_probabilities(changed, layer, pos, groups)
    observations = []
    for i, commitment in enumerate(frozen_event['response']['registered']):
        sid = packet.meta['ids'][rows[i]]
        if commitment['id'] != sid:
            raise ValueError('confirmation identity differs from registration')
        cells = {}
        for name, lp in [('original', lp_original[i]), ('changed', lp_changed[i])]:
            losses = lp[0] - lp[1:]
            cells[name] = {'base_logp': float(lp[0]), 'selected_logp': float(lp[1]),
                           'random_logp': lp[2:].tolist(), 'selected_loss': float(losses[0]),
                           'random_mean_loss': float(losses[1:].mean()),
                           'extra_loss': float(losses[0] - losses[1:].mean())}
        activation = float(z_original[i] - z_changed[i])
        interaction = cells['original']['extra_loss'] - cells['changed']['extra_loss']
        observations.append({'id': sid, 'original': originals[i], 'changed': changed[i], 'cells': cells,
                             'original_z': float(z_original[i]), 'changed_z': float(z_changed[i]),
                             'activation': activation, 'interaction': interaction})
    activation = float(np.mean([v['activation'] for v in observations]))
    interaction = float(np.mean([v['interaction'] for v in observations]))
    activation_sign, interaction_sign = direction(activation, ACT_THRESHOLD), direction(interaction, LOSS_THRESHOLD)
    hypothesis_scores = []
    for h in request['hypotheses']:
        matches = sum(direction(v['activation'], ACT_THRESHOLD) == h['activation'] for v in observations)
        hypothesis_scores.append({'mean_matches': activation_sign == h['activation'], 'pair_matches': matches})
    return {'n': len(rows), 'activation_mean': activation, 'activation_direction': activation_sign,
            'interaction_mean': interaction, 'interaction_direction': interaction_sign,
            'interaction_matches': interaction_sign == request['expected_interaction'],
            'hypothesis_scores': hypothesis_scores, 'observations': observations}


def perform(packet, stage, request, events, model_dir):
    if stage == 'open':
        return opening(packet), None
    if stage.startswith('inspect'):
        group = check_group(packet, request)
        if not text_field(request.get('reason')):
            raise ValueError('record the reason for this inspection')
        if stage == 'inspect2' and events[-1]['response']['group'] == group:
            raise ValueError('inspect two distinct groups')
        return inspection(packet, group), None
    if stage == 'freeze':
        return freeze_request(packet, request, events)
    frozen = events[STAGES.index('freeze')]
    if stage == 'probe':
        return probe(packet, frozen, model_dir), None
    if stage == 'conclude':
        observed = observed_conclusion(events[4]['response'], events[5]['response'])
        if (not text_field(request.get('conclusion')) or request.get('hypothesis') not in ('first', 'second', 'neither')
                or request.get('interaction') not in ('up', 'flat', 'down')
                or type(request.get('positive_participants')) is not int or not 0 <= request['positive_participants'] <= 3):
            raise ValueError('report the supported hypothesis, interaction, pooled positive participants and conclusion')
        return {'observed': observed, 'checks': {k: request[k] == v for k, v in observed.items()}}, None
    # Rebuild all maps from the locked units and training rows before opening the outcome.
    rebuilt = fit_brain(packet, frozen['response']['group'])
    if fingerprint(rebuilt) != frozen['response']['mapping_predictions_sha256']:
        raise ValueError('recomputed maps or candidate predictions differ from freeze')
    identities, y = packet.outcome()
    scores = brain_scores(rebuilt, identities, y)
    low, high = frozen['request']['expected_delta_r']
    for subject in scores['all']['subjects'].values():
        value = subject['delta_r']
        subject['in_forecast'] = None if value is None else low <= value <= high
    return {'scores': scores, 'model_and_predictions_verified': True,
            'scope': 'observed participants and offline Tuckute drive/suppress pool'}, None


def observed_conclusion(probe_result, score_result):
    hypotheses = ('first', 'second')
    matches = [name for name, h in zip(hypotheses, probe_result['hypothesis_scores']) if h['mean_matches']]
    subjects = score_result['scores']['all']['subjects'].values()
    return {'hypothesis': next(iter(matches), 'neither'), 'interaction': probe_result['interaction_direction'],
            'positive_participants': sum(s['delta_r'] is not None and s['delta_r'] > 0 for s in subjects)}


def verify_run(packet, actor, model_dir):
    db = journal(packet.root)
    try:
        events = history(db, actor, packet.digest)
    finally:
        db.close()
    return replay_events(packet, events, actor, model_dir)


def replay_events(packet, events, actor, model_dir):
    if len(events) != len(STAGES):
        raise ValueError('incomplete session')
    for index, event in enumerate(events):
        check_event(event, events[:index], actor, packet.digest)
        response, artifact = perform(packet, event['stage'], event['request'], events[:index], model_dir)
        if fingerprint([response, artifact]) != fingerprint([event['response'], event['artifact']]):
            raise ValueError('replayed result differs: ' + event['stage'])
    return {'actor': actor, 'packet_sha256': packet.digest, 'verified_stages': list(STAGES),
            'last_event_sha256': events[-1]['hash']}


def call(packet, actor, stage, request, model_dir=None):
    if not text_field(actor) or stage not in STAGES or not isinstance(request, dict):
        raise ValueError('invalid actor, stage or request')
    db = journal(packet.root)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            events = history(db, actor, packet.digest)
            index = STAGES.index(stage)
            if index < len(events):
                if events[index]['request'] != request:
                    raise ValueError('this request was already committed with different parameters')
                return events[index]['response']
            if index != len(events):
                raise ValueError('next required stage: ' + STAGES[len(events)])
            response, artifact = perform(packet, stage, request, events, model_dir)
            event = {'actor': actor, 'stage': stage, 'at': datetime.now(timezone.utc).isoformat(),
                     'packet': packet.digest, 'request': request, 'response': response, 'artifact': artifact,
                     'prev': events[-1]['hash'] if events else None}
            args = [actor, stage, event['at'], packet.digest]
            args.extend(json.dumps(o, ensure_ascii=False, allow_nan=False) for o in (request, response, artifact))
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)', (*args, event['prev'], event_digest(event)))
        return response
    finally:
        db.close()
