"""Data-only export of one native sleep-onset regression study into auditable shards.

The two remaining sleep-onset cases are scalar regression, so they get their own
adapter instead of being coerced through the classification export: there is no
label mapping, no one-hot row and no class coverage here, and nothing in this
file turns a continuous target into a class. The generic export owns everything
that is not target-specific -- config normalization and its change receipt, the
pinned-source and namespace gates, the private environment, the module-origin
check, the fold-group audit and the status writers -- and is imported unchanged.

What is exported is the native target verbatim. Every sample is additionally
re-derived from the native trigger, ``clip(n2_onset - segment.stop, 0, cap_s)``
with ``segment.stop = segment.start + segment.duration``, and compared with what
the native pipeline emitted. A disagreement fails the build with both values
recorded; the native value is never replaced by the derived one, no sample is
dropped and no partial output is cleaned up.

This never trains, never fits a model, never launches an agent and never
registers or publishes a task. A completed export is evidence about
serialization, fold structure and the target definition, and about nothing else.

The caller owns isolation, exactly as for the classification export: raw data
stays wherever --data points, the source checkout must sit on the pinned commit
with a clean tracked tree, and the process must already sit in its own network
namespace, whose origin the trusted launcher captures first:

    origin=$(readlink /proc/self/ns/net)
    NEURALBENCH_PREP_ORIGIN_NETNS="$origin" unshare --user --map-current-user --net \
        python tasks/eeg/_preparation/export_sleep_onset_native.py ...
"""
from __future__ import annotations
import argparse
import copy
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path

import export_classification_native as generic

CONTRACT_PATH = Path(__file__).resolve().parent / 'sleep_special_contract.py'

TASK_KIND = 'regression'
STATUS = 'sleep-onset-native-data-exported'
# (task id -> source, declared population). Both halves are checked against the CLI;
# neither is ever inferred from the other, and no third pair is reachable.
TASK_SOURCES = {'sleep_onset/default': ('Kemp2000Analysis', 78),
                'sleep_onset/alvarez2022haaglanden': ('Alvarez2022Haaglanden', 151)}

STEP_ORDER = ('source', 'annotate_sleep_onset', 'split')
ANNOTATE_STEP = 'annotate_sleep_onset'
ANNOTATE_NAME = 'AddSleepOnsetTargets'
ANNOTATE_FIELDS = (('max_pre_n2_s', 1200.0), ('n2_stage', 'N2'))
SPLIT_NAME = 'SklearnSplit'
SPLIT_BY = 'subject'
SPLIT_FIELDS = (('valid_split_ratio', 0.2), ('test_split_ratio', 0.2),
                ('valid_random_state', 33), ('test_random_state', 33))
TARGET_NAME = 'SleepOnsetTargetExtractor'
TARGET_EVENT_TYPE = 'SleepOnsetMarker'
TARGET_AGGREGATION = 'trigger'
ONSET_FIELD = 'n2_onset'
CAP_S = 600.0
WINDOW_DURATION = 5.0
WINDOW_START = 0.0
N_OUTPUTS = 1
SAMPLER_NAME = 'RegressionBinSampler'
BIN_EDGES = [0.0, 40.0, 90.0, 300.0, 600.0]
METRIC_LOG_NAME = 'bmae'
METRIC_NAME = 'BinnedMAE'
# Both sides of the comparison are the same clip() over the same two float seconds,
# rounded to float32, so agreement is expected to be exact. 1e-5 s is an absolute
# allowance, not a relative one: above ~160 s a single float32 ULP already exceeds it,
# so a genuine 1-ULP difference fails the build instead of passing quietly. That is
# the intended direction -- this gate reports a disagreement, it never absorbs one.
TARGET_ATOL = 1e-5
FREQUENCY_KEYS = ('frequency', 'sample_freq', 'sfreq')
TARGET_DEFINITION = ('clip(%s.%s - (segment.start + segment.duration), 0, %s)'
                     % (TARGET_EVENT_TYPE, ONSET_FIELD, CAP_S))


