#!/usr/bin/env python3
"""Convert a verified native shard export into four hash-bound public task files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile

from paths import canonical_new_path, disjoint
from sleep_special_contract import assign_bin
from verify_export import safe_file, verify_export


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            value.update(block)
    return value.hexdigest()


def lineage_subjects(root: Path, split: str, manifest: dict, expected: int) -> tuple[list[str], str]:
    lineage = manifest["splits"][split].get("lineage") or {}
    relative = lineage.get("file")
    if relative != f"lineage/{split}.jsonl":
        raise ValueError(f"{split}: unexpected lineage path")
    path = safe_file(root, relative)
    actual_hash = digest(path)
    if actual_hash != lineage.get("sha256"):
        raise ValueError(f"{split}: lineage digest mismatch")
    keys = []
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            record = json.loads(line)
            if record.get("index") != index or record.get("subject") in (None, ""):
                raise ValueError(f"{split}: lineage order or subject identity invalid")
            keys.append(json.dumps(record["subject"], sort_keys=True, ensure_ascii=False))
    if len(keys) != expected or lineage.get("rows") != expected:
        raise ValueError(f"{split}: lineage row count mismatch")
    return keys, actual_hash


def merge_split(root: Path, split: str, manifest: dict, recipe: dict,
                output: Path, scratch: Path) -> None:
    import numpy as np

    item = manifest["splits"][split]
    count = item["samples"]
    shape = tuple(manifest["input_shape"])
    x_path, y_path = scratch / f"{split}-x.npy", scratch / f"{split}-y.npy"
    x_all = np.lib.format.open_memmap(x_path, mode="w+", dtype=np.float32, shape=(count, *shape))
    y_dtype = np.float32 if recipe["target_kind"] == "regression" else np.int64
    y_all = np.lib.format.open_memmap(y_path, mode="w+", dtype=y_dtype, shape=(count,))
    cursor = 0
    native_bin_counts = [0] * (len(recipe["bin_edges"]) - 1) if recipe["target_kind"] == "regression" else None
    for shard in item["shards"]:
        path = safe_file(root, f"public/{split}/{shard['file']}")
        with np.load(path, allow_pickle=False) as arrays:
            x, y = arrays["x"], arrays["y"]
            n = shard["samples"]
            if x.shape != (n, *shape) or x.dtype != np.float32 or not np.isfinite(x).all():
                raise ValueError(f"{split}: invalid native feature shape, dtype, or value")
            if recipe["target_kind"] == "regression":
                # Native scalar_targets exports [N,1]; package only a lossless [N] view.
                if y.shape != (n, 1) or y.dtype != np.float32 or not np.isfinite(y).all() \
                        or (y < 0).any() or (y > recipe["cap_s"]).any():
                    raise ValueError(f"{split}: onset target differs from native scalar seconds/cap")
                y = y[:, 0]
                for value in y:
                    bin_index = assign_bin(float(value), recipe["bin_edges"])
                    if bin_index is None:
                        raise ValueError(f"{split}: clipped native onset target fell outside metric edges")
                    native_bin_counts[bin_index] += 1
            elif y.shape != (n,) or y.dtype != np.int64 or not np.isfinite(y).all() \
                    or (y < 0).any() or (y >= recipe["n_outputs"]).any():
                raise ValueError(f"{split}: class index differs from native mapping/cardinality")
            x_all[cursor:cursor+n] = x
            y_all[cursor:cursor+n] = y
            cursor += n
    if cursor != count:
        raise ValueError(f"{split}: shard sample count mismatch")
    if native_bin_counts is not None:
        target_summary = item.get("target_summary") or {}
        if target_summary.get("bin_counts") != native_bin_counts \
                or target_summary.get("out_of_range_targets") != 0:
            raise ValueError(f"{split}: exported BinnedMAE bin counts disagree with native targets")
    x_all.flush(); y_all.flush()
    np.savez(output, x=x_all, y=y_all)
    with ZipFile(output) as copied:
        if set(copied.namelist()) != {"x.npy", "y.npy"}:
            raise ValueError(f"{split}: packaged array members mismatch")
        for name, expected_shape in (("x.npy", (count, *shape)), ("y.npy", (count,))):
            with copied.open(name) as member:
                version = np.lib.format.read_magic(member)
                if version == (1, 0):
                    actual_shape, _, _ = np.lib.format.read_array_header_1_0(member)
                elif version == (2, 0):
                    actual_shape, _, _ = np.lib.format.read_array_header_2_0(member)
                else:
                    raise ValueError(f"{split}: unsupported NPY member version {version}")
                if actual_shape != expected_shape:
                    raise ValueError(f"{split}: packaged array header shape mismatch")


def trusted_receipt(recipe: dict, export_dir: Path, receipt_path: Path) -> dict:
    if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > 1024 * 1024:
        raise ValueError("trusted preparation receipt is missing, linked, or oversized")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema") != "bpb-eeg-native-export-run-receipt/1"
            or receipt.get("status") != "native_data_exported_and_checked"
            or receipt.get("trusted_preparation_receipt") is not True
            or receipt.get("task_id") != recipe["task_id"]
            or receipt.get("source_sha") != recipe["source_sha"]
            or receipt.get("vendor_files") != recipe["vendor_files"]):
        raise ValueError("preparation receipt does not bind this pinned task/exporter")
    if Path(receipt.get("output", "")).resolve(strict=True) != export_dir.resolve(strict=True):
        raise ValueError("preparation receipt names a different native export")
    if receipt.get("export_complete_sha256") != digest(export_dir / "complete.json"):
        raise ValueError("native complete.json changed after the trusted preparation receipt")
    report = json.loads(safe_file(export_dir.resolve(), "complete.json").read_text(encoding="utf-8"))
    if (report.get("calibration_manifest") or {}).get("sha256") != receipt.get("calibration_manifest_sha256"):
        raise ValueError("calibration manifest hash differs from the exporter receipt")
    verification = receipt.get("verification") or {}
    if verification.get("status") != "structure_and_hashes_checked_origin_unbound":
        raise ValueError("trusted exporter receipt lacks full structure/hash verification")
    for field in ("source", "raw_data_root"):
        if not Path(receipt.get(field, "")).resolve(strict=True).is_dir():
            raise ValueError(f"trusted receipt {field} is no longer accessible")
    return receipt


def package(recipe: dict, export_dir: Path, destination: Path, receipt_path: Path,
            task_dir: Path) -> dict:
    if export_dir.is_symlink() or not export_dir.is_dir():
        raise ValueError("native export is absent or linked")
    root = export_dir.resolve(strict=True)
    receipt = trusted_receipt(recipe, root, receipt_path)
    destination = canonical_new_path(destination, "public package")
    disjoint(destination, {"native export": root,
                           "pinned scientific source": Path(receipt["source"]),
                           "raw source data": Path(receipt["raw_data_root"]),
                           "task directory": task_dir.resolve()}, "public package")
    verification = verify_export(recipe, export_dir, hash_files=True)
    report = json.loads(safe_file(root, "complete.json").read_text(encoding="utf-8"))
    train_keys, train_lineage = lineage_subjects(root, "train", report, report["samples"]["train"])
    val_keys, val_lineage = lineage_subjects(root, "val", report, report["samples"]["val"])
    if set(train_keys) & set(val_keys):
        raise ValueError("subject leakage between public train and validation")
    # Stable opaque group IDs preserve the native subject grouping without shipping raw IDs.
    group_id = {key: index for index, key in enumerate(sorted(set(train_keys + val_keys)))}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700, exist_ok=False)  # atomically reserve this new owner path
    (destination / "state.json").write_text(json.dumps({"status": "building", "task_id": recipe["task_id"]}) + "\n",
                                            encoding="utf-8")
    public = destination / "public"
    evaluator = destination / "evaluator"
    public.mkdir(mode=0o755); evaluator.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".array-staging-", dir=destination) as temp:
        scratch = Path(temp)
        for split, keys, lineage_hash in (("train", train_keys, train_lineage),
                                          ("val", val_keys, val_lineage)):
            merge_split(root, split, report, recipe, public / f"{split}.npz", scratch)
            groups = {"schema": "bpb-native-subject-groups/1", "split": split,
                      "group_unit": "subject", "rows": len(keys),
                      "groups": [group_id[key] for key in keys],
                      "source_lineage_sha256": lineage_hash,
                      "identity_policy": "opaque public IDs; real source subject names withheld"}
            (public / f"{split}-groups.json").write_text(
                json.dumps(groups, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    data_files = {}
    for name in ("train.npz", "val.npz", "train-groups.json", "val-groups.json"):
        path = public / name
        data_files[name] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    public_receipt = {"schema": "bpb-eeg-public-package-candidate/1", "task_id": recipe["task_id"],
                      "source_task_id": recipe["source_task_id"], "source_sha": recipe["source_sha"],
                      "target_kind": recipe["target_kind"], "metric": recipe["metric"],
                      "input_shape": verification["input_shape"], "samples": {
                          "train": verification["samples"]["train"], "val": verification["samples"]["val"]},
                      "data_files": data_files, "test_included": False,
                      "status": "public_package_candidate_hash_bound_not_accepted"}
    (public / "PREPARED.json").write_text(json.dumps(public_receipt, indent=2) + "\n", encoding="utf-8")
    private_binding = {"schema": "bpb-eeg-evaluator-source-binding/1", "task_id": recipe["task_id"],
                       "private_test_source": str(root / "private" / "test"),
                       "source_complete_sha256": digest(root / "complete.json"),
                       "status": "controller_only_not_scored", "test_consumed": False}
    (evaluator / "binding.json").write_text(json.dumps(private_binding, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        for path in public.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        for path in evaluator.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
    (destination / "state.json").write_text(json.dumps({"status": "complete_candidate_not_accepted",
                                                 "task_id": recipe["task_id"],
                                                 "source_complete_sha256": receipt["export_complete_sha256"]}) + "\n",
                                            encoding="utf-8")
    return {"task_id": recipe["task_id"], "status": public_receipt["status"],
            "public_data_files": data_files, "test_included": False,
            "evaluator_binding": str(evaluator / "binding.json")}


def main(task_dir: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--preparation-receipt", type=Path, required=True)
    args = parser.parse_args()
    recipe = json.loads((task_dir / "preparation.json").read_text(encoding="utf-8"))
    result = package(recipe, args.export, args.destination, args.preparation_receipt, task_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parent))
