"""Freeze H2/B1 derived manifests and source links into a task contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from export import COUNTS, MANIFEST, MANIFEST_SHA, PROFILE, ROOT, SOURCE_SHA, TASKS, digest, sources


FILES = {"h2": {"x.npy", "mask.npy", "trial_end.npy", "labels.json"},
         "b1": {"x.npy", "y.npy", "mask.npy"}}


def verify_manifest(path: Path, task: str, role: str) -> tuple[dict, dict]:
    value = json.loads(path.read_text())
    task_dir = ROOT / "tasks/intracortical" / TASKS[task]
    if (value.get("schema") != f"bpb-{task}-evaluation-data/1" or
            value.get("task_id") != TASKS[task] or value.get("profile") != PROFILE or
            value.get("role") != role or value.get("source_sha") != SOURCE_SHA or
            value.get("source_manifest_sha256") != MANIFEST_SHA or
            value.get("protocol_sha256") != digest(task_dir / "protocol.json") or
            value.get("exporter_sha256") != digest(Path(__file__).with_name("export.py"))):
        raise ValueError(f"{task} {role} manifest provenance differs")
    runs = value["runs"]
    if len(runs) != COUNTS[task][role] or len({r["session_id"] for r in runs}) != len(runs):
        raise ValueError("Derived runs do not cover the frozen dates")
    for run in runs:
        if run["role"] != role or set(run["files"]) != FILES[task] or run["trials"] < 1:
            raise ValueError("Derived run shape or role differs")
        for name, metadata in run["files"].items():
            relative = Path(metadata["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe array relative path")
            file = (path.parent / relative).resolve()
            if not file.is_relative_to(path.parent.resolve()) or file.stat().st_size != metadata["bytes"] or digest(file) != metadata["sha256"]:
                raise ValueError("Derived file differs from manifest")
            if name.endswith(".npy"):
                arr = np.load(file, mmap_mode="r", allow_pickle=False)
                if list(arr.shape) != metadata["shape"] or arr.dtype.name != metadata["dtype"]:
                    raise ValueError("Derived array header differs")
            else:
                labels = json.loads(file.read_text())
                if not isinstance(labels, list) or len(labels) != metadata["count"]:
                    raise ValueError("Derived H2 label count differs")
        if task == "h2":
            x = run["files"]["x.npy"]
            if (x["shape"][1:] != [192] or x["dtype"] != "float32" or
                    run["files"]["mask.npy"]["shape"] != [x["shape"][0]] or
                    run["files"]["mask.npy"]["dtype"] != "bool" or
                    run["files"]["trial_end.npy"]["shape"] != [x["shape"][0]] or
                    run["files"]["trial_end.npy"]["dtype"] != "bool" or
                    run["files"]["labels.json"]["count"] != run["trials"]):
                raise ValueError("H2 trial shape differs")
        else:
            x = run["files"]["x.npy"]
            if (x["shape"] != [run["trials"], 27000, 85] or x["dtype"] != "uint8" or
                    run["files"]["y.npy"]["shape"] != [run["trials"], 880, 158] or
                    run["files"]["y.npy"]["dtype"] != "float64" or
                    run["files"]["mask.npy"]["shape"] != [run["trials"], 880, 158] or
                    run["files"]["mask.npy"]["dtype"] != "bool"):
                raise ValueError("B1 motif shape differs")
    return value, {"sha256": digest(path), "bytes": path.stat().st_size,
                   "runs": len(runs), "sessions": len({r["session_id"] for r in runs}),
                   "trials": sum(r["trials"] for r in runs)}


def freeze(task: str, derived: Path, public_receipt: Path, evaluator_receipt: Path) -> dict:
    protocol, assets = sources(task)
    task_dir = ROOT / "tasks/intracortical" / TASKS[task]
    target = task_dir / "contract.json"
    lock = task_dir / "data.lock"
    if target.exists() or lock.exists():
        raise ValueError("Contract and lock are immutable after first freeze")
    manifests, summaries = {}, {}
    for role in ("train", "valid", "test"):
        access = "evaluator" if role == "test" else "public"
        manifests[role], summaries[role] = verify_manifest(derived / access / role / "manifest.json", task, role)
    receipts = [json.loads(p.read_text()) for p in (public_receipt, evaluator_receipt)]
    if [r["access"] for r in receipts] != ["public", "evaluator"]:
        raise ValueError("Receipt access roles differ")
    source_by_id = {asset["asset_id"]: asset for asset in assets}
    bindings = {}
    for receipt in receipts:
        if (receipt["schema"] != f"bpb-{task}-export-receipt/1" or
                receipt["task_id"] != TASKS[task] or receipt["profile"] != PROFILE or
                receipt["source_manifest_sha256"] != MANIFEST_SHA or
                receipt["exporter_sha256"] != digest(Path(__file__).with_name("export.py")) or
                receipt["protocol_sha256"] != digest(task_dir / "protocol.json")):
            raise ValueError("Trusted export receipt differs")
        for binding in receipt["source_bindings"]:
            if binding["id"] in bindings:
                raise ValueError("Duplicate derived source binding")
            asset = source_by_id[binding["source_asset_id"]]
            if (binding["role"], binding["date"], binding["source_sha256"], binding["source_bytes"]) != (
                    asset["role"], asset["session_date"], asset["sha256"], asset["size_bytes"]):
                raise ValueError("Derived source binding differs")
            bindings[binding["id"]] = asset
    if len(bindings) != len(assets):
        raise ValueError("Incomplete source bindings")
    exported = []
    lock_lines = [f"# Frozen FALCON {task.upper()} public-origin NWB assets; Test is evaluator-only.",
                  f"# Source {SOURCE_SHA}; manifest SHA-256 {MANIFEST_SHA}.", "datasets:"]
    for role in ("train", "valid", "test"):
        for run in manifests[role]["runs"]:
            asset = bindings[run["id"]]
            if asset["role"] != role or asset["session_date"] != run["session_id"]:
                raise ValueError("Derived run date/role differs from source")
            exported.append({"id": run["id"], "role": role, "session_id": run["session_id"],
                             "source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
                             "source_bytes": asset["size_bytes"], "files": run["files"], "trials": run["trials"]})
            lock_lines += [f"  - name: {run['id']}.nwb",
                           f"    uri: https://api.dandiarchive.org/api/assets/{asset['asset_id']}/download/",
                           f"    sha256: {asset['sha256']}", f"    bytes: {asset['size_bytes']}",
                           "    format: nwb", f"    scope: {'private' if role == 'test' else 'public'}"]
    contract = {"schema": "bpb-falcon-sequence-contract/1", "task_id": TASKS[task],
                "task_version": ("0.1-public-validation-stream" if task == "h2" else "0.1-public-validation-motif"),
                "science_profile": PROFILE, "kind": ("streaming_sentence" if task == "h2" else "motif_spectrogram"),
                "source": {"repository": "https://github.com/snel-repo/falcon-challenge", "sha": SOURCE_SHA,
                           "dandiset_id": protocol["source"]["dandiset"],
                           "dandiset_version": protocol["source"]["version"],
                           "source_manifest_sha256": MANIFEST_SHA,
                           "protocol_sha256": digest(task_dir / "protocol.json"),
                           "exporter_sha256": digest(Path(__file__).with_name("export.py")),
                           "public_export_receipt_sha256": digest(public_receipt),
                           "evaluator_export_receipt_sha256": digest(evaluator_receipt)},
                "split": protocol["split"], "derived_manifests": summaries,
                "input": ({"file": "x.npy", "dtype": "float32", "shape": ["T", 192],
                           "unit": "spike_count_per_20ms", "model_delivery": "one_current_bin"}
                          if task == "h2" else
                          {"file": "x.npy", "dtype": "uint8", "shape": ["motifs", 27000, 85],
                           "unit": "threshold_crossing_at_30kHz", "model_delivery": "one_complete_motif"}),
                "output": ({"file": "labels.json", "dtype": "string", "shape": ["complete_trials"],
                            "trial_end_file": "trial_end.npy"}
                           if task == "h2" else
                           {"file": "y.npy", "dtype": "float64", "shape": ["motifs", 880, 158],
                            "mask_file": "mask.npy", "model_dtype": "float32"}),
                "evaluation_manifests": {role: {k: summaries[role][k] for k in ("sha256", "bytes")}
                                         for role in ("valid", "test")},
                "exported_runs": exported, "max_parameters": 10_000_000,
                "max_numeric_state_elements": 10_000_000,
                "max_registered_tensor_elements": 10_000_000,
                "model_interface": ({"module": "model.py", "class": "Model", "reset": "reset() at each file",
                                     "observe": "observe(x: float32[192], trial_start: bool) -> None, one current native-mask-selected 20 ms bin",
                                     "finish_trial": "finish_trial() -> str, exactly once per complete trial"}
                                    if task == "h2" else
                                    {"module": "model.py", "class": "Model", "forward": "forward(neural: float32[27000,85]) -> float32[880,158], one complete motif"}),
                "primary_metric": protocol["metric"], "source_origin_public": True,
                "official_falcon_score": False, "data_uploaded": False}
    with lock.open("x") as out:
        out.write("\n".join(lock_lines) + "\n")
    with target.open("x") as out:
        json.dump(contract, out, indent=2, sort_keys=True)
        out.write("\n")
    return {"contract": str(target), "lock": str(lock), "roles": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=TASKS)
    parser.add_argument("--derived-root", required=True, type=Path)
    parser.add_argument("--public-receipt", required=True, type=Path)
    parser.add_argument("--evaluator-receipt", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(freeze(args.task, args.derived_root, args.public_receipt, args.evaluator_receipt), sort_keys=True))


if __name__ == "__main__":
    main()