def contract():
    """The stdlib bin/metric rules, loaded by path so no package import is required."""
    name = 'full_runtime._sleep_special_contract'
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, CONTRACT_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def validate_pair(task_id, source_name):
    """Bind the run to one pinned (task, source) pair; neither half implies the other."""
    pair = TASK_SOURCES.get(task_id)
    if pair is None:
        raise ValueError('Task %r is not one of the sleep-onset regression cases %r; this adapter '
                         'exports nothing else' % (task_id, sorted(TASK_SOURCES)))
    expected_source, declared = pair
    if source_name != expected_source:
        raise ValueError('Task %r is pinned to source %r, not %r' % (task_id, expected_source, source_name))
    return {'task_id': task_id, 'source': expected_source, 'declared_subjects': declared,
            'task_kind': TASK_KIND}


def validate_case(task_id, source_name, expected_subjects):
    """The pinned pair plus the declared population the caller must ask for exactly."""
    case = validate_pair(task_id, source_name)
    if expected_subjects != case['declared_subjects']:
        raise ValueError('--expected-subjects %r is not the declared %s population of %d subjects; the '
                         'gate is not lowered to whatever the export happens to produce'
                         % (expected_subjects, case['source'], case['declared_subjects']))
    return case


def _numbers(value):
    """A list of plain finite numbers, or None when this is not a numeric sequence."""
    if not isinstance(value, (list, tuple)) or not value:
        return None
    values = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            return None
        values.append(float(item))
    return values


def validate_metric(metrics):
    """Only a BinnedMAE/bmae primary metric over the pinned edges scores this export."""
    entries = [metric for metric in metrics if isinstance(metric, dict)]
    misused = [metric for metric in entries
               if metric.get('log_name') == generic.METRIC_LOG_NAME or metric.get('name') == generic.METRIC_NAME]
    if misused:
        raise ValueError('sleep-onset is a regression export: a %s/%s classification metric must not score '
                         'it (%r)' % (generic.METRIC_LOG_NAME, generic.METRIC_NAME, misused))
    primary = [metric for metric in entries if metric.get('log_name') == METRIC_LOG_NAME]
    if len(primary) != 1:
        raise ValueError('Expected exactly one %r metric, found %d' % (METRIC_LOG_NAME, len(primary)))
    metric = primary[0]
    if metric.get('name') != METRIC_NAME:
        raise ValueError('%s must be computed by %s, not %r' % (METRIC_LOG_NAME, METRIC_NAME, metric.get('name')))
    boundaries = _numbers(metric.get('bin_boundaries'))
    if boundaries != BIN_EDGES:
        raise ValueError('%s bin_boundaries must be %r, not %r'
                         % (METRIC_LOG_NAME, BIN_EDGES, metric.get('bin_boundaries')))
    contract().check_bin_edges(boundaries)
    return metric, boundaries


