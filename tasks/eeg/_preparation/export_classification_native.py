"""Data-only export of one native classification study into auditable shards.

Resolves the pinned native source, replays the calibrated recipe against the
whole declared population and writes fixed-order shards plus a private
per-sample lineage record. It never trains, never fits a model, never launches
an agent and never registers a public task; publishing a task from these shards
is a separate step, and so is any claim that the agent pipeline is complete.

Only classification is in scope, and the gate is explicit: other task kinds get
their own adapter rather than being coerced through this one. Nothing here
monkeypatches native scientific behaviour. The native dataset ordering, label
mapping and split are authoritative and are audited, not replaced.

The caller owns isolation. Raw data stays wherever --data points, the source
checkout must sit on the pinned commit with a clean tracked tree, and the
process must already sit in its own network namespace. The trusted launcher
captures its own namespace id first and hands it over, because inside an
unprivileged namespace only /proc/self/ns/net stays readable:

    origin=$(readlink /proc/self/ns/net)
    NEURALBENCH_PREP_ORIGIN_NETNS="$origin" unshare --user --map-current-user --net \
        python tasks/eeg/_preparation/export_classification_native.py ...

There is deliberately no CLI flag to skip that check, and no platform on which
it silently degrades to unenforced.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib
import itertools
import json
import math
import os
import platform
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

PIN = 'a8092dc10956038e445ff0e07f9c0c7e03a10d36'
NATIVE_PACKAGES = ('neuralbench', 'neuralset', 'neuralfetch', 'neuraltrain')
SPLITS = ('train', 'val', 'test')
SHARD_BATCH = 32
SHARD_SEED = 33
NATIVE_THREADS = 2

METRIC_LOG_NAME = 'bal_acc'
METRIC_NAME = 'Accuracy'
TARGET_ENCODER = 'LabelEncoder'
TARGET_AGGREGATION = 'trigger'
TRIGGER_PROFILE = 'native-classification-trigger'
SEIZURE_PROFILE = 'native-seizure-sum-missing-last-v1'

# The one native profile whose target aggregates a scored epoch instead of a
# trigger. It is an explicit exception for two pinned studies, not a relaxation
# of the aggregation gate: every clause below is checked before it opens, and
# there is no flag, config value or CLI option that opens it any other way.
SLEEP_STAGE_PROFILE = 'native-sleep-stage-single'
SLEEP_TARGET_AGGREGATION = 'single'
SLEEP_TASK_SOURCES = {'sleep_stage/default': 'Kemp2000Analysis',
                      'sleep_stage/alvarez2022haaglanden': 'Alvarez2022Haaglanden'}
SLEEP_EVENT_TYPE = 'SleepStage'
SLEEP_EVENT_FIELD = 'stage'
SLEEP_DURATION = 30.0
SLEEP_NUM_CLASSES = 5
SLEEP_SPLIT = 'SklearnSplit'
SLEEP_SPLIT_BY = 'subject'
SLEEP_CROP_STEP = 'crop_sleep_recordings'
SLEEP_CROP_NAME = 'CropSleepRecordings'
SLEEP_MAX_WAKE_MIN = 30.0
SLEEP_STEP_ORDER = ('source', SLEEP_CROP_STEP, 'split')
SLEEP_TARGET_FIELDS = (('aggregation', SLEEP_TARGET_AGGREGATION), ('allow_missing', True),
                       ('return_one_hot', True), ('treat_missing_as_separate_class', False),
                       ('frequency', 0))

EVENT_SPLIT_BY = '_index'
# split_by values whose scientific group key is something other than the session,
# so a null session is a real property of the population and never blocks them.
SESSION_OPTIONAL_SPLIT_BY = (EVENT_SPLIT_BY, 'subject')

ORIGIN_NETNS_ENV = 'NEURALBENCH_PREP_ORIGIN_NETNS'
NETNS_PATTERN = re.compile(r'^net:\[[0-9]+\]$')
# Reachability probes: the namespace is only accepted if none of them connects.
# Neutral public endpoint only; never embed maintainer infrastructure addresses.
NETWORK_PROBES = (('1.1.1.1', 443),)
PROBE_TIMEOUT = 1.0
PREDEFINED_SPLIT = 'PredefinedSplit'
ZHOU_SOURCE_PREFIX = 'Zhou'
ZHOU_TEST_SESSION = '2'

# Known locations of each config block, tried in order. A block that moves gets
# added here explicitly; nothing is discovered by a generic deep search.
SOURCE_BLOCKS = (('data', 'study', 'steps', 'source'),)
SPLIT_BLOCKS = (('data', 'study', 'steps', 'split'),)
TARGET_BLOCKS = (('data', 'study', 'steps', 'target'), ('data', 'target'))
STEPS_BLOCKS = (('data', 'study', 'steps'),)
# Blocks that may carry a top-level data setting such as duration or the trigger
# event type, tried in order; nothing is discovered by a generic deep search.
SETTING_BLOCKS = (('data',), ('data', 'study'))
METRIC_BLOCKS = (('metrics',), ('task', 'metrics'), ('module', 'metrics'), ('trainer', 'metrics'))

INFRA_OVERRIDES = (('folder', None), ('max_jobs', 2), ('keep_in_ram', False),
                   ('cluster', None), ('gpus_per_node', 0), ('cpus_per_task', 2))
LOADER_OVERRIDES = (('batch_size', SHARD_BATCH), ('num_workers', 0),
                    ('pin_memory', False), ('persistent_workers', False))
# Scientific settings that normalization must never touch, checked by name
# against the change receipt on top of the full allowlisted diff.
PRESERVED_KEYS = ('split', 'split_by', 'valid_split_by', 'template', 'labels', 'windows', 'window',
                  'filter', 'scaler', 'sample_freq', 'sfreq', 'metrics', 'seed', 'random_state',
                  'exclusions', 'exclude', 'transforms', 'target', 'event_field')
_MISSING = object()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _plain(value):
    """JSON-friendly copy of a native field. Strings and numbers keep their identity."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    item = getattr(value, 'item', None)
    if callable(item):
        try:
            return _plain(item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _locate(config, candidates, label, kind=dict):
    """Return (block, dotted path) for the first candidate location of the wanted kind."""
    for path in candidates:
        node = config
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, kind) and node:
            return node, '.'.join(path)
    raise ValueError('Config exposes no %s block at any known location' % label)


