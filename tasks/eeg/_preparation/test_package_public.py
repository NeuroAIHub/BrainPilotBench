#!/usr/bin/env python3
"""Synthetic train/validation packaging and private-label exclusion checks."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import numpy as np

from package_public import package
from test_contract import ROOT, fixture, sha


def full_fixture(root: Path, recipe: dict) -> None:
    report = fixture(root, recipe)
    for index, split in enumerate(("train", "val", "test")):
        folder = root / ("private" if split == "test" else "public") / split
        shard = folder / "000000.npz"
        x = np.full((1, 2, 4), float(index), dtype=np.float32)
        y = (np.array([[40.0]], dtype=np.float32) if recipe["target_kind"] == "regression"
             else np.array([index % recipe["n_outputs"]], dtype=np.int64))
        if split == "test":
            np.savez(shard, x=x)
            np.save(folder / "000000-labels.npy", y, allow_pickle=False)
            report["splits"][split]["shards"][0]["labels_sha256"] = sha(folder / "000000-labels.npy")
        else:
            np.savez(shard, x=x, y=y)
        report["splits"][split]["shards"][0]["sha256"] = sha(shard)
    (root / "complete.json").write_text(json.dumps(report), encoding="utf-8")


def main() -> None:
    cache = Path.cwd() / ".cache" / "eeg-d-expansion"
    cache.mkdir(parents=True, exist_ok=True)
    tested = []
    for task_id in ("eeg-sleep-stage-hmc", "eeg-sleep-onset-hmc"):
        recipe = json.loads((ROOT / task_id / "preparation.json").read_text(encoding="utf-8"))
        recipe["expected_subjects"] = 3  # synthetic population only
        with tempfile.TemporaryDirectory(prefix=f"{task_id}-package-", dir=cache) as directory:
            work = Path(directory)
            export = work / "export"; export.mkdir()
            full_fixture(export, recipe)
            source = work / "pinned-source"; source.mkdir()
            raw = work / "raw-data"; raw.mkdir()
            receipt_path = work / "trusted-receipt.json"
            receipt = {"schema": "bpb-eeg-native-export-run-receipt/1",
                       "status": "native_data_exported_and_checked",
                       "trusted_preparation_receipt": True,
                       "task_id": recipe["task_id"], "source_sha": recipe["source_sha"],
                       "vendor_files": recipe["vendor_files"],
                       "source": str(source), "raw_data_root": str(raw),
                       "output": str(export), "export_complete_sha256": sha(export / "complete.json"),
                       "calibration_manifest_sha256": "0" * 64,
                       "verification": {"status": "structure_and_hashes_checked_origin_unbound"}}
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = package(recipe, export, work / "package", receipt_path, ROOT / task_id)
            assert result["test_included"] is False
            public = work / "package" / "public"
            assert {p.name for p in public.iterdir()} == {
                "train.npz", "val.npz", "train-groups.json", "val-groups.json", "PREPARED.json"}
            groups = json.loads((public / "train-groups.json").read_text(encoding="utf-8"))
            assert groups["group_unit"] == "subject" and len(groups["groups"]) == 1
            assert "private-original-identity" not in (public / "train-groups.json").read_text(encoding="utf-8")
            with np.load(public / "train.npz", allow_pickle=False) as arrays:
                assert set(arrays.files) == {"x", "y"} and arrays["x"].shape == (1, 2, 4)
            assert (work / "package" / "evaluator" / "binding.json").is_file()
            assert json.loads((work / "package" / "state.json").read_text())["status"] == "complete_candidate_not_accepted"
            try:
                package(recipe, export, export / "nested-package", receipt_path, ROOT / task_id)
            except ValueError as error:
                assert "overlaps native export" in str(error), error
            else:
                raise AssertionError("package inside frozen export was accepted")
            alias = work / "export-alias"
            alias.symlink_to(export, target_is_directory=True)
            try:
                package(recipe, export, alias / "nested-package", receipt_path, ROOT / task_id)
            except ValueError as error:
                assert "overlaps native export" in str(error), error
            else:
                raise AssertionError("symlink alias into frozen export was accepted")
            altered = json.loads((export / "complete.json").read_text(encoding="utf-8"))
            altered["code_sha256"] = "1" * 64
            (export / "complete.json").write_text(json.dumps(altered), encoding="utf-8")
            receipt["export_complete_sha256"] = sha(export / "complete.json")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            try:
                package(recipe, export, work / "wrong-code-package", receipt_path, ROOT / task_id)
            except ValueError as error:
                assert "pinned vendored code" in str(error), error
            else:
                raise AssertionError("wrong exporter code hash was accepted")
            tested.append(task_id)
    print(json.dumps({"synthetic_packages": tested,
                      "public_files_only": True, "source_subject_names_withheld": True,
                      "inside_export_and_symlink_alias_rejected": True,
                      "wrong_exporter_code_hash_rejected": True,
                      "private_test_data_used": False}, sort_keys=True))


if __name__ == "__main__":
    main()