def onset_profile(config, task_id, source_name):
    """Receipt for the resolved sleep-onset recipe, or a failure naming the clause.

    Every clause below is read from the config as resolved; nothing is written back,
    defaulted or relaxed, so a study that breaks one of them fails here rather than
    being edited into the profile.
    """
    case = validate_pair(task_id, source_name)
    source, _ = generic._locate(config, generic.SOURCE_BLOCKS, 'source')
    if source.get('name') != case['source']:
        raise ValueError('Sleep-onset config declares source %r, not the pinned %r'
                         % (source.get('name'), case['source']))
    if source.get('query') is not None:
        raise ValueError('Sleep-onset source query must be null: the whole declared population is '
                         'exported, never a subset (%r)' % (source.get('query'),))
    steps, steps_path = generic._locate(config, generic.STEPS_BLOCKS, 'steps')
    order = tuple(key for key in steps if key in STEP_ORDER)
    if order != STEP_ORDER:
        raise ValueError('Sleep-onset pipeline is %r, not %r' % (list(order), list(STEP_ORDER)))
    annotate = steps[ANNOTATE_STEP]
    if not isinstance(annotate, dict) or generic._declared_name(annotate) != ANNOTATE_NAME:
        raise ValueError('Sleep-onset annotation step must be an %s block, not %r' % (ANNOTATE_NAME, annotate))
    for field, expected in ANNOTATE_FIELDS:
        if not generic._exact(annotate.get(field), expected):
            raise ValueError('%s.%s must be %r, not %r' % (ANNOTATE_NAME, field, expected, annotate.get(field)))
    split, _ = generic._locate(config, generic.SPLIT_BLOCKS, 'split')
    if generic._declared_name(split) != SPLIT_NAME or split.get('split_by') != SPLIT_BY:
        raise ValueError('Sleep-onset split must be %s split_by %r, not %r split_by %r'
                         % (SPLIT_NAME, SPLIT_BY, generic._declared_name(split), split.get('split_by')))
    for field, expected in SPLIT_FIELDS:
        if not generic._exact(split.get(field), expected):
            raise ValueError('%s.%s must be %r, not %r' % (SPLIT_NAME, field, expected, split.get(field)))
    target, target_path = generic._locate(config, generic.TARGET_BLOCKS, 'target')
    if generic._declared_name(target) != TARGET_NAME:
        raise ValueError('Sleep-onset target must be a %s, not %r; no classification encoder is accepted '
                         'here' % (TARGET_NAME, generic._declared_name(target)))
    if generic._event_types(target.get('event_types')) != (TARGET_EVENT_TYPE,):
        raise ValueError('Sleep-onset target event_types must be exactly %r, not %r'
                         % (TARGET_EVENT_TYPE, target.get('event_types')))
    if target.get('aggregation') != TARGET_AGGREGATION:
        raise ValueError('Sleep-onset target aggregation must be %r, not %r'
                         % (TARGET_AGGREGATION, target.get('aggregation')))
    if not generic._exact(target.get('cap_s'), CAP_S):
        raise ValueError('Sleep-onset target cap_s must be %r, not %r; the cap is part of the target '
                         'definition and is never widened' % (CAP_S, target.get('cap_s')))
    event_type = generic._setting(config, 'trigger_event_type', 'trigger event type')
    if event_type != TARGET_EVENT_TYPE:
        raise ValueError('Sleep-onset trigger event type must be %r, not %r' % (TARGET_EVENT_TYPE, event_type))
    window = {key: generic._setting(config, key, key) for key in ('duration', 'start', 'stride')}
    for key, expected in (('duration', WINDOW_DURATION), ('start', WINDOW_START)):
        if not generic._exact(window[key], expected):
            raise ValueError('Sleep-onset window %s must be %r, not %r' % (key, expected, window[key]))
    outputs = config.get('brain_model_output_size')
    if not generic._exact(outputs, N_OUTPUTS):
        raise ValueError('Sleep-onset is a scalar regression: brain_model_output_size must be %r, not %r'
                         % (N_OUTPUTS, outputs))
    metrics, metrics_path = generic._locate(config, generic.METRIC_BLOCKS, 'metrics', kind=list)
    metric, boundaries = validate_metric(metrics)
    sampler, _ = generic._locate(config, (('data', 'sampler'),), 'sampler')
    if generic._declared_name(sampler) != SAMPLER_NAME or _numbers(sampler.get('bin_edges')) != boundaries:
        raise ValueError('Sleep-onset sampler must be %s over the metric edges %r, not %r over %r; the '
                         'primary score and the training sampler never bin differently'
                         % (SAMPLER_NAME, boundaries, generic._declared_name(sampler), sampler.get('bin_edges')))
    return {'task_id': task_id, 'source': case['source'], 'task_kind': TASK_KIND,
            'declared_subjects': case['declared_subjects'], 'source_population_query': None,
            'pipeline': list(order), 'steps_location': steps_path, 'target_location': target_path,
            'metrics_location': metrics_path,
            'annotation': {'name': ANNOTATE_NAME, **{field: annotate.get(field) for field, _ in ANNOTATE_FIELDS}},
            'split': {'name': SPLIT_NAME, 'split_by': SPLIT_BY,
                      **{field: split.get(field) for field, _ in SPLIT_FIELDS}},
            'target': {'name': TARGET_NAME, 'event_types': TARGET_EVENT_TYPE,
                       'aggregation': TARGET_AGGREGATION, 'cap_s': CAP_S,
                       'definition': TARGET_DEFINITION},
            'trigger_event_type': event_type, 'window': window, 'n_outputs': N_OUTPUTS,
            'metric': {'log_name': METRIC_LOG_NAME, 'name': METRIC_NAME, 'bin_edges': boundaries},
            'sampler': {'name': SAMPLER_NAME, 'bin_edges': boundaries,
                        'used_for_export': False,
                        'note': 'the native weighted sampler stays in the recipe but never orders '
                                'an export; shards are written in fixed native dataset order'},
            'primary_metric': copy.deepcopy(metric)}


