"""Pinned CHB-MIT native sum-target contract; no data export or model execution.

Neuralset a8092dc's Segment.ns_events contains same-timeline events that overlap
the half-open segment window. Its LabelEncoder sums overlapping Seizure one-hot
vectors. The missing class has native mapping index -1 but occupies the final
one-hot column. This adapter audits those native outputs; it does not modify
native labels, invent background events, or infer state from an Eeg trigger.
"""

from __future__ import annotations

import math
import re
from typing import Any


SOURCE_SHA = "a8092dc10956038e445ff0e07f9c0c7e03a10d36"
TASK_ID = "seizure/default"
SOURCE_NAME = "Dan2023Bids"
PROFILE = "native-seizure-sum-missing-last-v1"
MISSING = "__missing__"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
NEURO_SCIENCE = {
    "name": "EegExtractor",
    "event_types": "Eeg",
    "aggregation": "single",
    "allow_missing": False,
    "frequency": 120.0,
    "offset": 0.0,
    "baseline": None,
    "picks": ["eeg"],
    "apply_proj": False,
    "filter": [0.1, 75.0],
    "apply_hilbert": False,
    "notch_filter": [50.0, 60.0],
    "drop_bads": False,
    "scaler": "RobustScaler",
    "scale_factor": None,
    "clamp": 20.0,
    "fill_non_finite": None,
    "bipolar_ref": None,
    "channel_order": "unique",
    "allow_maxshield": False,
}


def _block(root: dict, *keys: str) -> dict:
    node: Any = root
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"Missing native config block: {'.'.join(keys)}")
        node = node[key]
    if not isinstance(node, dict):
        raise ValueError(f"Native config block is not an object: {'.'.join(keys)}")
    return node