def verify_source_checkout(source):
    """The pinned commit must be checked out with no uncommitted tracked change."""
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if head != PIN:
        raise ValueError('Source HEAD is %s, not the pinned %s' % (head, PIN))
    dirty = subprocess.check_output(
        ['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    if dirty:
        raise ValueError('Pinned source has uncommitted tracked changes:\n' + dirty)
    return {'head': head, 'tracked_tree_clean': True, 'path': str(source)}


def _probe_reachable(host, port):
    """True only if a TCP connection actually completes inside the timeout."""
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def verify_network_namespace(fixture=False):
    """Require a private net namespace with no reachable external endpoint.

    /proc/1/ns/net is deliberately not read: inside an unprivileged user+net
    namespace that read is denied, so the launcher passes its own namespace id
    in NEURALBENCH_PREP_ORIGIN_NETNS instead. A missing, malformed or identical
    origin is a failure, and so is any endpoint that still answers. fixture is
    for unit tests of the callers only.
    """
    system = platform.system()
    if fixture:
        return {'enforced': False, 'platform': system, 'reason': 'test fixture'}
    origin = os.environ.get(ORIGIN_NETNS_ENV)
    if not origin:
        raise ValueError(
            '%s is unset; the trusted launcher must capture origin=$(readlink /proc/self/ns/net) '
            'outside and run this export under `unshare --user --map-current-user --net`'
            % ORIGIN_NETNS_ENV)
    if not NETNS_PATTERN.match(origin):
        raise ValueError('%s is %r, which is not a net:[<inode>] namespace identity'
                         % (ORIGIN_NETNS_ENV, origin))
    try:
        mine = os.readlink('/proc/self/ns/net')
    except OSError as exc:
        raise ValueError('Cannot read /proc/self/ns/net on %s, so private-namespace isolation cannot be '
                         'proved and this export does not run unenforced: %s' % (system, exc))
    if not NETNS_PATTERN.match(mine):
        raise ValueError('/proc/self/ns/net reads %r, which is not a net:[<inode>] namespace identity'
                         % mine)
    if mine == origin:
        raise ValueError('Network namespace %s is still the launcher namespace; run this export under '
                         '`unshare --user --map-current-user --net`' % mine)
    reachable = [{'host': host, 'port': port} for host, port in NETWORK_PROBES
                 if _probe_reachable(host, port)]
    if reachable:
        raise ValueError('Network namespace %s still reaches external endpoints: %s'
                         % (mine, json.dumps(reachable)))
    return {'enforced': True, 'platform': system, 'self_ns': mine, 'origin_ns': origin,
            'origin_env': ORIGIN_NETNS_ENV,
            'checks': {'origin_namespace_declared': True, 'origin_namespace_well_formed': True,
                       'namespace_differs_from_origin': True, 'init_namespace_read': False,
                       'probes_attempted': len(NETWORK_PROBES), 'probes_connected': 0,
                       'probe_timeout_s': PROBE_TIMEOUT},
            'probes': [{'host': host, 'port': port, 'connected': False} for host, port in NETWORK_PROBES]}


def verify_module_origins(source):
    """Import lazy native packages and bind every search location to the checkout."""
    root, origins = Path(source).resolve(), {}
    for name in NATIVE_PACKAGES:
        expected = (root / (name + '-repo') / name).resolve(strict=True)
        if root not in expected.parents or not expected.is_dir():
            raise ValueError('%s package directory escapes the pinned source' % name)
        module = importlib.import_module(name)
        spec = getattr(module, '__spec__', None)
        if getattr(module, '__name__', None) != name or spec is None or spec.name != name:
            raise ValueError('%s has no matching import specification' % name)
        locations = list(spec.submodule_search_locations or [])
        canonical_locations = [Path(path).resolve(strict=True) for path in locations]
        if canonical_locations != [expected]:
            raise ValueError('%s has foreign or missing package search locations: %r' %
                             (name, [str(path) for path in canonical_locations]))
        file = getattr(module, '__file__', None)
        if file:
            resolved = Path(file).resolve(strict=True)
            if expected not in resolved.parents:
                raise ValueError('%s resolves outside the pinned source: %s' % (name, resolved))
            origin = getattr(spec, 'origin', None)
            if not origin or Path(origin).resolve(strict=True) != resolved:
                raise ValueError('%s file and import specification disagree' % name)
            file_record = str(resolved)
        else:
            if spec.origin not in (None, 'namespace'):
                raise ValueError('%s has no file but is not a namespace package' % name)
            file_record = None
        origins[name] = {'file': file_record, 'search_locations': [str(expected)],
                         'version': _plain(getattr(module, '__version__', None))}
    return origins


def validate_calibration_manifest(manifest):
    """Accept only a calibrated manifest built against the pinned source."""
    if not isinstance(manifest, dict):
        raise ValueError('Calibrated manifest must be a JSON object')
    if manifest.get('source_sha') != PIN:
        raise ValueError('Calibrated manifest was produced against %r, not the pinned %s'
                         % (manifest.get('source_sha'), PIN))
    config = manifest.get('resolved_config')
    if not isinstance(config, dict) or not config:
        raise ValueError('Calibrated manifest carries no resolved_config')
    return config


def _set(container, key, value, path, changes, only_if_present=False):
    before = container.get(key, _MISSING)
    if only_if_present and before is _MISSING:
        return
    if before is not _MISSING and type(before) is type(value) and before == value:
        return
    container[key] = value
    changes.append({'path': path, 'before': None if before is _MISSING else before,
                    'present_before': before is not _MISSING, 'after': value})


def _apply_infra(node, prefix, cache_dir, changes):
    """Rewrite every nested infra block; the rest of the tree is only walked."""
    if isinstance(node, dict):
        for key, value in node.items():
            path = '%s.%s' % (prefix, key) if prefix else key
            if key == 'infra' and isinstance(value, dict):
                for field, override in INFRA_OVERRIDES:
                    _set(value, field, cache_dir if field == 'folder' else override,
                         '%s.%s' % (path, field), changes, only_if_present=True)
            else:
                _apply_infra(value, path, cache_dir, changes)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _apply_infra(value, '%s[%d]' % (prefix, index), cache_dir, changes)


def normalize_config(config, data_root, cache_dir):
    """Point the frozen recipe at the full local source and this build's resources.

    Returns (config, changes); every edit is recorded with its dotted path and
    its before/after value, so the receipt is the complete story of the diff.
    """
    updated = copy.deepcopy(config)
    changes = []
    source, source_path = _locate(updated, SOURCE_BLOCKS, 'source')
    _set(source, 'path', str(data_root), source_path + '.path', changes)
    _set(source, 'query', None, source_path + '.query', changes)
    _apply_infra(updated, '', str(cache_dir), changes)
    data = updated.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('neuro'), dict):
        raise ValueError('Config exposes no data/data.neuro block')
    for field, override in LOADER_OVERRIDES:
        _set(data, field, override, 'data.' + field, changes)
    _set(data['neuro'], 'mne_cpus', 1, 'data.neuro.mne_cpus', changes)
    for change in changes:
        if change['path'].rsplit('.', 1)[-1] in PRESERVED_KEYS:
            raise ValueError('Normalization must not touch the scientific field ' + change['path'])
    return updated, changes


def config_diff(before, after, prefix=''):
    """Dotted paths at which two configs differ. Types are compared, so 1 != True."""
    paths = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            path = '%s.%s' % (prefix, key) if prefix else key
            if key not in before or key not in after:
                paths.append(path)
            else:
                paths.extend(config_diff(before[key], after[key], path))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            paths.append(prefix)
        else:
            for index, (a, b) in enumerate(zip(before, after)):
                paths.extend(config_diff(a, b, '%s[%d]' % (prefix, index)))
    elif type(before) is not type(after) or before != after:
        paths.append(prefix)
    return paths


def assert_only_allowed_changes(before, after, changes):
    """The real diff must be covered by the recorded receipt, path by path."""
    allowed = {change['path'] for change in changes}
    unexpected = [path for path in config_diff(before, after) if path not in allowed]
    if unexpected:
        raise ValueError('Config changed outside the recorded receipt: ' + ', '.join(unexpected))
    return sorted(allowed)


def validate_source_block(source, expected_name):
    """The export is bound to one named source and to the whole population."""
    name = source.get('name')
    if name != expected_name:
        raise ValueError('Config source is %r, not the expected %r' % (name, expected_name))
    if source.get('query') is not None:
        raise ValueError('source query must be null: no subset of the source population')
    return {'name': name, 'query': None, 'path': source.get('path')}


def validate_metrics(metrics):
    """Return the class count declared by the primary balanced-accuracy metric."""
    entries = [m for m in metrics if isinstance(m, dict) and m.get('log_name') == METRIC_LOG_NAME]
    if len(entries) != 1:
        raise ValueError('Expected exactly one %r metric, found %d' % (METRIC_LOG_NAME, len(entries)))
    metric = entries[0]
    if metric.get('name') != METRIC_NAME:
        raise ValueError('%s must be computed by %s, not %r' % (METRIC_LOG_NAME, METRIC_NAME, metric.get('name')))
    kwargs = metric.get('kwargs')
    if not isinstance(kwargs, dict):
        raise ValueError('%s declares no kwargs' % METRIC_LOG_NAME)
    for field, expected in (('task', 'multiclass'), ('average', 'macro')):
        if kwargs.get(field) != expected:
            raise ValueError('%s kwargs.%s must be %r, not %r'
                             % (METRIC_LOG_NAME, field, expected, kwargs.get(field)))
    num_classes = kwargs.get('num_classes')
    if type(num_classes) is not int or num_classes < 2:
        raise ValueError('%s kwargs.num_classes must be an integer >= 2, not %r'
                         % (METRIC_LOG_NAME, num_classes))
    return num_classes


def validate_target(target, allowed_aggregation=TARGET_AGGREGATION):
    """Only the one-hot LabelEncoder/trigger target is supported; return its event field.

    allowed_aggregation stays the trigger aggregation for every caller that does
    not hand over a fully verified native profile; target_profile is the only
    place that widens it, only for explicitly checked native task profiles.
    """
    declared = [value for key in ('encoder', 'name', 'type', '_target_')
                for value in [target.get(key)] if isinstance(value, str)]
    if not any(value.rsplit('.', 1)[-1] == TARGET_ENCODER for value in declared):
        raise ValueError('Unsupported target %r: this adapter only exports a %s target'
                         % (declared or None, TARGET_ENCODER))
    if target.get('aggregation') != allowed_aggregation:
        raise ValueError('Target aggregation must be %r, not %r' % (allowed_aggregation, target.get('aggregation')))
    if target.get('return_one_hot') is not True:
        raise ValueError('Target must return one-hot labels; this adapter never reshapes them silently')
    event_field = target.get('event_field')
    if not isinstance(event_field, str) or not event_field:
        raise ValueError('Target declares no event_field')
    return event_field


def _exact(value, expected):
    """Type-aware equality: 1 is never True, and a number keeps its numeric identity."""
    if isinstance(expected, bool) or isinstance(value, bool):
        return value is expected
    if isinstance(expected, (int, float)):
        return isinstance(value, (int, float)) and value == expected
    return type(value) is type(expected) and value == expected


def _event_types(value):
    return (value,) if isinstance(value, str) else tuple(value) if isinstance(value, (list, tuple)) else ()


def _setting(config, key, label):
    """One declared data setting, read from a known block rather than searched for."""
    for path in SETTING_BLOCKS:
        node = config
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict) and key in node:
            return node[key]
    raise ValueError('Config declares no %s at any known location (%s)'
                     % (label, ', '.join('.'.join(path + (key,)) for path in SETTING_BLOCKS)))