def resolved_frequency(config):
    """Sampling frequency of the resolved extractor, read rather than assumed."""
    neuro = config.get('data', {}).get('neuro') if isinstance(config.get('data'), dict) else None
    if not isinstance(neuro, dict):
        raise ValueError('Config exposes no data.neuro block to read the frequency from')
    for key in FREQUENCY_KEYS:
        value = neuro.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not math.isfinite(value) or value <= 0:
            raise ValueError('data.neuro.%s is %r, which is not a usable frequency' % (key, value))
        return {'frequency': float(value), 'field': 'data.neuro.' + key}
    raise ValueError('data.neuro declares no frequency at any of %r' % (FREQUENCY_KEYS,))


def derive_target(order, start, duration, n2_onset, cap_s=CAP_S):
    """The native onset target for one window: clip(n2_onset - segment.stop, 0, cap_s).

    The window END is the reference point, not its start: the label is the remaining
    distance from the end of the observed window to the N2 onset.
    """
    generic._assert_window(order, start, duration)
    if isinstance(n2_onset, bool) or not isinstance(n2_onset, (int, float)) or not math.isfinite(n2_onset):
        raise ValueError('Sample %r carries a non-numeric or non-finite %s (%r)'
                         % (order, ONSET_FIELD, n2_onset))
    if isinstance(cap_s, bool) or not isinstance(cap_s, (int, float)) or not math.isfinite(cap_s) or cap_s <= 0:
        raise ValueError('cap_s must be a positive finite number, not %r' % (cap_s,))
    stop = float(start) + float(duration)
    gap = float(n2_onset) - stop
    return {'segment_stop': stop, 'raw_gap': gap, 'cap_s': float(cap_s),
            'derived_target': min(max(gap, 0.0), float(cap_s)),
            'clipped_at': 'floor' if gap < 0.0 else ('cap' if gap > cap_s else None)}


def scalar_targets(split, y):
    """Native regression targets as float32 [N,1]; only a lossless squeeze is allowed."""
    import numpy as np
    array = np.asarray(y)
    if array.dtype != np.float32:
        raise ValueError('%s: native targets are %s; a regression export never casts them' % (split, array.dtype))
    if array.ndim == 1:
        shaped = array.reshape(int(array.shape[0]), 1)
    elif array.ndim == 2 and array.shape[1] == 1:
        shaped = array
    else:
        raise ValueError('%s: expected native scalar targets shaped [N,1] or [N], got %r; a wider target is '
                         'a classification target and is never reduced to a scalar here' % (split, array.shape))
    if not np.isfinite(shaped).all():
        raise ValueError('%s: non-finite native target value' % split)
    return np.ascontiguousarray(shaped)


