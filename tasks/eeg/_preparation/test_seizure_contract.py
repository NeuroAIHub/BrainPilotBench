"""Small, wave-free checks of the pinned CHB-MIT native sum-label contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import seizure_contract as contract
import export_classification_native as exporter
from test_contract import fixture
from verify_export import verify_fields


class Eeg:
    type = "Eeg"

    def __init__(self, index: int = 7, *, timeline: str = "t1", start: float = 0,
                 duration: float = 20, subject: str = "01") -> None:
        self._index = index
        self.timeline = timeline
        self.start = start
        self.duration = duration
        self.subject = subject

    def to_dict(self) -> dict:
        return {"type": self.type, "subject": self.subject,
                "session": "01", "timeline": self.timeline, "start": self.start,
                "duration": self.duration}


class Seizure:
    type = "Seizure"

    def __init__(self, index: int, *, timeline: str = "t1", start: float = 2,
                 duration: float = 2, state: str = "seiz") -> None:
        self._index = index
        self.timeline = timeline
        self.start = start
        self.duration = duration
        self.state = state

    def _get_field_or_extra(self, field: str) -> str:
        if field != "state":
            raise KeyError(field)
        return self.state


class PretendSeizure(Seizure):
    pass


class Segment:
    def __init__(self, trigger: Eeg, events: list, *, start: float = 0,
                 duration: float = 5, timeline: str = "t1") -> None:
        self.trigger = trigger
        self.ns_events = events
        self.start = start
        self.duration = duration
        self.timeline = timeline


def full_config() -> dict:
    return {
        "data": {
            "study": {"steps": {
                "source": {"name": "Dan2023Bids", "query": None},
                "split": {"name": "SklearnSplit", "split_by": "subject",
                          "valid_split_ratio": 0.2, "test_split_ratio": 0.2,
                          "valid_random_state": 33, "test_random_state": 33,
                          "stratify_by": "state"}}},
            "target": {"name": "LabelEncoder", "event_types": "Seizure",
                       "event_field": "state", "aggregation": "sum",
                       "allow_missing": True, "treat_missing_as_separate_class": True,
                       "return_one_hot": True, "frequency": 0.0,
                       "predefined_mapping": None},
            "channel_positions": {"layout_or_montage_name": "standard_1005"},
            "sampler": {"name": "ClassificationSampler"},
            "neuro": {"name": "EegExtractor", "event_types": "Eeg",
                      "aggregation": "single", "allow_missing": False,
                      "frequency": 120.0, "offset": 0.0, "baseline": None,
                      "picks": ["eeg"], "apply_proj": False,
                      "filter": [0.1, 75.0], "apply_hilbert": False,
                      "notch_filter": [50.0, 60.0], "drop_bads": False,
                      "scaler": "RobustScaler", "scale_factor": None,
                      "clamp": 20.0, "fill_non_finite": None,
                      "bipolar_ref": None, "channel_order": "unique",
                      "allow_maxshield": False},
            "trigger_event_type": "Eeg", "start": 0.0, "duration": 5.0,
            "stride": 5.0, "stride_drop_incomplete": True,
        },
        "brain_model_output_size": 2,
        "metrics": [{"name": "Accuracy", "log_name": "bal_acc",
                     "kwargs": {"task": "multiclass", "average": "macro", "num_classes": 2}}],
    }


class SeizureContractTests(unittest.TestCase):
    mapping = {"seiz": 0, "__missing__": -1}

    def lineage(self, events: list, target: list, *, segment_start: float = 0,
                timeline: str = "t1") -> dict:
        trigger = Eeg()
        segment = Segment(trigger, [trigger, *events], start=segment_start, timeline=timeline)
        return contract.lineage_entry(0, segment, trigger.to_dict(), target,
                                      self.mapping, "a" * 64)

    def test_pinned_config_and_native_missing_mapping(self) -> None:
        profile = contract.validate_profile(full_config(), task_id=contract.TASK_ID,
                                            source_name=contract.SOURCE_NAME,
                                            source_sha=contract.SOURCE_SHA)
        self.assertEqual(profile["native_target_aggregation"], "sum")
        self.assertEqual(profile["missing_tensor_index"], 1)
        self.assertEqual(contract.label_mapping_records(self.mapping, 2)[1],
                         {"native_label": "__missing__", "type": "str",
                          "native_index": -1, "index": 1})

    def test_generic_routes_only_the_pinned_seizure_case(self) -> None:
        profile = exporter.target_profile(full_config(), contract.TASK_ID, contract.SOURCE_NAME)
        self.assertEqual(profile["profile"], contract.PROFILE)
        self.assertEqual(profile["target_contract_module"]["sha256"], exporter.digest(contract.__file__))
        records = exporter.classification_mapping(self.mapping, 2, profile["profile"])
        self.assertEqual(records[1]["index"], 1)
        with self.assertRaises(ValueError):
            exporter.classification_mapping(self.mapping, 2, exporter.TRIGGER_PROFILE)
        with self.assertRaises(ValueError):
            exporter.target_profile(full_config(), "other/default", contract.SOURCE_NAME)
        with self.assertRaises(ValueError):
            exporter.target_profile(full_config(), contract.TASK_ID, "OtherStudy")

    def test_generic_routes_native_window_lineage_without_trigger_state(self) -> None:
        trigger = Eeg()
        segment = Segment(trigger, [trigger])
        plan = {"target_profile": contract.PROFILE, "label_to_ind": self.mapping}
        result = exporter.classification_lineage(0, segment, trigger.to_dict(), [0, 1],
                                                plan, "a" * 64, 1)
        self.assertEqual(result["event_value"], "__missing__")
        with self.assertRaisesRegex(ValueError, "serialized class index"):
            exporter.classification_lineage(0, segment, trigger.to_dict(), [0, 1],
                                           plan, "a" * 64, 0)

    def test_export_receipt_binds_the_seizure_target_module(self) -> None:
        recipe_path = Path(__file__).resolve().parent.parent / "eeg-seizure-chbmit/preparation.json"
        recipe = json.loads(recipe_path.read_text())
        recipe["expected_subjects"] = 3  # This test uses only synthetic subject IDs.
        with tempfile.TemporaryDirectory(prefix="bpb-seizure-receipt-") as directory:
            report = fixture(Path(directory), recipe)
            expected = {"name": "seizure_contract.py", "sha256": exporter.digest(contract.__file__)}
            report["target_contract_module"] = expected
            verify_fields(recipe, report)
            for wrong in (None, {**expected, "name": "other.py"}, {**expected, "sha256": "0" * 64}):
                report["target_contract_module"] = wrong
                with self.assertRaisesRegex(ValueError, "module hash mismatch"):
                    verify_fields(recipe, report)

    def test_config_mismatches_fail_closed(self) -> None:
        for path, wrong in (("target.aggregation", "trigger"),
                            ("target.treat_missing_as_separate_class", False),
                            ("target.event_types", "Eeg"),
                            ("data.duration", 4.0),
                            ("data.stride", 2.5),
                            ("split.split_by", "session"),
                            ("split.valid_random_state", 34),
                            ("split.stratify_by", None),
                            ("source.query", "timeline_index == 144"),
                            ("channel_positions.layout_or_montage_name", "standard_1020"),
                            ("sampler.name", "OtherSampler"),
                            ("neuro.frequency", 100.0),
                            ("neuro.filter", [1.0, 75.0]),
                            ("neuro.notch_filter", [60.0]),
                            ("neuro.picks", ["meg"]),
                            ("neuro.baseline", [0.0, 0.1]),
                            ("neuro.offset", 1.0),
                            ("neuro.scaler", "StandardScaler"),
                            ("neuro.clamp", 10.0),
                            ("neuro.channel_order", "sorted")):
            with self.subTest(path=path):
                config = copy.deepcopy(full_config())
                if path.startswith("target."):
                    block = config["data"]["target"]
                elif path.startswith("split."):
                    block = config["data"]["study"]["steps"]["split"]
                elif path.startswith("source."):
                    block = config["data"]["study"]["steps"]["source"]
                elif path.startswith("channel_positions.") or path.startswith("sampler.") \
                        or path.startswith("neuro."):
                    block = config["data"][path.split(".")[0]]
                else:
                    block = config["data"]
                block[path.rsplit(".", 1)[-1]] = wrong
                with self.assertRaises(ValueError):
                    contract.validate_profile(config, task_id=contract.TASK_ID,
                                              source_name=contract.SOURCE_NAME,
                                              source_sha=contract.SOURCE_SHA)
        with self.assertRaises(ValueError):
            contract.validate_profile(full_config(), task_id=contract.TASK_ID,
                                      source_name=contract.SOURCE_NAME, source_sha="other")
        extra_neuro = full_config()
        extra_neuro["data"]["neuro"]["new_scientific_field"] = True
        with self.assertRaisesRegex(ValueError, "scientific field set"):
            contract.validate_profile(extra_neuro, task_id=contract.TASK_ID,
                                      source_name=contract.SOURCE_NAME,
                                      source_sha=contract.SOURCE_SHA)
        resource_only = full_config()
        resource_only["data"]["neuro"].update(infra={"folder": "private-cache"}, mne_cpus=2)
        self.assertEqual(contract.validate_profile(
            resource_only, task_id=contract.TASK_ID, source_name=contract.SOURCE_NAME,
            source_sha=contract.SOURCE_SHA)["profile"], contract.PROFILE)

    def test_native_mapping_must_not_relabel_missing_to_zero(self) -> None:
        for mapping in ({"seiz": 0, "__missing__": 1},
                        {"seiz": 1, "__missing__": -1},
                        {"seiz": 0, "other": -1},
                        {"seiz": 0, "__missing__": -1, "other": 1}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                contract.label_mapping_records(mapping, 2)

    def test_missing_background_and_single_seizure_match_native_one_hot(self) -> None:
        missing = self.lineage([], [0, 1])
        self.assertEqual((missing["label"], missing["event_value"],
                          missing["overlapping_seizure_events"]), (1, "__missing__", []))
        seizure = self.lineage([Seizure(11)], [1, 0])
        self.assertEqual((seizure["label"], seizure["event_value"]), (0, "seiz"))
        self.assertEqual(seizure["overlapping_seizure_events"][0]["event_index"], 11)
        self.assertEqual(seizure["target_aggregation"], "sum")

    def test_native_target_must_match_events_without_argmax_or_imputation(self) -> None:
        for events, vector in (([], [1, 0]), ([Seizure(11)], [0, 1]),
                               ([], [0, 0]), ([Seizure(11)], [1, 1]),
                               ([Seizure(11)], [2, 0]), ([Seizure(11)], [0.5, 0.5])):
            with self.subTest(events=len(events), vector=vector), self.assertRaises(ValueError):
                self.lineage(events, vector)

    def test_two_overlapping_seizures_fail_even_if_vector_is_one_hot(self) -> None:
        with self.assertRaisesRegex(ValueError, "multiple overlapping"):
            self.lineage([Seizure(11), Seizure(12, start=3, duration=2)], [1, 0])

    def test_half_open_timeline_and_class_boundaries(self) -> None:
        for event in (Seizure(11, start=5, duration=2),
                      Seizure(11, start=0, duration=0.0),
                      Seizure(11, timeline="t2"),
                      Seizure(11, state="bckg"),
                      PretendSeizure(11)):
            with self.subTest(event=vars(event), cls=type(event).__name__), self.assertRaises(ValueError):
                self.lineage([event], [1, 0])

    def test_wrong_trigger_or_window_provenance_fails(self) -> None:
        trigger = Eeg()
        segment = Segment(trigger, [trigger, Seizure(11)], start=0, duration=4)
        with self.assertRaisesRegex(ValueError, "window duration"):
            contract.lineage_entry(0, segment, trigger.to_dict(), [1, 0], self.mapping, "a" * 64)
        segment.duration = 5
        record = trigger.to_dict()
        record["Index"] = 999
        with self.assertRaisesRegex(ValueError, "trigger table"):
            contract.lineage_entry(0, segment, record, [1, 0], self.mapping, "a" * 64)


if __name__ == "__main__":
    unittest.main()