def _sleep_stage_contract(config, task_id, source_name, target):
    """Receipt for the pinned sleep-stage pair, or None when this is another study.

    Returning None leaves the caller on the trigger-only gate. Anything that
    matches the pair by task id or by source but breaks one clause of the native
    contract raises here: the config is never edited to fit the exception.
    """
    expected_source = SLEEP_TASK_SOURCES.get(task_id)
    if expected_source is None:
        if source_name in set(SLEEP_TASK_SOURCES.values()):
            raise ValueError('Source %r is a pinned sleep-stage source but task %r is not one of %r; no '
                             'sleep profile is assumed from the source alone'
                             % (source_name, task_id, sorted(SLEEP_TASK_SOURCES)))
        return None
    if source_name != expected_source:
        raise ValueError('Task %r is pinned to source %r, not %r' % (task_id, expected_source, source_name))
    source, _ = _locate(config, SOURCE_BLOCKS, 'source')
    if source.get('name') != expected_source:
        raise ValueError('Sleep-stage config declares source %r, not the pinned %r'
                         % (source.get('name'), expected_source))
    if source.get('query') is not None:
        raise ValueError('Sleep-stage source query must be null: no subset of the source population')
    steps, _ = _locate(config, STEPS_BLOCKS, 'steps')
    order = tuple(key for key in steps if key in SLEEP_STEP_ORDER)
    if order != SLEEP_STEP_ORDER:
        raise ValueError('Sleep-stage pipeline is %r, not %r' % (list(order), list(SLEEP_STEP_ORDER)))
    crop = steps[SLEEP_CROP_STEP]
    if not isinstance(crop, dict) or _declared_name(crop) != SLEEP_CROP_NAME:
        raise ValueError('Sleep-stage crop step must be a %s block, not %r'
                         % (SLEEP_CROP_NAME, crop if not isinstance(crop, dict) else _declared_name(crop)))
    if not _exact(crop.get('max_wake_duration_min'), SLEEP_MAX_WAKE_MIN):
        raise ValueError('%s.max_wake_duration_min must be %r, not %r'
                         % (SLEEP_CROP_NAME, SLEEP_MAX_WAKE_MIN, crop.get('max_wake_duration_min')))
    split, _ = _locate(config, SPLIT_BLOCKS, 'split')
    if _declared_name(split) != SLEEP_SPLIT or split.get('split_by') != SLEEP_SPLIT_BY:
        raise ValueError('Sleep-stage split must be %s split_by %r, not %r split_by %r'
                         % (SLEEP_SPLIT, SLEEP_SPLIT_BY, _declared_name(split), split.get('split_by')))
    duration = _setting(config, 'duration', 'window duration')
    if not _exact(duration, SLEEP_DURATION):
        raise ValueError('Sleep-stage window duration must be %r, not %r' % (SLEEP_DURATION, duration))
    event_type = _setting(config, 'trigger_event_type', 'trigger event type')
    if event_type != SLEEP_EVENT_TYPE:
        raise ValueError('Sleep-stage trigger event type must be %r, not %r' % (SLEEP_EVENT_TYPE, event_type))
    if _event_types(target.get('event_types')) != (SLEEP_EVENT_TYPE,):
        raise ValueError('Sleep-stage target event_types must be exactly %r, not %r'
                         % (SLEEP_EVENT_TYPE, target.get('event_types')))
    if target.get('event_field') != SLEEP_EVENT_FIELD:
        raise ValueError('Sleep-stage target event_field must be %r, not %r'
                         % (SLEEP_EVENT_FIELD, target.get('event_field')))
    for field, expected in SLEEP_TARGET_FIELDS:
        if not _exact(target.get(field), expected):
            raise ValueError('Sleep-stage target %s must be %r, not %r' % (field, expected, target.get(field)))
    metrics, _ = _locate(config, METRIC_BLOCKS, 'metrics', kind=list)
    num_classes = validate_metrics(metrics)
    if num_classes != SLEEP_NUM_CLASSES:
        raise ValueError('Sleep-stage export expects %d classes, not %d' % (SLEEP_NUM_CLASSES, num_classes))
    return {'task_id': task_id, 'source': expected_source, 'duration': duration,
            'trigger_event_type': event_type, 'pipeline': list(order),
            'max_wake_duration_min': crop.get('max_wake_duration_min'),
            'split': _declared_name(split), 'split_by': split.get('split_by'),
            'num_classes': num_classes, 'source_population_query': None}