def onset_lineage_entry(order, segment, record, allow_missing_session, waveform, native_target,
                        cap_s=CAP_S, bin_edges=BIN_EDGES, tolerance=TARGET_ATOL):
    """One private lineage row, audited against the native trigger and not against y alone."""
    rules = contract()
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
    start, duration = generic._plain(segment.start), generic._plain(segment.duration)
    onset = generic._plain(trigger._get_field_or_extra(ONSET_FIELD))
    derived = derive_target(order, start, duration, onset, cap_s)
    emitted = float(native_target)
    if not math.isfinite(emitted):
        raise ValueError('Sample %d carries a non-finite native target (%r)' % (order, native_target))
    expected = rules.to_float32(derived['derived_target'])
    delta = abs(expected - emitted)
    if delta > tolerance:
        raise ValueError('Sample %d: the native target %.9g disagrees with %s = %.9g (delta %.9g > %g). The '
                         'native value is kept as written and the export stops here; it is never replaced '
                         'by the derived one, and no sample is dropped to make the two agree.'
                         % (order, emitted, TARGET_DEFINITION, expected, delta, tolerance))
    return {'index': order, 'subject': generic._plain(subject), 'session': generic._plain(session),
            'timeline': generic._plain(timeline), 'start': start, 'duration': duration,
            'segment_stop': derived['segment_stop'], 'trigger_index': generic._plain(native_index),
            'event_field': ONSET_FIELD, 'n2_onset': onset, 'raw_gap': derived['raw_gap'],
            'clipped_at': derived['clipped_at'], 'cap_s': derived['cap_s'],
            'derived_target': derived['derived_target'], 'derived_target_float32': expected,
            'native_target': emitted, 'target_delta': delta,
            'expected_bin_index': rules.assign_bin(derived['derived_target'], bin_edges),
            'native_bin_index': rules.assign_bin(emitted, bin_edges),
            'waveform_sha256': waveform}


def resolved_target_receipt(target_object, cap_s=CAP_S):
    """The target the native stack actually built must be the one the config declared."""
    declared, class_name = getattr(target_object, 'name', None), type(target_object).__name__
    if TARGET_NAME not in (declared, class_name) and not class_name.startswith(TARGET_NAME):
        raise ValueError('Resolved native target is %r (declared %r), not a %s'
                         % (class_name, declared, TARGET_NAME))
    resolved_cap = getattr(target_object, 'cap_s', None)
    if isinstance(resolved_cap, bool) or not isinstance(resolved_cap, (int, float)) \
            or float(resolved_cap) != float(cap_s):
        raise ValueError('Resolved native target cap_s is %r, not the configured %r' % (resolved_cap, cap_s))
    return {'class': class_name, 'declared_name': declared, 'cap_s': float(resolved_cap),
            'aggregation': generic._plain(getattr(target_object, 'aggregation', None))}


def export_split(split, dataset, out, plan, seen_waveforms, duplicates):
    """Write one split in native dataset order and return (manifest, lineage rows)."""
    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    rules = contract()
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
    # Fixed-order rewrap: the native RegressionBinSampler is never used for an export.
    loader = DataLoader(dataset, batch_size=generic.SHARD_BATCH, num_workers=0, shuffle=False, drop_last=False,
                        collate_fn=dataset.collate_fn,
                        generator=torch.Generator().manual_seed(generic.SHARD_SEED))
    shards, rows, values, cursor, shape, readback = [], [], [], 0, None, 0
    with lineage_path.open('w') as lineage_file:
        for index, batch in enumerate(loader):
            x = batch.data['neuro'].cpu().numpy()
            y = scalar_targets(split, batch.data['target'].cpu().numpy())
            generic._check_features(split, x)
            if len(y) != len(x):
                raise ValueError('%s: %d features against %d targets in shard %d' % (split, len(x), len(y), index))
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
                np.savez(path, x=x)  # no public y for the test split, ever
                np.save(label_path, y, allow_pickle=False)
            else:
                np.savez(path, x=x, y=y)
            readback += generic._verify_readback(path, label_path, x, y, split)
            for offset in range(len(x)):
                order = cursor + offset
                entry = onset_lineage_entry(order, segments[order], records[order],
                                            plan['allow_missing_session'], generic.waveform_sha256(x[offset]),
                                            float(y[offset][0]), plan['cap_s'], plan['bin_edges'])
                seen = seen_waveforms.get(entry['waveform_sha256'])
                if seen is None:
                    seen_waveforms[entry['waveform_sha256']] = (split, order)
                elif seen[0] != split:
                    duplicates.append({'sha256': entry['waveform_sha256'], 'first_split': seen[0],
                                       'first_index': seen[1], 'second_split': split, 'second_index': order})
                lineage_file.write(json.dumps(entry) + '\n')
                rows.append(entry)
                values.append(float(y[offset][0]))
            cursor += len(x)
            shards.append({'file': path.name, 'samples': int(len(x)), 'shape': [int(v) for v in x.shape],
                           'sha256': generic.digest(path)})
            if label_path is not None:
                shards[-1].update(labels_file=label_path.name, labels_sha256=generic.digest(label_path))
    if cursor != len(dataset):
        raise ValueError('%s: wrote %d of %d native samples' % (split, cursor, len(dataset)))
    counts = rules.bin_counts(values, plan['bin_edges'])
    return {'samples': cursor, 'sample_shape': list(shape), 'shards': shards,
            'directory': str(target_dir.relative_to(out)),
            'targets_location': 'sibling -labels.npy files' if split == 'test' else 'y inside each shard',
            'target_summary': {'bin_edges': counts['bin_edges'], 'bin_counts': counts['counts'],
                               'empty_bins': counts['empty_bins'], 'populated_bins': counts['populated_bins'],
                               'out_of_range_targets': counts['out_of_range'],
                               'min': min(values), 'max': max(values),
                               'at_zero_count': sum(1 for value in values if value == 0.0),
                               'at_cap_count': sum(1 for value in values if value == plan['cap_s']),
                               'note': 'bins are an independent diagnostic computed from the exported '
                                       'native targets; empty bins are reported, never filled, and no '
                                       'target is resampled, clipped or synthesised to populate one'},
            'lineage': {'file': str(lineage_path.relative_to(out)), 'rows': len(rows),
                        'sha256': generic.digest(lineage_path)},
            'readback_rows_verified': readback}, rows