def _exact(value: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(value, bool):
        return value is expected
    if isinstance(expected, (int, float)):
        return isinstance(value, (int, float)) and value == expected
    return type(value) is type(expected) and value == expected


def _require(block: dict, path: str, expected: Any) -> None:
    key = path.rsplit(".", 1)[-1]
    if not _exact(block.get(key), expected):
        raise ValueError(f"CHB-MIT {path} must be {expected!r}, got {block.get(key)!r}")


def validate_profile(config: dict, *, task_id: str, source_name: str, source_sha: str) -> dict:
    """Fail closed unless the resolved config is the pinned full CHB-MIT study."""
    if (task_id, source_name, source_sha) != (TASK_ID, SOURCE_NAME, SOURCE_SHA):
        raise ValueError("Wrong task, source, or pinned native source SHA for CHB-MIT sum profile")
    data = _block(config, "data")
    study = _block(data, "study")
    steps = _block(study, "steps")
    if tuple(steps) != ("source", "split"):
        raise ValueError("CHB-MIT study steps must be source then split")
    source = _block(steps, "source")
    _require(source, "source.name", SOURCE_NAME)
    _require(source, "source.query", None)
    split = _block(steps, "split")
    for field, expected in (("name", "SklearnSplit"), ("split_by", "subject"),
                            ("valid_split_ratio", 0.2), ("test_split_ratio", 0.2),
                            ("valid_random_state", 33), ("test_random_state", 33),
                            ("stratify_by", "state")):
        _require(split, f"split.{field}", expected)
    target = _block(data, "target")
    for field, expected in (("name", "LabelEncoder"), ("event_types", "Seizure"),
                            ("event_field", "state"), ("aggregation", "sum"),
                            ("allow_missing", True), ("treat_missing_as_separate_class", True),
                            ("return_one_hot", True), ("frequency", 0),
                            ("predefined_mapping", None)):
        _require(target, f"target.{field}", expected)
    positions = _block(data, "channel_positions")
    _require(positions, "channel_positions.layout_or_montage_name", "standard_1005")
    sampler = _block(data, "sampler")
    _require(sampler, "sampler.name", "ClassificationSampler")
    neuro = _block(data, "neuro")
    science_fields = set(neuro) - {"infra", "mne_cpus"}
    if science_fields != set(NEURO_SCIENCE):
        raise ValueError("CHB-MIT neuro scientific field set changed")
    for field, expected in NEURO_SCIENCE.items():
        _require(neuro, f"neuro.{field}", expected)
    for field, expected in (("trigger_event_type", "Eeg"), ("start", 0),
                            ("duration", 5), ("stride", 5),
                            ("stride_drop_incomplete", True)):
        _require(data, f"data.{field}", expected)
    _require(config, "brain_model_output_size", 2)
    metrics = config.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("CHB-MIT config has no metric list")
    primary = [item for item in metrics if isinstance(item, dict) and item.get("log_name") == "bal_acc"]
    if len(primary) != 1 or primary[0].get("name") != "Accuracy":
        raise ValueError("CHB-MIT requires one native Accuracy/bal_acc metric")
    kwargs = primary[0].get("kwargs")
    if not isinstance(kwargs, dict):
        raise ValueError("CHB-MIT bal_acc metric has no kwargs")
    for field, expected in (("task", "multiclass"), ("average", "macro"), ("num_classes", 2)):
        _require(kwargs, f"bal_acc.{field}", expected)
    return {"profile": PROFILE, "source": SOURCE_NAME, "source_sha": SOURCE_SHA,
            "source_population_query": None, "expected_subjects": 23,
            "target_event_type": "Seizure", "target_event_field": "state",
            "native_target_aggregation": "sum", "trigger_event_type": "Eeg",
            "window_seconds": 5, "stride_seconds": 5, "num_classes": 2,
            "missing_native_index": -1, "missing_tensor_index": 1}


def label_mapping_records(label_to_ind: dict, num_classes: int) -> list[dict]:
    """Keep native -1 visible while binding the missing one-hot column to 1."""
    if type(num_classes) is not int or num_classes != 2:
        raise ValueError("CHB-MIT native target must have exactly two output columns")
    if (not isinstance(label_to_ind, dict) or set(label_to_ind) != {"seiz", MISSING} or
            type(label_to_ind["seiz"]) is not int or label_to_ind["seiz"] != 0 or
            type(label_to_ind[MISSING]) is not int or label_to_ind[MISSING] != -1):
        raise ValueError("CHB-MIT native mapping must be {'seiz': 0, '__missing__': -1}")
    return [{"native_label": "seiz", "type": "str", "native_index": 0, "index": 0},
            {"native_label": MISSING, "type": "str", "native_index": -1, "index": 1}]


def _plain(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        value = item()
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError(f"Non-scalar native event field: {type(value).__name__}")


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    value = _plain(value)
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Invalid {field}: {value!r}")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"Invalid {field}: {value!r}")
    return float(value)


def _event_type(event: Any) -> str:
    declared = getattr(event, "type", None)
    actual = type(event).__name__
    if declared == "Seizure" and actual != "Seizure":
        raise ValueError("Seizure event type does not match its native class")
    if declared == "Eeg" and actual != "Eeg":
        raise ValueError("Eeg trigger type does not match its native class")
    return declared


def _event_index(event: Any) -> Any:
    value = _plain(getattr(event, "_index", None))
    if value is None or type(value) not in (int, str):
        raise ValueError("Native event has no stable Index")
    return value


def _one_hot(native_target: Any) -> list[int]:
    try:
        values = list(native_target)
    except TypeError as error:
        raise ValueError("Native CHB-MIT target is not a vector") from error
    if len(values) != 2:
        raise ValueError("Native CHB-MIT target must have two one-hot columns")
    checked = []
    for value in values:
        value = _plain(value)
        if type(value) not in (int, float) or not math.isfinite(value) or value not in (0, 1):
            raise ValueError("Native CHB-MIT target has a non-binary one-hot value")
        checked.append(int(value))
    if sum(checked) != 1:
        raise ValueError("Native CHB-MIT target is zero-hot or multi-hot")
    return checked


def lineage_entry(order: int, segment: Any, record: dict, native_target: Any,
                  label_to_ind: dict, waveform_sha256: str) -> dict:
    """Audit one actual native target against overlapping Seizure events."""
    label_mapping_records(label_to_ind, 2)
    if type(order) is not int or order < 0:
        raise ValueError("Invalid native sample order")
    if not isinstance(record, dict):
        raise ValueError("Native trigger record must be a dict")
    if not isinstance(waveform_sha256, str) or not _SHA256.fullmatch(waveform_sha256):
        raise ValueError("Missing native waveform SHA-256")
    trigger = getattr(segment, "trigger", None)
    if trigger is None or _event_type(trigger) != "Eeg":
        raise ValueError("CHB-MIT window must have a native Eeg trigger")
    trigger_index = _event_index(trigger)
    fields = trigger.to_dict()
    if not isinstance(fields, dict):
        raise ValueError("Eeg trigger has no native fields")
    if "Index" in fields and fields["Index"] != trigger_index:
        raise ValueError("Eeg trigger fields disagree with native Index")
    if "Index" in record and record["Index"] != trigger_index:
        raise ValueError("Native trigger table disagrees with Eeg trigger Index")
    timeline = _plain(getattr(segment, "timeline", None))
    if type(timeline) is not str or not timeline or _plain(getattr(trigger, "timeline", None)) != timeline:
        raise ValueError("CHB-MIT window or Eeg trigger has no matching timeline")
    subject = _plain(fields.get("subject"))
    if type(subject) not in (str, int) or subject == "":
        raise ValueError("CHB-MIT Eeg trigger has no subject")
    start = _number(getattr(segment, "start", None), "window start")
    duration = _number(getattr(segment, "duration", None), "window duration", positive=True)
    if duration != 5.0:
        raise ValueError("CHB-MIT window duration differs from native 5 seconds")
    stop = start + duration
    trigger_start = _number(getattr(trigger, "start", None), "Eeg trigger start")
    trigger_duration = _number(getattr(trigger, "duration", None), "Eeg trigger duration", positive=True)
    if trigger_start > start or trigger_start + trigger_duration < stop:
        raise ValueError("CHB-MIT window exceeds its Eeg trigger")
    events = getattr(segment, "ns_events", None)
    if not isinstance(events, (list, tuple)):
        raise ValueError("Native segment has no overlapping event list")
    seizures = []
    eeg_trigger_seen = False
    for event in events:
        event_type = _event_type(event)
        if event_type == "Eeg" and _event_index(event) == trigger_index:
            eeg_trigger_seen = True
        if event_type != "Seizure":
            continue
        if _plain(getattr(event, "timeline", None)) != timeline:
            raise ValueError("Seizure event crosses the window timeline")
        event_start = _number(getattr(event, "start", None), "Seizure start")
        event_duration = _number(getattr(event, "duration", None), "Seizure duration", positive=True)
        if not (event_start < stop and event_start + event_duration > start):
            raise ValueError("Seizure event does not overlap the half-open window")
        getter = getattr(event, "_get_field_or_extra", None)
        if not callable(getter) or _plain(getter("state")) != "seiz":
            raise ValueError("CHB-MIT source contains an unexpected Seizure state")
        seizures.append({"event_index": _event_index(event), "state": "seiz",
                         "timeline": timeline, "start": event_start, "duration": event_duration})
    if not eeg_trigger_seen:
        raise ValueError("Native segment events omit the Eeg trigger")
    if len(seizures) > 1:
        raise ValueError("Native sum target has multiple overlapping Seizure events")
    observed = _one_hot(native_target)
    expected = [1, 0] if seizures else [0, 1]
    if observed != expected:
        raise ValueError(f"Native CHB-MIT target {observed} disagrees with overlapping Seizure events {expected}")
    label = 0 if seizures else 1
    return {"index": order, "subject": subject, "session": _plain(fields.get("session")),
            "timeline": timeline, "start": start, "duration": duration,
            "trigger_index": trigger_index, "event_field": "state",
            "event_value": "seiz" if seizures else MISSING, "label": label,
            "waveform_sha256": waveform_sha256,
            "target_aggregation": "sum", "native_one_hot": observed,
            "overlapping_seizure_events": seizures}