def target_profile(config, task_id, source_name):
    """Resolve which native target profile this study may export under.

    The trigger profile is the default and the only one a config can reach by
    itself. The sleep-stage profile is opened here alone, and only when the
    pinned (task, source) pair and the whole native sleep contract match.
    """
    target, target_path = _locate(config, TARGET_BLOCKS, 'target')
    if task_id == 'seizure/default' or source_name == 'Dan2023Bids':
        import seizure_contract
        contract = seizure_contract.validate_profile(
            config, task_id=task_id, source_name=source_name, source_sha=PIN)
        event_field = validate_target(target, allowed_aggregation='sum')
        return {'profile': SEIZURE_PROFILE, 'event_field': event_field,
                'native_target_aggregation': 'sum', 'target_location': target_path,
                'checks': contract, 'target_contract_module': {
                    'name': 'seizure_contract.py', 'sha256': digest(seizure_contract.__file__)}}
    contract = _sleep_stage_contract(config, task_id, source_name, target)
    aggregation = SLEEP_TARGET_AGGREGATION if contract else TARGET_AGGREGATION
    event_field = validate_target(target, allowed_aggregation=aggregation)
    return {'profile': SLEEP_STAGE_PROFILE if contract else TRIGGER_PROFILE,
            'event_field': event_field, 'native_target_aggregation': target.get('aggregation'),
            'target_location': target_path, 'checks': contract}


def label_mapping_records(label_to_ind, num_classes):
    """Native mapping as an ordered list; keys stay int or str, never stringified."""
    records = sorted(({'native_label': _plain(label), 'type': type(label).__name__, 'index': int(index)}
                      for label, index in label_to_ind.items()), key=lambda record: record['index'])
    if [record['index'] for record in records] != list(range(num_classes)):
        raise ValueError('Native label mapping does not cover 0..%d exactly' % (num_classes - 1))
    return records


def classification_mapping(label_to_ind, num_classes, profile):
    if profile == SEIZURE_PROFILE:
        import seizure_contract
        return seizure_contract.label_mapping_records(label_to_ind, num_classes)
    return label_mapping_records(label_to_ind, num_classes)


def classification_lineage(order, segment, record, native_target, plan, waveform, label):
    if plan.get('target_profile') == SEIZURE_PROFILE:
        import seizure_contract
        entry = seizure_contract.lineage_entry(
            order, segment, record, native_target, plan['label_to_ind'], waveform)
        if entry['label'] != label:
            raise ValueError('Native sum-window audit disagrees with the serialized class index')
        return entry
    return lineage_entry(order, segment, record, plan['event_field'],
                         plan['label_to_ind'], plan['allow_missing_session'], waveform, label)