def _run(args, out, source, manifest_path, original, checkout, namespace, data_root):
    config, changes = generic.normalize_config(original, data_root, out / 'cache')
    allowed = generic.assert_only_allowed_changes(original, config, changes)
    source_block, _ = generic._locate(config, generic.SOURCE_BLOCKS, 'source')
    source_summary = generic.validate_source_block(source_block, args.expected_source_name)
    split_block, _ = generic._locate(config, generic.SPLIT_BLOCKS, 'split')
    target_block, _ = generic._locate(config, generic.TARGET_BLOCKS, 'target')
    case = validate_case(args.task_id, args.expected_source_name, args.expected_subjects)
    # The whole native profile is resolved before a single sample is read, so a recipe
    # that is not this study fails while the output still holds nothing but status files.
    profile = onset_profile(config, args.task_id, args.expected_source_name)
    frequency = resolved_frequency(config)
    config_sha = generic.sha256_json(config)
    generic._write_status(out / 'running.json',
                          {'status': 'running', 'pid': os.getpid(), 'task_id': args.task_id,
                           'task_kind': TASK_KIND,
                           'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                           'source_sha': generic.PIN, 'source_head': checkout['head'], 'out': str(out),
                           'calibration_manifest': str(manifest_path),
                           'calibration_manifest_sha256': generic.digest(manifest_path),
                           'normalized_config_sha256': config_sha, 'config_changes': changes,
                           'network_namespace': namespace})

    environment = generic._prepare_environment(out, data_root)
    for name in generic.NATIVE_PACKAGES:
        sys.path.insert(0, str(source / (name + '-repo')))
    from neuralbench.config_manager import _ensure_initialized
    _ensure_initialized()
    import torch
    # All four native packages are imported explicitly, because the origin check below
    # only proves an origin for a package that is actually loaded.
    import neuralbench, neuralset, neuralfetch, neuraltrain  # noqa: F401
    from neuralbench.main import Experiment
    origins = generic.verify_module_origins(source)
    torch.set_num_threads(generic.NATIVE_THREADS)

    experiment = Experiment(**copy.deepcopy(config))
    loaders = experiment.data.prepare()  # data only: no trainer, no model, no fit, ever
    if set(loaders) != set(generic.SPLITS):
        raise ValueError('Expected the native splits %r, got %r' % (list(generic.SPLITS), sorted(loaders)))
    target_receipt = resolved_target_receipt(experiment.data.target, CAP_S)
    plan = {'cap_s': CAP_S, 'bin_edges': profile['metric']['bin_edges'],
            'allow_missing_session': split_block.get('split_by') in generic.SESSION_OPTIONAL_SPLIT_BY}

    (out / 'lineage').mkdir(mode=0o700)
    splits, lineage, waveforms, duplicates = {}, {}, {}, []
    for split in generic.SPLITS:
        splits[split], lineage[split] = export_split(split, loaders[split].dataset, out, plan,
                                                     waveforms, duplicates)
    if duplicates:
        raise ValueError('Identical native waveforms appear in more than one fold; they are neither '
                         'de-duplicated nor repartitioned here: ' + json.dumps(duplicates[:10]))
    shapes = {tuple(splits[split]['sample_shape']) for split in generic.SPLITS}
    if len(shapes) != 1:
        raise ValueError('Splits disagree on the sample shape: %r' % sorted(shapes))
    input_shape = list(shapes.pop())
    subjects = sorted({row['subject'] for rows in lineage.values() for row in rows}, key=repr)
    if len(subjects) != args.expected_subjects:
        raise ValueError('Population differs: %d subjects against the declared %d for %s. Missing subjects '
                         'are a reportable native outcome; nothing is deleted, relabelled or re-split to '
                         'reach the declared count.' % (len(subjects), args.expected_subjects, case['source']))
    groups = generic.validate_split_groups(split_block, lineage, args.expected_source_name)
    rows_total = sum(len(rows) for rows in lineage.values())
    bins = {split: splits[split]['target_summary']['bin_counts'] for split in generic.SPLITS}

    report = {
        'status': STATUS, 'task_id': args.task_id, 'task_kind': TASK_KIND,
        'source_sha': generic.PIN, 'source': dict(source_summary, checkout=checkout),
        'data_root': str(data_root), 'source_population_query': None,
        'calibration_manifest': {'path': str(manifest_path), 'sha256': generic.digest(manifest_path)},
        'config': {'normalized_sha256': config_sha, 'changed_paths': allowed, 'changes': changes,
                   'resolved_full_config': json.loads(experiment.model_dump_json())},
        'protocol': {'profile': profile, 'split': copy.deepcopy(split_block),
                     'target': copy.deepcopy(target_block), 'resolved_target': target_receipt,
                     'primary_metric': profile['primary_metric'], 'groups': groups,
                     'target_definition': TARGET_DEFINITION,
                     'target_reference_point': 'segment end (start + duration), not the segment start',
                     'target_comparison_tolerance': TARGET_ATOL},
        'target_definition': TARGET_DEFINITION,
        'metric': {'log_name': METRIC_LOG_NAME, 'name': METRIC_NAME,
                   'bin_edges': profile['metric']['bin_edges']},
        'n_outputs': N_OUTPUTS, 'input_shape': input_shape,
        'channels': input_shape[0], 'timepoints': input_shape[-1],
        'frequency': frequency['frequency'], 'frequency_field': frequency['field'],
        'timepoints_expected_from_frequency': frequency['frequency'] * profile['window']['duration'],
        'window': profile['window'],
        'subjects': subjects, 'subject_count': len(subjects), 'declared_subjects': case['declared_subjects'],
        'samples': {split: splits[split]['samples'] for split in generic.SPLITS}, 'splits': splits,
        'bin_counts': bins,
        'resource_overrides': {'batch_size': generic.SHARD_BATCH, 'num_workers': 0, 'pin_memory': False,
                               'persistent_workers': False, 'mne_cpus': 1,
                               'threads': generic.NATIVE_THREADS, 'shard_generator_seed': generic.SHARD_SEED,
                               'shuffle': False, 'drop_last': False,
                               'native_sampler_used': False},
        'environment': environment, 'network_namespace': namespace, 'native_packages': origins,
        'code_sha256': generic.digest(Path(__file__).resolve()),
        'generic_export_sha256': generic.digest(Path(generic.__file__).resolve()),
        'contract_module': {'path': str(CONTRACT_PATH), 'sha256': generic.digest(CONTRACT_PATH),
                            'used_for': 'independent bin assignment and float32 rounding in the audit only; '
                                        'it never produces or edits an exported target'},
        'training_executed': False, 'model_fitted': False, 'runtime_registration': False, 'published': False,
        'agent_evaluated': False, 'runtime_accepted': False,
        'private_artifacts': ['lineage/', 'private/'],
        'private_warnings': [
            'Every exported target is the native value verbatim. The re-derivation from '
            'n2_onset is an audit: a disagreement fails the build with both values recorded, '
            'and no target is ever rewritten to the derived value.',
            'private/test holds features only; the test targets live in sibling -labels.npy '
            'files and must never ship with a public task.'],
        'evidence': {'shards_hashed': sum(len(splits[s]['shards']) for s in generic.SPLITS),
                     'rows_read_back_and_compared': sum(splits[s]['readback_rows_verified']
                                                        for s in generic.SPLITS),
                     'lineage_rows': rows_total,
                     'targets_rederived_from_native_trigger': rows_total},
        'limitations': [
            'Data export gate only: not evidence that the downstream agent pipeline is complete, '
            'accepted or passed, and not a published task.',
            'Everything under lineage/ and private/ is controller-only.',
            'Public task construction, registration and readiness are separate steps performed elsewhere.',
            'Bin counts are diagnostics over the exported targets, not a claim about the native '
            'sampler weights or about BinnedMAE on any prediction.',
            'Native preprocessing is zero-phase and whole-recording, so temporal causality of the '
            'features is NOT validated by this export.']}
    generic._write_status(out / 'complete.json', report)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', required=True, help='pinned native source checkout')
    parser.add_argument('--manifest', required=True, help='calibrated manifest: source_sha + resolved_config')
    parser.add_argument('--data', required=True, help='local root of the already-fetched source data')
    parser.add_argument('--out', required=True, help='new output directory, never an existing one')
    parser.add_argument('--task-id', required=True, help='one of ' + ', '.join(sorted(TASK_SOURCES)))
    parser.add_argument('--expected-source-name', required=True)
    parser.add_argument('--expected-subjects', type=int, required=True,
                        help='the declared population of the pinned pair')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    out = Path(args.out)
    if os.path.lexists(out):
        raise ValueError('--out already exists; a partial or finished build is never resumed or '
                         'overwritten: %s' % out)
    source = Path(args.source).resolve()
    checkout = generic.verify_source_checkout(source)
    manifest_path = Path(args.manifest)
    original = generic.validate_calibration_manifest(json.loads(manifest_path.read_bytes().decode('utf-8')))
    data_root = Path(args.data).resolve()
    if not data_root.is_dir():
        raise ValueError('--data must be an existing directory: %s' % data_root)
    namespace = generic.verify_network_namespace()
    # Only now, with the metadata, source and namespace all checked, does anything exist on disk.
    out.mkdir(mode=0o700, parents=True)
    os.chmod(out, 0o700)
    try:
        report = _run(args, out, source, manifest_path, original, checkout, namespace, data_root)
    except BaseException as exc:
        # Leave every artifact as it is: a failed build is inspected, never retried in place.
        try:
            generic._write_status(out / 'failed.json',
                                  {'status': 'failed', 'pid': os.getpid(), 'task_id': args.task_id,
                                   'task_kind': TASK_KIND,
                                   'failed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                   'error': '%s: %s' % (type(exc).__name__, exc),
                                   'note': 'Artifacts preserved exactly as written, including any partial '
                                           'shard set and its native targets. This output directory is '
                                           'never reused, cleaned or retried in place.'})
        except OSError:
            pass
        raise
    print(json.dumps({'status': report['status'], 'task_id': report['task_id'],
                      'task_kind': report['task_kind'], 'subjects': report['subject_count'],
                      'n_outputs': report['n_outputs'], 'input_shape': report['input_shape'],
                      'samples': report['samples']}))
    return report


if __name__ == '__main__':
    main()
