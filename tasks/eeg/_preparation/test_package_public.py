#!/usr/bin/env python3
"""Synthetic train/validation packaging and private-label exclusion checks."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import numpy as np

from package_public import package, trusted_receipt
from test_contract import ROOT, fixture, sha
import verify_export


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
    for task_id in ("eeg-sleep-stage-hmc", "eeg-sleep-onset-hmc", "eeg-sleep-onset-sleepedf"):
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
            if task_id == "eeg-sleep-onset-sleepedf":
                old_status_path = work / "original-failed-status.json"
                old_status = {"status": "failed_partial_output_preserved", "return_code": 2,
                              "abort_reason": None, "output": str(export),
                              "receipt": str(work / "absent-original-receipt.json"),
                              "manifest_sha256": "0" * 64}
                old_status_path.write_text(json.dumps(old_status), encoding="utf-8")
                recovery = {**receipt,
                            "schema": "bpb-eeg-existing-export-recovery/1",
                            "status": "existing_native_export_reverified",
                            "original_run_success": False,
                            "original_run": {"status_path": str(old_status_path),
                                             "status_sha256": sha(old_status_path),
                                             "status": old_status["status"],
                                             "return_code": old_status["return_code"]},
                            "recovery_verifier_sha256": sha(Path(verify_export.__file__))}
                recovery_path = work / "new-recovery-receipt.json"
                recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
                assert trusted_receipt(recipe, export, recovery_path)["original_run_success"] is False
                recovered = package(recipe, export, work / "recovered-package", recovery_path,
                                    ROOT / task_id)
                assert recovered["test_included"] is False

                def rejected_recovery(name: str, changed: dict, phrase: str) -> None:
                    path = work / f"recovery-{name}.json"
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    try:
                        trusted_receipt(recipe, export, path)
                    except ValueError as error:
                        assert phrase in str(error), error
                    else:
                        raise AssertionError(f"unsafe recovery receipt accepted: {name}")

                rejected_recovery("schema", {**recovery, "schema": "unreviewed/1"}, "unknown")
                rejected_recovery("status", {**recovery, "status": "native_data_exported_and_checked"},
                                  "wrong verification status")
                rejected_recovery("success", {**recovery, "original_run_success": True},
                                  "original run failure")
                rejected_recovery("verifier", {**recovery, "recovery_verifier_sha256": "f" * 64},
                                  "verifier hash")
                rejected_recovery("old-hash", {**recovery, "original_run": {
                    **recovery["original_run"], "status_sha256": "f" * 64}}, "failed status file")
                fake_status_path = work / "fake-completed-status.json"
                fake_status_path.write_text(json.dumps({**old_status, "status": "completed_data_only",
                                                        "return_code": 0}), encoding="utf-8")
                rejected_recovery("old-status", {**recovery, "original_run": {
                    **recovery["original_run"], "status_path": str(fake_status_path),
                    "status_sha256": sha(fake_status_path)}}, "does not bind")
                rejected_recovery("old-return", {**recovery, "original_run": {
                    **recovery["original_run"], "return_code": 0}}, "nonzero return code")
                rejected_recovery("vendor", {**recovery, "vendor_files": {}}, "pinned task/exporter")
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
            if recipe["target_kind"] == "regression":
                original_report = json.loads((export / "complete.json").read_text(encoding="utf-8"))
                altered_cap = json.loads(json.dumps(original_report))
                altered_cap["protocol"]["profile"]["target"]["cap_s"] = recipe["cap_s"] - 1
                (export / "complete.json").write_text(json.dumps(altered_cap), encoding="utf-8")
                receipt["export_complete_sha256"] = sha(export / "complete.json")
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                try:
                    package(recipe, export, work / "wrong-cap-package", receipt_path, ROOT / task_id)
                except ValueError as error:
                    assert "onset cap changed" in str(error), error
                else:
                    raise AssertionError("package accepted a changed native onset cap")
                (export / "complete.json").write_text(json.dumps(original_report), encoding="utf-8")
                receipt["export_complete_sha256"] = sha(export / "complete.json")
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
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
                      "changed_onset_cap_rejected": True,
                      "recovery_receipt_accepted_with_failed_origin_and_bad_bindings_rejected": True,
                      "wrong_exporter_code_hash_rejected": True,
                      "private_test_data_used": False}, sort_keys=True))


if __name__ == "__main__":
    main()
