"""Freeze a verified M1-A or M2 export into task-local contract and data lock.

This command requires complete Train, Valid, and Test manifests and both trusted
receipts. It creates new files only. It does not evaluate a Test model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from export import (ARRAYS, ASSET_MANIFEST_SHA, DOMAIN, PROFILE, SOURCE_SHA,
                    SPECS, digest, frozen_sources)


def checked_manifest(path: Path, role: str, task_id: str, exporter_sha: str,
                     protocol_sha: str) -> tuple[dict, dict]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if (manifest.get("schema") != "bpb-falcon-regression-data/1"
            or manifest.get("task_id") != task_id or manifest.get("profile") != PROFILE
            or manifest.get("role") != role or manifest.get("source_sha") != SOURCE_SHA
            or manifest.get("source_manifest_sha256") != ASSET_MANIFEST_SHA
            or manifest.get("protocol_sha256") != protocol_sha
            or manifest.get("exporter_sha256") != exporter_sha):
        raise ValueError(f"derived {role} provenance mismatch")
    runs = manifest["runs"]
    expected_runs, expected_dates = SPECS[task_id]["counts"][role]
    if (len(runs), len({run["session_id"] for run in runs})) != (expected_runs, expected_dates):
        raise ValueError(f"derived {role} run/date counts mismatch")
    channels = SPECS[task_id]["channels"]
    outputs = SPECS[task_id]["outputs"]
    for run in runs:
        if run["role"] != role or set(run["files"]) != set(ARRAYS):
            raise ValueError("run role or arrays changed")
        t = run["files"]["x.npy"]["shape"][0]
        expected = {"x.npy": ([t, channels], "uint8"), "y.npy": ([t, outputs], "float64"),
                    "mask.npy": ([t], "bool"), "trial_start.npy": ([t], "bool")}
        for name, info in run["files"].items():
            if (info["shape"], info["dtype"]) != expected[name]:
                raise ValueError("derived array shape or dtype changed")
            relative = Path(info["path"])
            actual = (path.parent / relative).resolve()
            if (relative.is_absolute() or ".." in relative.parts
                    or not actual.is_relative_to(path.parent.resolve())
                    or actual.stat().st_size != info["bytes"] or digest(actual) != info["sha256"]):
                raise ValueError("derived array path or digest invalid")
    return manifest, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                      "runs": len(runs), "sessions": expected_dates}


def build(task_id: str, root: Path, public_receipt: Path, evaluator_receipt: Path) -> dict:
    _, protocol, assets = frozen_sources(task_id)
    task = DOMAIN / task_id
    contract_path = task / "contract.json"
    lock_path = task / "data.lock"
    if contract_path.exists() or lock_path.exists():
        raise FileExistsError("contract or data lock already exists")
    protocol_sha = digest(task / "protocol.json")
    selective = task_id == "falcon-m2-finger-velocity"
    exporter_sha = digest(Path(__file__).with_name("selective_m2.py" if selective else "export.py"))
    paths = {"train": root / "public/train/manifest.json",
             "valid": root / "public/valid/manifest.json",
             "test": root / "evaluator/test/manifest.json"}
    derived, summaries = {}, {}
    for role, path in paths.items():
        derived[role], summaries[role] = checked_manifest(path, role, task_id, exporter_sha, protocol_sha)
    receipts = [json.loads(path.read_text()) for path in (public_receipt, evaluator_receipt)]
    if [receipt["access"] for receipt in receipts] != ["public", "evaluator"]:
        raise ValueError("public and evaluator receipt order changed")
    source_by_id = {asset["asset_id"]: asset for asset in assets}
    bindings = {}
    for receipt in receipts:
        if (receipt.get("schema") != ("bpb-falcon-regression-selective-export/1" if selective
                                      else "bpb-falcon-regression-export/1")
                or receipt.get("task_id") != task_id or receipt.get("profile") != PROFILE
                or receipt.get("source_manifest_sha256") != ASSET_MANIFEST_SHA
                or receipt.get("protocol_sha256") != protocol_sha
                or receipt.get("exporter_sha256") != exporter_sha):
            raise ValueError("trusted receipt provenance mismatch")
        for binding in receipt["source_bindings"]:
            if binding["id"] in bindings:
                raise ValueError("duplicate run binding")
            asset = source_by_id[binding["source_asset_id"]]
            if (binding["role"], binding["date"], binding["source_sha256"], binding["source_bytes"]) != (
                    asset["role"], asset["session_date"], asset["sha256"], asset["size_bytes"]):
                raise ValueError("receipt source binding changed")
            if selective:
                range_path = (root / ("evaluator" if asset["role"] == "test" else "public")
                              / "selected_sources" / asset["asset_id"] / "receipt.json")
                if (binding.get("full_raw_sha256_verified") is not False
                        or digest(range_path) != binding.get("selected_range_receipt_sha256")):
                    raise ValueError("selected HTTP range receipt does not match source binding")
                range_receipt = json.loads(range_path.read_text())
                if (range_receipt.get("source_asset_id") != asset["asset_id"]
                        or range_receipt.get("source_dandi_etag") != asset["dandi_etag"]
                        or range_receipt.get("full_raw_sha256_verified") is not False):
                    raise ValueError("selected HTTP range receipt provenance mismatch")
            bindings[binding["id"]] = (asset, binding, range_receipt if selective else None)
    if len(bindings) != len(assets):
        raise ValueError("not all source assets are bound")
    exported = []
    lock_lines = [] if selective else [
        f"# Frozen {task_id} public-origin NWB assets; Test is evaluator-only.",
        f"# Source {SOURCE_SHA}; source manifest SHA-256 {ASSET_MANIFEST_SHA}.",
        "# Full raw NWB SHA-256 was locally verified.", "datasets:"]
    for role in ("train", "valid", "test"):
        for run in derived[role]["runs"]:
            asset, binding, range_receipt = bindings[run["id"]]
            if (asset["role"] != role or asset["session_date"] != run["session_id"]
                    or binding["files"] != run["files"]):
                raise ValueError("run role/date differs from source")
            exported_run = {"id": run["id"], "role": role, "session_id": run["session_id"],
                            "source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
                            "source_bytes": asset["size_bytes"], "files": run["files"],
                            "full_raw_sha256_verified": not selective}
            if selective:
                exported_run["selected_range_receipt_sha256"] = binding["selected_range_receipt_sha256"]
                exported_run["selected_downloaded_bytes"] = binding["selected_downloaded_bytes"]
                exported_run["versioned_metadata_sha256"] = range_receipt["metadata_json_sha256"]
                exported_run["native_hdf5_metadata_sha256"] = range_receipt["native_hdf5_metadata_sha256"]
            exported.append(exported_run)
            if not selective:
                lock_lines.extend((f"  - name: {run['id']}.nwb",
                                   f"    uri: https://api.dandiarchive.org/api/assets/{asset['asset_id']}/download/",
                                   f"    sha256: {asset['sha256']}", f"    bytes: {asset['size_bytes']}",
                                   "    format: nwb", f"    scope: {'private' if role == 'test' else 'public'}"))
    spec = SPECS[task_id]
    contract = {
        "schema": "bpb-falcon-regression-contract/1", "task_id": task_id,
        "task_version": "0.1-public-validation-stream", "science_profile": PROFILE,
        "kind": "streaming_regression",
        "source": {"repository": "https://github.com/snel-repo/falcon-challenge", "sha": SOURCE_SHA,
                   "dandiset_id": protocol["source"]["dandiset"],
                   "dandiset_version": protocol["source"]["version"],
                   "source_manifest_sha256": ASSET_MANIFEST_SHA,
                   "protocol_sha256": protocol_sha, "exporter_sha256": exporter_sha,
                   "public_export_receipt_sha256": digest(public_receipt),
                   "evaluator_export_receipt_sha256": digest(evaluator_receipt),
                   "source_verification": "selected_http_ranges" if selective else "full_raw_sha256",
                   "full_raw_sha256_verified": not selective},
        "input": {"file": "x.npy", "dtype": "uint8", "shape": ["T", spec["channels"]],
                  "unit": "native spike counts per 20 ms", "model_dtype": "float32"},
        "output": {"file": "y.npy", "dtype": "float64", "shape": ["T", spec["outputs"]],
                   "target": spec["container"], "model_dtype": "float32"},
        "mask": {"file": "mask.npy", "dtype": "bool", "shape": ["T"],
                 "meaning": "native eval_mask; non-scoring bins remain in causal history"},
        "trial_start": {"file": "trial_start.npy", "dtype": "bool", "shape": ["T"],
                        "boundary_before_current_sample": True,
                        "formula": "searchsorted(target_timestamps, trials.start_time)",
                        "terminal_marker_added": False},
        "model_interface": {"module": "model.py", "class": "Model",
                            "reset": "reset() at each source run/file boundary",
                            "forward": f"forward(x: float32[{spec['channels']}], trial_start: bool = False) -> float32[{spec['outputs']}]",
                            "test_time_parameter_updates": False},
        "max_parameters": 10_000_000, "max_numeric_state_elements": 10_000_000,
        "primary_metric": {"id": "R2_variance_weighted", "direction": "maximize",
                           "aggregation": "mask then concatenate same-date runs; variance-weighted R2 per date; equal-weight date mean and population std"},
        "split": {"unit": "recording_date", "train_dates": protocol["split"]["train_dates"],
                  "valid_dates": protocol["split"]["valid_dates"],
                  "test_dates": protocol["split"]["test_dates"],
                  "test_access": "evaluator_only_public_origin"},
        "evaluation_manifests": {role: {key: summaries[role][key] for key in ("sha256", "bytes")}
                                 for role in ("valid", "test")},
        "derived_manifests": summaries, "exported_runs": exported,
        "source_origin_public": True, "official_falcon_score": False, "data_uploaded": False,
        "full_raw_sha256_verified": not selective,
    }
    if selective:
        lock_data = {"datasets": []}
        for role in ("train", "valid", "test"):
            access = "evaluator" if role == "test" else "public"
            scope = "private" if role == "test" else "public"
            lock_data["datasets"].append({
                "name": f"m2-{role}-manifest.json",
                "uri": f"local://{access}/{role}/manifest.json",
                "sha256": summaries[role]["sha256"], "bytes": summaries[role]["bytes"],
                "format": "json", "scope": scope})
            for run in derived[role]["runs"]:
                for name in ARRAYS:
                    info = run["files"][name]
                    lock_data["datasets"].append({
                        "name": f"{run['id']}-{name}",
                        "uri": f"local://{access}/{role}/{info['path']}",
                        "sha256": info["sha256"], "bytes": info["bytes"],
                        "format": "npy", "scope": scope})
        with lock_path.open("x") as out:
            json.dump(lock_data, out, sort_keys=True, indent=2)
            out.write("\n")
    else:
        with lock_path.open("x") as out:
            out.write("\n".join(lock_lines) + "\n")
    with contract_path.open("x") as out:
        json.dump(contract, out, sort_keys=True, indent=2)
        out.write("\n")
    return {"contract": str(contract_path), "data_lock": str(lock_path),
            "raw_assets": len(exported), "roles": summaries}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", choices=tuple(SPECS), required=True)
    parser.add_argument("--derived-root", required=True, type=Path)
    parser.add_argument("--public-receipt", required=True, type=Path)
    parser.add_argument("--evaluator-receipt", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.task_id, args.derived_root, args.public_receipt,
                           args.evaluator_receipt), sort_keys=True))


if __name__ == "__main__":
    main()