def one_hot_to_int64(y, num_classes):
    """Strict one-hot [N,K] of 0/1 with row sum 1 -> int64 class indices."""
    import numpy as np
    array = np.asarray(y)
    if array.ndim != 2 or array.shape[1] != num_classes:
        raise ValueError('Expected one-hot targets shaped [N,%d], got %r' % (num_classes, array.shape))
    if not np.isfinite(array).all():
        raise ValueError('Non-finite target value')
    if not ((array == 0) | (array == 1)).all():
        raise ValueError('Soft targets are not exportable: every target entry must be 0 or 1')
    if not (array.sum(axis=1) == 1).all():
        raise ValueError('Each one-hot row must select exactly one class')
    return array.argmax(axis=1).astype('int64')


def check_class_coverage(labels, num_classes, split):
    """Every fold of a classification export must contain all of 0..K-1."""
    present = sorted({int(value) for value in labels})
    if present != list(range(num_classes)):
        raise ValueError('Split %s covers classes %r, not 0..%d' % (split, present, num_classes - 1))
    return present


def waveform_sha256(row):
    import numpy as np
    return hashlib.sha256(np.ascontiguousarray(row).tobytes()).hexdigest()


def _assert_window(order, start, duration):
    """A window is only usable if it is finite, non-negative and has real extent."""
    for name, value in (('start', start), ('duration', duration)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('Sample %r has a non-numeric window %s (%r)' % (order, name, value))
        if not math.isfinite(value):
            raise ValueError('Sample %r has a non-finite window %s (%r)' % (order, name, value))
    if start < 0:
        raise ValueError('Sample %r starts at %r, before the beginning of its timeline' % (order, start))
    if duration <= 0:
        raise ValueError('Sample %r has a non-positive window duration (%r)' % (order, duration))


def lineage_entry(order, segment, record, event_field, label_to_ind, allow_missing_session, waveform, label):
    """One private lineage row, audited against the native trigger and not against y alone."""
    trigger = segment.trigger
    fields = trigger.to_dict()
    native_index = record.get('Index', fields.get('Index'))
    if native_index is None:
        raise ValueError('Sample %d carries no native trigger Index' % order)
    if 'Index' in record and 'Index' in fields and record['Index'] != fields['Index']:
        raise ValueError('Sample %d: segment and trigger table disagree on the native Index' % order)
    session = fields.get('session')
    if session is None and not allow_missing_session:
        raise ValueError('Sample %d has no session, which this split groups by; no session identity is '
                         'invented here' % order)
    subject = fields.get('subject')
    if subject is None or (isinstance(subject, str) and not subject.strip()):
        raise ValueError('Sample %d has no subject; every lineage row carries its real subject' % order)
    timeline = getattr(segment, 'timeline', fields.get('timeline'))
    if timeline is None or (isinstance(timeline, str) and not timeline.strip()):
        raise ValueError('Sample %d has no timeline to place its window on' % order)
    value = trigger._get_field_or_extra(event_field)
    if value not in label_to_ind:
        raise ValueError('Sample %d carries %r for %s, which is outside the native label mapping'
                         % (order, value, event_field))
    encoded = int(label_to_ind[value])
    if encoded != label:
        raise ValueError('Sample %d: emitted label %d disagrees with the native mapping (%d)'
                         % (order, label, encoded))
    start, duration = _plain(segment.start), _plain(segment.duration)
    _assert_window(order, start, duration)
    return {'index': order, 'subject': _plain(subject), 'session': _plain(session),
            'timeline': _plain(timeline),
            'start': start, 'duration': duration,
            'trigger_index': _plain(native_index), 'event_field': event_field,
            'event_value': _plain(value), 'label': label, 'waveform_sha256': waveform}


def _declared_name(block):
    for key in ('name', 'type', '_target_', 'strategy'):
        value = block.get(key)
        if isinstance(value, str) and value:
            return value.rsplit('.', 1)[-1]
    return None


def _values(rows, field):
    return {row[field] for row in rows}


def _assert_disjoint(lineage, field, label):
    for left, right in itertools.combinations(sorted(lineage), 2):
        shared = _values(lineage[left], field) & _values(lineage[right], field)
        if shared:
            raise ValueError('%s leakage between %s and %s: %s'
                             % (label, left, right, sorted(map(repr, shared))[:10]))


OVERLAP_REPORT_LIMIT = 64


def _window_overlaps(lineage):
    """Same-timeline windows must not overlap in time across folds.

    Adjacent comparison misses a window nested inside an earlier, longer one, so
    this sweeps each timeline and keeps every interval that is still open at the
    current start. A window that merely touches another (end == start) does not
    overlap, and no tolerance is added around that boundary.
    """
    windows, overlaps = {}, []
    for split, rows in lineage.items():
        for row in rows:
            start, duration = row['start'], row['duration']
            _assert_window(row['index'], start, duration)
            key = (row['subject'], row['session'], row['timeline'])
            windows.setdefault(key, []).append((start, start + duration, split, row['index']))
    for key in sorted(windows, key=repr):
        active = []
        for start, end, split, index in sorted(windows[key], key=lambda entry: (entry[0], entry[1], repr(entry[2:]))):
            active = [open_window for open_window in active if open_window[1] > start]
            for a_start, a_end, a_split, a_index in active:
                if a_split != split:
                    overlaps.append({'timeline': [_plain(part) for part in key], 'first_split': a_split,
                                     'first_index': a_index, 'second_split': split, 'second_index': index})
                    if len(overlaps) >= OVERLAP_REPORT_LIMIT:
                        return overlaps
            active.append((start, end, split, index))
    return overlaps


def validate_split_groups(split_block, lineage, expected_source_name):
    """Check fold disjointness the way this study actually splits, and no other way."""
    split_by = split_block.get('split_by')
    valid_split_by = split_block.get('valid_split_by')
    declared = _declared_name(split_block)
    report = {'declared_split': declared, 'split_by': split_by, 'valid_split_by': valid_split_by,
              'groups': {split: {'samples': len(rows),
                                 'subjects': sorted(_values(rows, 'subject'), key=repr),
                                 'sessions': sorted((v for v in _values(rows, 'session') if v is not None), key=repr),
                                 'null_sessions': sum(1 for row in rows if row['session'] is None),
                                 'trigger_indices': len(_values(rows, 'trigger_index'))}
                         for split, rows in sorted(lineage.items())}}
    null_sessions = [row['index'] for rows in lineage.values() for row in rows if row['session'] is None]
    # The subject is the group key of the population itself, so it is required on every
    # row whatever the split groups by. The session is only required when it is the key.
    missing_subjects = [row['index'] for rows in lineage.values() for row in rows
                        if row['subject'] is None
                        or (isinstance(row['subject'], str) and not row['subject'].strip())]
    if missing_subjects:
        raise ValueError('Lineage rows carry no subject: %s' % json.dumps(missing_subjects[:10]))
    report['null_session_rows'] = len(null_sessions)
    if split_by == 'subject':
        _assert_disjoint(lineage, 'subject', 'Subject')
        report['rule'] = 'subject-disjoint'
    elif split_by == EVENT_SPLIT_BY:
        _assert_disjoint(lineage, 'trigger_index', 'Trigger index')
        overlaps = _window_overlaps(lineage)
        if overlaps:
            raise ValueError('Same-timeline windows overlap across folds: ' + json.dumps(overlaps[:10]))
        report.update(rule='trigger-index-disjoint + non-overlapping same-timeline windows',
                      cross_fold_window_overlaps=0)
    elif declared == PREDEFINED_SPLIT and valid_split_by == 'session':
        if null_sessions:
            raise ValueError('This split groups by session, so a null session cannot be placed in a fold '
                             'and none is invented: rows %s' % json.dumps(null_sessions[:10]))
        _assert_disjoint(lineage, 'session', 'Session')
        report['rule'] = 'session-disjoint'
        if expected_source_name.startswith(ZHOU_SOURCE_PREFIX):
            sessions = _values(lineage['test'], 'session')
            if sessions != {ZHOU_TEST_SESSION}:
                raise ValueError('%s holds out %s as test, not session %r'
                                 % (expected_source_name, sorted(map(repr, sessions)), ZHOU_TEST_SESSION))
            report['held_out_test_session'] = ZHOU_TEST_SESSION
    else:
        raise ValueError('Unsupported native split strategy (%r, split_by=%r, valid_split_by=%r); no '
                         'generic cross-subject rule is assumed here' % (declared, split_by, valid_split_by))
    return report


def _check_features(split, x):
    import numpy as np
    if x.ndim != 3:
        raise ValueError('%s: expected native features shaped [N,C,T], got %r' % (split, x.shape))
    if x.dtype != np.float32:
        raise ValueError('%s: native features are %s; refusing to cast them to float32' % (split, x.dtype))
    if not np.isfinite(x).all():
        raise ValueError('%s: non-finite native feature value' % split)


def _verify_readback(path, label_path, x, y, split):
    """Read the shard back and compare it to what is still in memory for this batch."""
    import numpy as np
    expected = {'x'} if label_path is not None else {'x', 'y'}
    with np.load(path, allow_pickle=False) as payload:
        if set(payload.files) != expected:
            raise ValueError('%s: shard keys %r violate the split contract' % (split, sorted(payload.files)))
        read_x, read_y = payload['x'], (None if label_path is not None else payload['y'])
    if label_path is not None:
        read_y = np.load(label_path, allow_pickle=False)
    for name, written, read in (('x', x, read_x), ('y', y, read_y)):
        if read.dtype != written.dtype or read.shape != written.shape or not np.array_equal(read, written):
            raise ValueError('%s: %s did not survive serialization to %s' % (split, name, path.name))
    return int(read_x.shape[0])


def export_split(split, dataset, out, plan, seen_waveforms, duplicates):
    """Write one split in native dataset order and return (manifest, lineage rows)."""
    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    segments = list(dataset.segments)
    records = list(dataset.triggers.to_dict('records'))
    if not len(segments) == len(records) == len(dataset):
        raise ValueError('%s: segments (%d), triggers (%d) and dataset (%d) disagree in length'
                         % (split, len(segments), len(records), len(dataset)))
    if not segments:
        raise ValueError('%s: the native split is empty' % split)
    target_dir = Path(out) / ('private' if split == 'test' else 'public') / split
    target_dir.mkdir(mode=0o700, parents=True)
    lineage_path = Path(out) / 'lineage' / (split + '.jsonl')
    # Fixed-order rewrap: the native weighted training sampler is never used for an export.
    loader = DataLoader(dataset, batch_size=SHARD_BATCH, num_workers=0, shuffle=False, drop_last=False,
                        collate_fn=dataset.collate_fn, generator=torch.Generator().manual_seed(SHARD_SEED))
    shards, rows, labels, cursor, shape, readback = [], [], [], 0, None, 0
    with lineage_path.open('w') as lineage_file:
        for index, batch in enumerate(loader):
            x = batch.data['neuro'].cpu().numpy()
            native_y = batch.data['target'].cpu().numpy()
            y = one_hot_to_int64(native_y, plan['num_classes'])
            _check_features(split, x)
            if len(y) != len(x):
                raise ValueError('%s: %d features against %d labels in shard %d' % (split, len(x), len(y), index))
            if shape is None:
                shape = tuple(int(v) for v in x.shape[1:])
            elif tuple(int(v) for v in x.shape[1:]) != shape:
                raise ValueError('%s: shard %d has shape %r, expected %r' % (split, index, x.shape[1:], shape))
            path = target_dir / ('%06d.npz' % index)
            label_path = target_dir / ('%06d-labels.npy' % index) if split == 'test' else None
            for candidate in (path, label_path):
                if candidate is not None and os.path.lexists(candidate):
                    raise ValueError('Refusing to overwrite an existing shard: %s' % candidate)
            if label_path is not None:
                np.savez(path, x=x)
                np.save(label_path, y, allow_pickle=False)
            else:
                np.savez(path, x=x, y=y)
            readback += _verify_readback(path, label_path, x, y, split)
            for offset in range(len(x)):
                order = cursor + offset
                entry = classification_lineage(order, segments[order], records[order],
                                               native_y[offset], plan,
                                               waveform_sha256(x[offset]), int(y[offset]))
                seen = seen_waveforms.get(entry['waveform_sha256'])
                if seen is None:
                    seen_waveforms[entry['waveform_sha256']] = (split, order)
                elif seen[0] != split:
                    duplicates.append({'sha256': entry['waveform_sha256'], 'first_split': seen[0],
                                       'first_index': seen[1], 'second_split': split, 'second_index': order})
                lineage_file.write(json.dumps(entry) + '\n')
                rows.append(entry)
                labels.append(int(y[offset]))
            cursor += len(x)
            shards.append({'file': path.name, 'samples': int(len(x)), 'shape': [int(v) for v in x.shape],
                           'sha256': digest(path)})
            if label_path is not None:
                shards[-1].update(labels_file=label_path.name, labels_sha256=digest(label_path))
    if cursor != len(dataset):
        raise ValueError('%s: wrote %d of %d native samples' % (split, cursor, len(dataset)))
    coverage = check_class_coverage(labels, plan['num_classes'], split)
    return {'samples': cursor, 'sample_shape': list(shape), 'shards': shards,
            'class_counts': [labels.count(cls) for cls in coverage], 'classes_present': coverage,
            'directory': str(target_dir.relative_to(out)),
            'labels_location': 'sibling -labels.npy files' if split == 'test' else 'y inside each shard',
            'lineage': {'file': str(lineage_path.relative_to(out)), 'rows': len(rows),
                        'sha256': digest(lineage_path)},
            'readback_rows_verified': readback}, rows


def _prepare_environment(out, data_root):
    """Every writable path the native stack uses is redirected under the new output."""
    dirs = {name: Path(out) / name for name in ('cache', 'home', 'xdg-config', 'xdg-cache', 'mne', 'native-runs')}
    for path in dirs.values():
        path.mkdir(mode=0o700, parents=True)
    runtime = {'USER': 'neuralbench-classification-builder', 'ENTITY_NAME': 'neuralbench-classification-builder',
               'PROJECT_NAME': 'neuralbench-classification-data', 'DATA_DIR': str(data_root),
               'CACHE_DIR': str(dirs['cache']), 'SAVE_DIR': str(dirs['native-runs']), 'WANDB_HOST': '',
               'N_CPUS': NATIVE_THREADS, 'CLUSTER': None, 'SLURM_PARTITION': '', 'SLURM_CONSTRAINT': ''}
    runtime_path = Path(out) / 'runtime.json'
    runtime_path.write_text(json.dumps(runtime, indent=2) + '\n')
    environment = {'NEURALBENCH_CONFIG': str(runtime_path), 'HOME': str(dirs['home']),
                   'XDG_CONFIG_HOME': str(dirs['xdg-config']), 'XDG_CACHE_HOME': str(dirs['xdg-cache']),
                   '_MNE_FAKE_HOME_DIR': str(dirs['mne']), 'MNE_DATA': str(dirs['cache']),
                   'CUDA_VISIBLE_DEVICES': '', 'WANDB_MODE': 'disabled',
                   'OMP_NUM_THREADS': str(NATIVE_THREADS), 'MKL_NUM_THREADS': str(NATIVE_THREADS),
                   'URLLIB3_NO_OVERRIDE': '1', 'PYTHONNOUSERSITE': '1',
                   'MOABB_DOWNLOAD_PROVIDER': 'upstream'}
    os.environ.update(environment)
    return {'runtime_json': runtime, 'environment': environment,
            'directories': {name: str(path) for name, path in dirs.items()}}


def _write_status(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2) + '\n')
    return payload


