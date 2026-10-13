#!/usr/bin/env python3
"""Verify one native data-only export before any public/private packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            value.update(block)
    return value.hexdigest()


def safe_file(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError(f"unsafe export path: {relative!r}")
    candidate = root.joinpath(*rel.parts)
    if candidate.is_symlink() or not candidate.is_file() or root not in candidate.resolve().parents:
        raise ValueError(f"missing, linked, or escaping export file: {relative!r}")
    return candidate


def verify_fields(recipe: dict, report: dict) -> dict:
    wanted = "sleep-onset-native-data-exported" if recipe["target_kind"] == "regression" else "classification-native-data-exported"
    if report.get("status") != wanted or report.get("task_id") != recipe["source_task_id"]:
        raise ValueError("export status or native task ID mismatch")
    if report.get("source_sha") != recipe["source_sha"] or report.get("source_population_query") is not None:
        raise ValueError("native source SHA or full-population query mismatch")
    source = report.get("source") or {}
    if source.get("name") != recipe["source_dataset"] or (source.get("checkout") or {}).get("head") != recipe["source_sha"]:
        raise ValueError("native source study or checkout identity mismatch")
    if report.get("task_kind") != recipe["target_kind"]:
        raise ValueError("target kind mismatch")
    if report.get("code_sha256") != recipe["vendor_files"][recipe["exporter"]]:
        raise ValueError("native export was not produced by the pinned vendored code")
    if recipe["target_kind"] == "regression":
        if report.get("generic_export_sha256") != recipe["vendor_files"]["export_classification_native.py"]:
            raise ValueError("onset generic exporter dependency hash mismatch")
        if (report.get("contract_module") or {}).get("sha256") != recipe["vendor_files"]["sleep_special_contract.py"]:
            raise ValueError("onset metric/target contract module hash mismatch")
    if report.get("subject_count") != recipe["expected_subjects"]:
        raise ValueError("subject count differs from pinned source declaration")
    if report.get("n_outputs") != recipe["n_outputs"]:
        raise ValueError("native output cardinality mismatch")
    shape = report.get("input_shape")
    if not isinstance(shape, list) or len(shape) != 2 or not all(type(x) is int and x > 0 for x in shape):
        raise ValueError("native export did not establish [channels,time] input shape")
    if report.get("training_executed") is not False or report.get("model_fitted") is not False:
        raise ValueError("data-only export unexpectedly ran model training")
    if report.get("published") is not False:
        raise ValueError("export incorrectly claims publication")
    if recipe["target_kind"] == "regression":
        metric = report.get("metric") or {}
        if (metric.get("name"), metric.get("log_name"), metric.get("bin_edges")) != (
            "BinnedMAE", "bmae", recipe["bin_edges"]):
            raise ValueError("native onset BinnedMAE or bin edges drifted")
        if report.get("target_definition") != recipe["target_definition"]:
            raise ValueError("native onset target definition drifted")
        if report.get("declared_subjects") != recipe["expected_subjects"]:
            raise ValueError("onset declared subject count drifted")
        protocol = report.get("protocol") or {}
        cap_locations = {
            "profile.target": (protocol.get("profile") or {}).get("target") or {},
            "target": protocol.get("target") or {},
            "resolved_target": protocol.get("resolved_target") or {},
        }
        for location, target in cap_locations.items():
            if target.get("cap_s") != recipe["cap_s"]:
                raise ValueError(f"onset cap changed in protocol.{location}")
    else:
        primary = (report.get("protocol") or {}).get("primary_metric") or {}
        if primary.get("name") != "Accuracy" or primary.get("log_name") != "bal_acc":
            raise ValueError("native classification primary metric drifted")
        if recipe.get("target_profile") and report.get("target_profile") != recipe["target_profile"]:
            raise ValueError("native target aggregation/profile drifted")
        if recipe.get("target_profile") == "native-seizure-sum-missing-last-v1":
            module = report.get("target_contract_module") or {}
            if (module.get("name") != "seizure_contract.py" or
                    module.get("sha256") != recipe["vendor_files"].get("seizure_contract.py")):
                raise ValueError("native seizure sum-target module hash mismatch")
    samples = report.get("samples")
    if not isinstance(samples, dict) or set(samples) != {"train", "val", "test"}:
        raise ValueError("native split set differs from train/val/test")
    if any(type(value) is not int or value < 1 for value in samples.values()):
        raise ValueError("empty or malformed native split")
    return {"input_shape": shape, "samples": samples}


def verify_export(recipe: dict, export_dir: Path, hash_files: bool = True) -> dict:
    if export_dir.is_symlink() or not export_dir.is_dir():
        raise ValueError("export directory is absent or linked")
    root = export_dir.resolve()
    if (root / "failed.json").exists():
        raise ValueError("export contains a failure receipt")
    report = json.loads(safe_file(root, "complete.json").read_text(encoding="utf-8"))
    summary = verify_fields(recipe, report)
    splits = report.get("splits")
    if not isinstance(splits, dict) or set(splits) != {"train", "val", "test"}:
        raise ValueError("export split manifest is incomplete")
    groups_report = (report.get("protocol") or {}).get("groups") or {}
    if groups_report.get("rule") != "subject-disjoint" or groups_report.get("split_by") != "subject":
        raise ValueError("native full export did not prove subject-disjoint folds")
    groups = groups_report.get("groups") or {}
    if not isinstance(groups, dict) or set(groups) != {"train", "val", "test"}:
        raise ValueError("native split-group evidence is incomplete")
    subject_sets = {}
    for split in ("train", "val", "test"):
        subjects = groups[split].get("subjects")
        if not isinstance(subjects, list) or not subjects:
            raise ValueError(f"{split}: source subject-group evidence missing")
        subject_sets[split] = {json.dumps(value, sort_keys=True) for value in subjects}
        if len(subject_sets[split]) != len(subjects):
            raise ValueError(f"{split}: duplicate source subject group")
    if any(subject_sets[left] & subject_sets[right] for left, right in
           (("train", "val"), ("train", "test"), ("val", "test"))):
        raise ValueError("native subject leakage across train/validation/Test")
    if len(set().union(*subject_sets.values())) != recipe["expected_subjects"]:
        raise ValueError("native group union differs from declared full population")
    files_checked = 0
    lineage_hashes = {}
    for split in ("train", "val", "test"):
        item = splits[split]
        expected_dir = f"{'private' if split == 'test' else 'public'}/{split}"
        if item.get("directory") != expected_dir or item.get("samples") != summary["samples"][split]:
            raise ValueError(f"{split}: wrong role directory or sample count")
        if item.get("sample_shape") != summary["input_shape"]:
            raise ValueError(f"{split}: input shape drift")
        if groups[split].get("samples") != item["samples"]:
            raise ValueError(f"{split}: native group/sample count mismatch")
        lineage = item.get("lineage") or {}
        if lineage.get("file") != f"lineage/{split}.jsonl" or lineage.get("rows") != item["samples"]:
            raise ValueError(f"{split}: native lineage metadata missing")
        lineage_file = safe_file(root, lineage["file"])
        lineage_hashes[split] = digest(lineage_file)
        if lineage_hashes[split] != lineage.get("sha256"):
            raise ValueError(f"{split}: native lineage digest mismatch")
        # Check actual membership, not only the group summary in complete.json.
        # Lineage is evaluator-only. No response/target value is used here.
        actual_subjects = set()
        lineage_rows = 0
        with lineage_file.open(encoding="utf-8") as stream:
            for index, line in enumerate(stream):
                record = json.loads(line)
                if record.get("index") != index or record.get("subject") in (None, ""):
                    raise ValueError(f"{split}: invalid lineage index or subject")
                actual_subjects.add(json.dumps(record["subject"], sort_keys=True))
                lineage_rows += 1
        if lineage_rows != item["samples"] or actual_subjects != subject_sets[split]:
            raise ValueError(f"{split}: actual lineage differs from native group summary")
        files_checked += 1
        shards = item.get("shards")
        if not isinstance(shards, list) or not shards:
            raise ValueError(f"{split}: no shards")
        shard_total = 0
        for index, shard in enumerate(shards):
            filename = shard.get("file")
            if filename != f"{index:06d}.npz":
                raise ValueError(f"{split}: shard order is not contiguous")
            path = safe_file(root, f"{expected_dir}/{filename}")
            if hash_files and digest(path) != shard.get("sha256"):
                raise ValueError(f"{split}: shard digest mismatch")
            with ZipFile(path) as container:
                members = set(container.namelist())
            wanted = {"x.npy"} if split == "test" else {"x.npy", "y.npy"}
            if members != wanted:
                raise ValueError(f"{split}: feature/target visibility differs from native export")
            files_checked += 1
            if split == "test":
                label = shard.get("labels_file")
                if label != f"{index:06d}-labels.npy":
                    raise ValueError("private label shard is missing or out of order")
                label_path = safe_file(root, f"{expected_dir}/{label}")
                if hash_files and digest(label_path) != shard.get("labels_sha256"):
                    raise ValueError("private label digest mismatch")
                files_checked += 1
            elif "labels_file" in shard:
                raise ValueError("public shard unexpectedly references a private label file")
            n = shard.get("samples")
            if type(n) is not int or n < 1:
                raise ValueError(f"{split}: malformed shard sample count")
            shard_total += n
        if shard_total != item["samples"]:
            raise ValueError(f"{split}: shard totals differ from native split")
        if recipe["target_kind"] == "regression":
            target_summary = item.get("target_summary") or {}
            if target_summary.get("bin_edges") != recipe["bin_edges"]:
                raise ValueError(f"{split}: onset bin edges drifted")
            counts = target_summary.get("bin_counts")
            if not isinstance(counts, list) or len(counts) != len(recipe["bin_edges"]) - 1:
                raise ValueError(f"{split}: onset bin counts missing")
    return {"status": "structure_and_hashes_checked_origin_unbound" if hash_files else "structure_only_origin_unbound",
            "task_id": recipe["task_id"], "native_task_id": recipe["source_task_id"],
            "subjects": recipe["expected_subjects"], "input_shape": summary["input_shape"],
            "samples": summary["samples"], "files_checked": files_checked,
            "lineage_sha256": lineage_hashes,
            "public_paths": ["public/train", "public/val"],
            "evaluator_only_paths": ["private/test", "lineage"]}


def main(task_dir: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--no-hashes", action="store_true", help="structure-only diagnostic; never acceptance")
    args = parser.parse_args()
    recipe = json.loads((task_dir / "preparation.json").read_text(encoding="utf-8"))
    result = verify_export(recipe, args.export, hash_files=not args.no_hashes)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parent))
