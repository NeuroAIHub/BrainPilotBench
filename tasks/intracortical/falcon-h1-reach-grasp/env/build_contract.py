"""Write H1 data.lock and contract.json from verified source and derived manifests.

This is a one-time, maintainer-only mechanical freeze. It refuses to overwrite
either tracked file and never opens NWB target arrays or runs a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from export_h1 import (ASSET_MANIFEST, ASSET_MANIFEST_SHA, EXPECTED, PROFILE,
                       PROTOCOL, PROTOCOL_SHA, SOURCE_SHA, TASK_DIR, load_sources,
                       sha256_file)


def checked_manifest(path: Path, role: str, exporter_sha: str) -> tuple[dict, dict]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if (manifest.get("schema") != "bpb-h1-evaluation-data/1" or manifest.get("profile") != PROFILE
            or manifest.get("role") != role or manifest.get("source_sha") != SOURCE_SHA
            or manifest.get("source_manifest_sha256") != ASSET_MANIFEST_SHA
            or manifest.get("protocol_sha256") != PROTOCOL_SHA
            or manifest.get("exporter_sha256") != exporter_sha):
        raise ValueError(f"Derived {role} manifest provenance mismatch")
    runs = manifest["runs"]
    if (len(runs), len({run["session_id"] for run in runs})) != EXPECTED[role]:
        raise ValueError(f"Derived {role} run/date counts mismatch")
    for run in runs:
        if run["role"] != role or set(run["files"]) != {"x.npy", "y.npy", "mask.npy", "trial_start.npy"}:
            raise ValueError(f"Invalid run fields for {run['id']}")
        t = run["files"]["x.npy"]["shape"][0]
        expected = {"x.npy": ([t, 176], "uint8"), "y.npy": ([t, 7], "float64"),
                    "mask.npy": ([t], "bool"), "trial_start.npy": ([t], "bool")}
        for name, file in run["files"].items():
            if (file["shape"], file["dtype"]) != expected[name]:
                raise ValueError(f"Array shape/dtype mismatch for {run['id']}/{name}")
            relative = Path(file["path"])
            actual = (path.parent / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or not actual.is_relative_to(path.parent.resolve()):
                raise ValueError("Unsafe array path")
            if actual.stat().st_size != file["bytes"] or sha256_file(actual) != file["sha256"]:
                raise ValueError(f"Array digest mismatch for {run['id']}/{name}")
    return manifest, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                      "runs": len(runs), "sessions": EXPECTED[role][1]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derived-root", required=True, type=Path)
    parser.add_argument("--public-receipt", required=True, type=Path)
    parser.add_argument("--evaluator-receipt", required=True, type=Path)
    args = parser.parse_args()
    contract_path = TASK_DIR / "contract.json"
    lock_path = TASK_DIR / "data.lock"
    if contract_path.exists() or lock_path.exists():
        parser.error("contract.json or data.lock already exists; freeze is immutable")
    source_manifest, protocol = load_sources()
    root = args.derived_root.resolve()
    exporter_sha = sha256_file(TASK_DIR / "env/export_h1.py")
    role_paths = {"train": root / "public/train/manifest.json",
                  "valid": root / "public/valid/manifest.json",
                  "test": root / "evaluator/test/manifest.json"}
    derived = {}
    summaries = {}
    for role, path in role_paths.items():
        derived[role], summaries[role] = checked_manifest(path, role, exporter_sha)
    receipts = [json.loads(args.public_receipt.read_text()), json.loads(args.evaluator_receipt.read_text())]
    if [receipt["access"] for receipt in receipts] != ["public", "evaluator"]:
        raise ValueError("Wrong trusted receipts")
    source_by_id = {asset["asset_id"]: asset for asset in source_manifest["assets"]
                    if asset["task_id"] == "falcon-h1-reach-grasp"}
    bindings = {}
    for receipt in receipts:
        if (receipt["schema"] != "bpb-h1-export-receipt/1"
                or receipt["source_manifest_sha256"] != ASSET_MANIFEST_SHA
                or receipt["protocol_sha256"] != PROTOCOL_SHA
                or receipt["exporter_sha256"] != exporter_sha):
            raise ValueError("Trusted export receipt mismatch")
        for binding in receipt["source_bindings"]:
            if binding["id"] in bindings:
                raise ValueError("Duplicate run binding")
            asset = source_by_id[binding["source_asset_id"]]
            if (binding["role"], binding["source_sha256"], binding["source_bytes"]) != (asset["role"], asset["sha256"], asset["size_bytes"]):
                raise ValueError("Run/source binding mismatch")
            bindings[binding["id"]] = asset
    if len(bindings) != 27:
        raise ValueError("Not all H1 source assets are bound")
    exported_runs = []
    lock_lines = ["# Frozen FALCON H1 public-origin NWB assets; Test is evaluator-only.",
                  f"# Source {SOURCE_SHA}; source manifest SHA-256 {ASSET_MANIFEST_SHA}.", "datasets:"]
    for role in ("train", "valid", "test"):
        for run in derived[role]["runs"]:
            asset = bindings[run["id"]]
            if asset["role"] != role or asset["session_date"] != run["session_id"]:
                raise ValueError("Derived run/source date or role mismatch")
            exported_runs.append({"id": run["id"], "role": role, "session_id": run["session_id"],
                                  "source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
                                  "source_bytes": asset["size_bytes"], "files": run["files"]})
            lock_lines.extend([
                f"  - name: {run['id']}.nwb",
                f"    uri: https://api.dandiarchive.org/api/assets/{asset['asset_id']}/download/",
                f"    sha256: {asset['sha256']}",
                f"    bytes: {asset['size_bytes']}",
                "    format: nwb",
                f"    scope: {'private' if role == 'test' else 'public'}",
            ])
    contract = {
        "schema": "bpb-h1-contract/1",
        "task_id": "falcon-h1-reach-grasp",
        "task_version": "0.1-public-validation-stream",
        "science_profile": PROFILE,
        "kind": "streaming_regression",
        "source": {"repository": "https://github.com/snel-repo/falcon-challenge",
                   "sha": SOURCE_SHA, "dandiset_id": "000954", "dandiset_version": "draft",
                   "source_manifest_sha256": ASSET_MANIFEST_SHA,
                   "protocol_sha256": PROTOCOL_SHA, "exporter_sha256": exporter_sha,
                   "public_export_receipt_sha256": sha256_file(args.public_receipt),
                   "evaluator_export_receipt_sha256": sha256_file(args.evaluator_receipt)},
        "input": {"file": "x.npy", "dtype": "uint8", "shape": ["T", 176],
                  "unit": "spike_counts_per_preceding_20ms", "model_dtype": "float32"},
        "output": {"file": "y.npy", "dtype": "float64", "shape": ["T", 7],
                   "target": "OpenLoopKinematicsVelocity", "model_dtype": "float32"},
        "mask": {"file": "mask.npy", "dtype": "bool", "shape": ["T"],
                 "meaning": "native eval_mask; non-scoring timesteps retained for causal history"},
        "trial_start": {"file": "trial_start.npy", "dtype": "bool", "shape": ["T"],
                        "boundary_before_current_sample": True,
                        "formula": "[False] + (diff(TrialNum) > 0)",
                        "terminal_marker_added": False},
        "model_interface": {"module": "model.py", "class": "Model", "reset": "reset() at each run/file boundary",
                            "forward": "forward(x: float32[176], trial_start: bool = False) -> float32[7]",
                            "test_time_parameter_updates": False},
        "max_parameters": 10_000_000,
        "max_numeric_state_elements": 10_000_000,
        "primary_metric": {"id": "R2_variance_weighted", "direction": "maximize",
                           "aggregation": "mask then concatenate same-date sets; variance-weighted R2 per date; equal-weight date mean and population std"},
        "split": {"unit": "recording_date", "train_dates": protocol["split"]["train_dates"],
                  "valid_dates": protocol["split"]["valid_dates"], "test_dates": protocol["split"]["test_dates"],
                  "test_access": "evaluator_only_public_origin"},
        "evaluation_manifests": {"valid": {k: summaries["valid"][k] for k in ("sha256", "bytes")},
                                 "test": {k: summaries["test"][k] for k in ("sha256", "bytes")}},
        "derived_manifests": summaries,
        "exported_runs": exported_runs,
        "source_origin_public": True,
        "official_falcon_score": False,
        "data_uploaded": False,
    }
    with lock_path.open("x") as output:
        output.write("\n".join(lock_lines) + "\n")
    with contract_path.open("x") as output:
        json.dump(contract, output, sort_keys=True, indent=2)
        output.write("\n")
    print(json.dumps({"contract": str(contract_path), "data_lock": str(lock_path),
                      "raw_assets": len(exported_runs), "roles": summaries}, sort_keys=True))


if __name__ == "__main__":
    main()