def _run(args, out, source, manifest_path, original, checkout, namespace, data_root):
    config, changes = normalize_config(original, data_root, out / 'cache')
    allowed = assert_only_allowed_changes(original, config, changes)
    source_block, _ = _locate(config, SOURCE_BLOCKS, 'source')
    source_summary = validate_source_block(source_block, args.expected_source_name)
    split_block, _ = _locate(config, SPLIT_BLOCKS, 'split')
    metrics, metrics_path = _locate(config, METRIC_BLOCKS, 'metrics', kind=list)
    num_classes = validate_metrics(metrics)
    target_block, _ = _locate(config, TARGET_BLOCKS, 'target')
    # Source, split and metrics are resolved by now, so the profile gate sees the exact
    # context it decides on. Any mismatch fails here, before a single sample is read.
    profile = target_profile(config, args.task_id, args.expected_source_name)
    event_field = profile['event_field']
    primary_metric = [m for m in metrics if isinstance(m, dict) and m.get('log_name') == METRIC_LOG_NAME][0]
    config_sha = sha256_json(config)
    _write_status(out / 'running.json',
                  {'status': 'running', 'pid': os.getpid(), 'task_id': args.task_id,
                   'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   'source_sha': PIN, 'source_head': checkout['head'], 'out': str(out),
                   'calibration_manifest': str(manifest_path),
                   'calibration_manifest_sha256': digest(manifest_path),
                   'normalized_config_sha256': config_sha, 'config_changes': changes,
                   'network_namespace': namespace})

    environment = _prepare_environment(out, data_root)
    for name in NATIVE_PACKAGES:
        sys.path.insert(0, str(source / (name + '-repo')))
    from neuralbench.config_manager import _ensure_initialized
    _ensure_initialized()
    import torch
    from neuralbench.main import Experiment
    origins = verify_module_origins(source)
    torch.set_num_threads(NATIVE_THREADS)

    experiment = Experiment(**copy.deepcopy(config))
    loaders = experiment.data.prepare()  # data only: no trainer, no model fit, ever
    if set(loaders) != set(SPLITS):
        raise ValueError('Expected the native splits %r, got %r' % (list(SPLITS), sorted(loaders)))
    target_object = experiment.data.target
    resolved_event_field = getattr(target_object, 'event_field', event_field)
    if resolved_event_field != event_field:
        raise ValueError('Resolved target event field %r differs from the configured %r'
                         % (resolved_event_field, event_field))
    label_to_ind = dict(target_object._label_to_ind)
    mapping = classification_mapping(label_to_ind, num_classes, profile['profile'])
    plan = {'num_classes': num_classes, 'label_to_ind': label_to_ind, 'event_field': event_field,
            'target_profile': profile['profile'],
            'allow_missing_session': split_block.get('split_by') in SESSION_OPTIONAL_SPLIT_BY}

    (out / 'lineage').mkdir(mode=0o700)
    splits, lineage, waveforms, duplicates = {}, {}, {}, []
    for split in SPLITS:
        splits[split], lineage[split] = export_split(split, loaders[split].dataset, out, plan,
                                                     waveforms, duplicates)
    if duplicates:
        raise ValueError('Identical native waveforms appear in more than one fold; they are neither '
                         'de-duplicated nor repartitioned here: ' + json.dumps(duplicates[:10]))
    shapes = {tuple(splits[split]['sample_shape']) for split in SPLITS}
    if len(shapes) != 1:
        raise ValueError('Splits disagree on the sample shape: %r' % sorted(shapes))
    input_shape = list(shapes.pop())
    subjects = sorted({row['subject'] for rows in lineage.values() for row in rows}, key=repr)
    if len(subjects) != args.expected_subjects:
        raise ValueError('Population differs: %d subjects versus the expected %d'
                         % (len(subjects), args.expected_subjects))
    groups = validate_split_groups(split_block, lineage, args.expected_source_name)
    rows_total = sum(len(rows) for rows in lineage.values())
    private_warnings = [
        'One-hot validity was checked on every shard, not assumed: an all-zero, multi-hot or soft '
        'target row fails the build instead of being argmaxed, imputed or dropped.']
    if profile['profile'] == SLEEP_STAGE_PROFILE:
        private_warnings.append(
            'The native sleep target sets allow_missing, which does not authorize inventing a label '
            'here: a stage outside the native mapping fails its sample and the partial build is kept.')
    if profile['profile'] == SEIZURE_PROFILE:
        private_warnings.append(
            'The native missing mapping index -1 occupies the last one-hot column. Sum targets '
            'are checked against overlapping Seizure events; multi-event/non-one-hot windows fail '
            'instead of being clipped, relabeled, dropped, or silently argmaxed.')

    report = {
        'status': 'classification-native-data-exported', 'task_id': args.task_id,
        'task_kind': 'classification', 'source_sha': PIN, 'source': dict(source_summary, checkout=checkout),
        'data_root': str(data_root), 'source_population_query': None,
        'calibration_manifest': {'path': str(manifest_path), 'sha256': digest(manifest_path)},
        'config': {'normalized_sha256': config_sha, 'changed_paths': allowed, 'changes': changes,
                   'metrics_location': metrics_path,
                   'resolved_full_config': json.loads(experiment.model_dump_json())},
        'protocol': {'split': copy.deepcopy(split_block), 'target': copy.deepcopy(target_block),
                     'primary_metric': copy.deepcopy(primary_metric), 'groups': groups,
                     'target_profile': profile['profile'],
                     'native_target_aggregation': profile['native_target_aggregation'],
                     'target_profile_checks': profile['checks']},
        'target_profile': profile['profile'],
        'native_target_aggregation': profile['native_target_aggregation'],
        'label_mapping': mapping, 'n_outputs': num_classes, 'input_shape': input_shape,
        'channels': input_shape[0], 'timepoints': input_shape[-1],
        'subjects': subjects, 'subject_count': len(subjects),
        'samples': {split: splits[split]['samples'] for split in SPLITS}, 'splits': splits,
        'resource_overrides': {'batch_size': SHARD_BATCH, 'num_workers': 0, 'pin_memory': False,
                               'persistent_workers': False, 'mne_cpus': 1, 'threads': NATIVE_THREADS,
                               'shard_generator_seed': SHARD_SEED, 'shuffle': False, 'drop_last': False},
        'environment': environment, 'network_namespace': namespace, 'native_packages': origins,
        'code_sha256': digest(Path(__file__).resolve()),
        'training_executed': False, 'model_fitted': False, 'runtime_registration': False, 'published': False,
        'private_artifacts': ['lineage/', 'private/'],
        'private_warnings': private_warnings,
        'evidence': {'shards_hashed': sum(len(splits[split]['shards']) for split in SPLITS),
                     'rows_read_back_and_compared': sum(splits[s]['readback_rows_verified'] for s in SPLITS),
                     'lineage_rows': rows_total,
                     ('labels_audited_against_native_window_events' if profile['profile'] == SEIZURE_PROFILE
                      else 'labels_audited_against_native_trigger'): rows_total},
        'limitations': [
            'Data export gate only: not evidence that the downstream agent pipeline is complete or accepted.',
            'Everything under lineage/ and private/ is controller-only and must not ship with a public task.',
            'Public task construction, registration and readiness are separate steps performed elsewhere.',
            'Counts and hashes are evidence about serialization and fold structure, not about acquisition '
            'or preprocessing confounds.']}
    if 'target_contract_module' in profile:
        report['target_contract_module'] = profile['target_contract_module']
    _write_status(out / 'complete.json', report)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', required=True, help='pinned native source checkout')
    parser.add_argument('--manifest', required=True, help='calibrated manifest: source_sha + resolved_config')
    parser.add_argument('--data', required=True, help='local root of the already-fetched source data')
    parser.add_argument('--out', required=True, help='new output directory, never an existing one')
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--expected-source-name', required=True)
    parser.add_argument('--expected-subjects', type=int, required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    out = Path(args.out)
    if os.path.lexists(out):
        raise ValueError('--out already exists; a partial or finished build is never resumed or '
                         'overwritten: %s' % out)
    source = Path(args.source).resolve()
    checkout = verify_source_checkout(source)
    manifest_path = Path(args.manifest)
    original = validate_calibration_manifest(json.loads(manifest_path.read_bytes().decode('utf-8')))
    data_root = Path(args.data).resolve()
    if not data_root.is_dir():
        raise ValueError('--data must be an existing directory: %s' % data_root)
    namespace = verify_network_namespace()
    out.mkdir(mode=0o700, parents=True)
    os.chmod(out, 0o700)
    try:
        report = _run(args, out, source, manifest_path, original, checkout, namespace, data_root)
    except BaseException as exc:
        # Leave every artifact as it is: a failed build is inspected, never retried in place.
        try:
            _write_status(out / 'failed.json',
                          {'status': 'failed', 'pid': os.getpid(), 'task_id': args.task_id,
                           'failed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                           'error': '%s: %s' % (type(exc).__name__, exc),
                           'note': 'Artifacts preserved; this output directory is never reused.'})
        except OSError:
            pass
        raise
    print(json.dumps({'status': report['status'], 'task_id': report['task_id'],
                      'subjects': report['subject_count'], 'n_outputs': report['n_outputs'],
                      'input_shape': report['input_shape'], 'samples': report['samples']}))
    return report


if __name__ == '__main__':
    main()
