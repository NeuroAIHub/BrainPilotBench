#!/usr/bin/env python3
"""Synthetic role-boundary checks; no native data, Agent, or Test is touched."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile

from verify_export import verify_export

ROOT = Path(__file__).resolve().parent.parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path, recipe: dict) -> dict:
    kind = recipe["target_kind"]
    splits = {}
    groups = {}
    (root / "lineage").mkdir()
    for split in ("train", "val", "test"):
        role = "private" if split == "test" else "public"
        relative = f"{role}/{split}"
        folder = root / relative
        folder.mkdir(parents=True)
        shard = folder / "000000.npz"
        with ZipFile(shard, "w") as archive:
            archive.writestr("x.npy", b"synthetic x")
            if split != "test":
                archive.writestr("y.npy", b"synthetic y")
        entry = {"file": shard.name, "sha256": sha(shard), "samples": 1}
        if split == "test":
            labels = folder / "000000-labels.npy"
            labels.write_bytes(b"synthetic private y")
            entry.update(labels_file=labels.name, labels_sha256=sha(labels))
        item = {"directory": relative, "samples": 1, "sample_shape": [2, 4], "shards": [entry]}
        if kind == "regression":
            item["target_summary"] = {"bin_edges": recipe["bin_edges"], "bin_counts": [0, 1, 0, 0],
                                      "out_of_range_targets": 0}
        subject = f"private-original-identity-{split}"
        lineage = root / "lineage" / f"{split}.jsonl"
        lineage.write_text(json.dumps({"index": 0, "subject": subject}) + "\n", encoding="utf-8")
        item["lineage"] = {"file": f"lineage/{split}.jsonl", "rows": 1, "sha256": sha(lineage)}
        groups[split] = {"samples": 1, "subjects": [subject]}
        splits[split] = item
    report = {
        "status": "sleep-onset-native-data-exported" if kind == "regression" else "classification-native-data-exported",
        "task_id": recipe["source_task_id"], "task_kind": kind,
        "source_sha": recipe["source_sha"], "source_population_query": None,
        "source": {"name": recipe["source_dataset"], "checkout": {"head": recipe["source_sha"]}},
        "subject_count": recipe["expected_subjects"], "declared_subjects": recipe["expected_subjects"],
        "n_outputs": recipe["n_outputs"], "input_shape": [2, 4],
        "training_executed": False, "model_fitted": False, "published": False,
        "code_sha256": recipe["vendor_files"][recipe["exporter"]],
        "calibration_manifest": {"sha256": "0" * 64},
        "samples": {name: 1 for name in splits}, "splits": splits,
    }
    group_report = {"rule": "subject-disjoint", "split_by": "subject", "groups": groups}
    if kind == "regression":
        report.update(metric={"name": "BinnedMAE", "log_name": "bmae", "bin_edges": recipe["bin_edges"]},
                      target_definition=recipe["target_definition"],
                      protocol={"profile": {"cap_s": recipe["cap_s"]}, "groups": group_report},
                      generic_export_sha256=recipe["vendor_files"]["export_classification_native.py"],
                      contract_module={"sha256": recipe["vendor_files"]["sleep_special_contract.py"]})
    else:
        report.update(protocol={"primary_metric": {"name": "Accuracy", "log_name": "bal_acc"},
                                "groups": group_report},
                      target_profile=recipe["target_profile"])
    (root / "complete.json").write_text(json.dumps(report), encoding="utf-8")
    return report


def main() -> None:
    cache = Path.cwd() / ".cache" / "eeg-d-expansion"
    cache.mkdir(parents=True, exist_ok=True)
    tested = []
    for task_id in ("eeg-sleep-stage-hmc", "eeg-sleep-onset-hmc"):
        recipe = json.loads((ROOT / task_id / "preparation.json").read_text(encoding="utf-8"))
        recipe["expected_subjects"] = 3  # synthetic population only
        with tempfile.TemporaryDirectory(prefix=f"{task_id}-synthetic-", dir=cache) as directory:
            output = Path(directory)
            fixture(output, recipe)
            passed = verify_export(recipe, output)
            assert passed["files_checked"] == 7
            manifest = json.loads((output / "complete.json").read_text(encoding="utf-8"))
            test_lineage = output / "lineage/test.jsonl"
            original = test_lineage.read_text(encoding="utf-8")
            test_lineage.write_text(json.dumps({"index": 0, "subject": "private-original-identity-train"}) + "\n", encoding="utf-8")
            manifest["splits"]["test"]["lineage"]["sha256"] = sha(test_lineage)
            (output / "complete.json").write_text(json.dumps(manifest), encoding="utf-8")
            try:
                verify_export(recipe, output)
            except ValueError as error:
                assert "actual lineage" in str(error), error
            else:
                raise AssertionError("actual Test lineage leakage hidden by summary was accepted")
            test_lineage.write_text(original, encoding="utf-8")
            manifest["splits"]["test"]["lineage"]["sha256"] = sha(test_lineage)
            (output / "complete.json").write_text(json.dumps(manifest), encoding="utf-8")
            private = output / "private" / "test" / "000000.npz"
            with ZipFile(private, "a") as archive:
                archive.writestr("y.npy", b"forbidden hidden target")
            manifest = json.loads((output / "complete.json").read_text(encoding="utf-8"))
            manifest["splits"]["test"]["shards"][0]["sha256"] = sha(private)
            (output / "complete.json").write_text(json.dumps(manifest), encoding="utf-8")
            try:
                verify_export(recipe, output)
            except ValueError as error:
                assert "visibility" in str(error), error
            else:
                raise AssertionError("private target inside mounted feature shard was accepted")
            manifest["protocol"]["groups"]["groups"]["test"]["subjects"] = [
                "private-original-identity-train"]
            (output / "complete.json").write_text(json.dumps(manifest), encoding="utf-8")
            try:
                verify_export(recipe, output)
            except ValueError as error:
                assert "subject leakage" in str(error), error
            else:
                raise AssertionError("cross-split Test subject leakage was accepted")
            tested.append(task_id)
    print(json.dumps({"synthetic_export_structure": tested,
                      "private_test_target_leak_rejected": True,
                      "cross_split_test_group_leak_rejected": True,
                      "native_data_or_test_used": False}, sort_keys=True))


if __name__ == "__main__":
    main()
