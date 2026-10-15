"""Trusted FALCON H2/B1 export from exact, hashed NWB source assets.

Native field and boundary formulas follow the MIT-licensed upstream
falcon_challenge/dataloaders.py at 770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from pynwb import NWBHDF5IO


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "tasks/intracortical/_preparation/assets.manifest.json"
MANIFEST_SHA = "b83c065c76b71c76c00076e35ab242a426c85dad9cfd7f54b4e05af6c0dc5ce4"
SOURCE_SHA = "770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f"
PROFILE = "bpb-falcon-public-derived-cross-session-zs-v1"
TASKS = {"h2": "falcon-h2-handwriting", "b1": "falcon-b1-birdsong"}
COUNTS = {"h2": {"train": 20, "valid": 1, "test": 5},
          "b1": {"train": 2, "valid": 1, "test": 3}}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def outside_git(path: Path) -> Path:
    path = path.resolve()
    if any((p / ".git").exists() for p in (path, *path.parents)):
        raise ValueError("Source and derived arrays must stay outside Git checkouts")
    return path


def sources(task: str) -> tuple[dict, list[dict]]:
    if digest(MANIFEST) != MANIFEST_SHA:
        raise ValueError("Frozen FALCON asset manifest changed")
    source = json.loads(MANIFEST.read_text())
    protocol = json.loads((ROOT / "tasks/intracortical" / TASKS[task] / "protocol.json").read_text())
    if (source["profile"] != PROFILE or source["upstream_source_sha"] != SOURCE_SHA or
            protocol["profile"] != PROFILE or protocol["source"]["sha"] != SOURCE_SHA):
        raise ValueError("Source or protocol profile changed")
    assets = [item for item in source["assets"] if item["task_id"] == TASKS[task]]
    if len(assets) != sum(COUNTS[task].values()):
        raise ValueError("Incomplete frozen asset inventory")
    for role, count in COUNTS[task].items():
        selected = [item for item in assets if item["role"] == role]
        if (len(selected) != count or
                sorted(item["session_date"] for item in selected) != protocol["split"][f"{role}_dates"] or
                any("minival" in item["path"] for item in selected)):
            raise ValueError(f"{task} {role} source split differs from protocol")
    return protocol, assets


def source_path(root: Path, item: dict, *, content_cache: bool = False) -> Path:
    if content_cache:
        path = (root / item["sha256"] / "data").resolve()
        if not path.is_relative_to(root):
            raise ValueError("Content-cache path escapes root")
        if not path.is_file() or path.stat().st_size != item["size_bytes"] or digest(path) != item["sha256"]:
            raise ValueError(f"Frozen source bytes differ for {item['asset_id']}")
        return path
    relative = Path(item["dandiset_id"]) / item["path"]
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe source path")
    access = "evaluator" if item["role"] == "test" else "public"
    base = (root / access).resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Source path escapes access root")
    if not path.is_file() or path.stat().st_size != item["size_bytes"] or digest(path) != item["sha256"]:
        raise ValueError(f"Frozen source bytes differ for {item['asset_id']}")
    return path


def h2_arrays(path: Path) -> tuple[dict[str, np.ndarray], list[str], dict]:
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        nwb = io.read()
        spikes = nwb.acquisition["binned_spikes"]
        x = np.asarray(spikes.data[:])
        times = np.asarray(spikes.timestamps[:], dtype=np.float64)
        mask = np.asarray(nwb.acquisition["eval_mask"].data[:], dtype=bool)
        trials = nwb.trials.to_dataframe()
        cues = trials["cue"].tolist()
        if x.ndim != 2 or x.shape[1] != 192 or x.dtype != np.float32 or len(x) < 1:
            raise ValueError("H2 native neural matrix changed")
        if times.shape != (len(x),) or mask.shape != (len(x),) or not np.isfinite(x).all():
            raise ValueError("H2 time, mask, or neural input changed")
        gaps = np.diff(times)
        if not np.isfinite(times).all() or np.any(gaps <= 0):
            raise ValueError("H2 timestamps are not increasing")
        # FALCON dataloaders.py returns [diff(time) > 0.021, True].
        end = np.concatenate((gaps > 0.021, [True])).astype(bool)
        if int(end.sum()) != len(cues) or not cues or any(not isinstance(cue, str) or not cue for cue in cues):
            raise ValueError("H2 native time gaps do not match complete sentence trials")
        starts = np.r_[0, np.flatnonzero(end)[:-1] + 1]
        stops = np.flatnonzero(end) + 1
        for start, stop, (_, trial) in zip(starts, stops, trials.iterrows()):
            if (not np.isclose(times[start], trial.start_time, atol=1e-5, rtol=0) or
                    not np.isclose(times[stop - 1], trial.stop_time, atol=1e-5, rtol=0)):
                raise ValueError("H2 native time gaps differ from trial table boundaries")
        if any(not mask[start:stop].any() for start, stop in zip(starts, stops)):
            raise ValueError("H2 contains a trial with no evaluation samples")
        # The native loader returns cues in the same trial-table order.
        return {"x.npy": x, "mask.npy": mask, "trial_end.npy": end}, cues, {
            "trials": len(cues), "input_samples": len(x), "scored_samples": int(mask.sum()),
            "trial_lengths": [int(stop - start) for start, stop in zip(starts, stops)]}


def b1_arrays(path: Path) -> tuple[dict[str, np.ndarray], None, dict]:
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        nwb = io.read()
        series = nwb.acquisition["tx"]
        raw = np.asarray(series.data[:])
        times = np.asarray(series.timestamps[:], dtype=np.float64)
        table = nwb.trials.to_dataframe()
        count = len(table)
        if raw.ndim != 2 or raw.shape[1] != 85 or count < 1 or len(raw) != count * 27000:
            raise ValueError("B1 neural samples do not form 900 ms complete motifs")
        if times.shape != (len(raw),) or not np.isfinite(raw).all() or not np.isin(raw, (0, 1)).all():
            raise ValueError("B1 threshold crossings changed")
        x = np.asarray(raw, dtype=np.uint8).reshape(count, 27000, 85)
        y = np.empty((count, 880, 158), dtype=np.float64)
        mask = np.empty((count, 880, 158), dtype=bool)
        for index, (_, row) in enumerate(table.iterrows()):
            first = index * 27000
            last = first + 27000
            if (not np.isclose(times[first], row.start_time, atol=1/30000, rtol=0) or
                    not np.isclose(times[last - 1], row.stop_time, atol=1/30000, rtol=0) or
                    not np.allclose(np.diff(times[first:last]), 1/30000, atol=1e-8, rtol=0)):
                raise ValueError("B1 neural sample boundaries differ from trial table")
            values = np.asarray(row.spectrogram_values)
            valid = np.asarray(row.spectrogram_eval_mask, dtype=bool)
            if values.shape != (158, 880) or valid.shape != values.shape or not np.isfinite(values).all():
                raise ValueError("B1 native spectrogram shape or values changed")
            y[index] = values.T
            mask[index] = valid.T
            if int(mask[index].sum()) != 700 * 158:
                raise ValueError("B1 native mask does not select 700 time bins")
        return {"x.npy": x, "y.npy": y, "mask.npy": mask}, None, {
            "trials": count, "input_samples": len(raw), "scored_cells": int(mask.sum())}


def save(path: Path, value: np.ndarray | list[str], private: bool) -> dict:
    with path.open("xb") as out:
        if path.suffix == ".npy":
            np.save(out, value, allow_pickle=False)
        else:
            out.write((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    if private:
        os.chmod(path, 0o600)
    return {"path": str(path.relative_to(path.parents[2])), "bytes": path.stat().st_size,
            "sha256": digest(path), **({"shape": list(value.shape), "dtype": value.dtype.name}
                                      if isinstance(value, np.ndarray) else {"count": len(value)})}


def export(task: str, access: str, source_root: Path, output_root: Path,
           *, content_cache: bool = False) -> dict:
    protocol, assets = sources(task)
    source_root = outside_git(source_root)
    output_root = outside_git(output_root)
    if (source_root == output_root or source_root.is_relative_to(output_root) or
            output_root.is_relative_to(source_root)):
        raise ValueError("Raw and derived roots must be separate")
    private = access == "evaluator"
    roles = ("test",) if private else ("train", "valid")
    output_root.mkdir(parents=True, exist_ok=True)
    access_root = output_root / access
    access_root.mkdir(mode=0o700 if private else 0o755, exist_ok=True)
    if private:
        os.chmod(access_root, 0o700)
    summaries, bindings = [], []
    for role in roles:
        role_dir = access_root / role
        role_dir.mkdir(mode=0o700 if private else 0o755, exist_ok=False)
        if private:
            os.chmod(role_dir, 0o700)
        run_dir = role_dir / "runs"
        run_dir.mkdir(mode=0o700 if private else 0o755)
        entries = []
        for index, asset in enumerate(sorted((a for a in assets if a["role"] == role),
                                            key=lambda a: (a["session_date"], a["path"])), 1):
            source = source_path(source_root, asset, content_cache=content_cache)
            arrays, labels, summary = h2_arrays(source) if task == "h2" else b1_arrays(source)
            run_id = f"{task}-{role}-{index:04d}"
            run_path = run_dir / run_id
            run_path.mkdir(mode=0o700 if private else 0o755)
            files = {name: save(run_path / name, value, private) for name, value in arrays.items()}
            if labels is not None:
                files["labels.json"] = save(run_path / "labels.json", labels, private)
            entries.append({"id": run_id, "role": role, "session_id": asset["session_date"],
                            "order": index - 1, "files": files, **summary})
            bindings.append({"id": run_id, "role": role, "date": asset["session_date"],
                             "source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
                             "source_bytes": asset["size_bytes"], "files": files})
        role_manifest = {"schema": f"bpb-{task}-evaluation-data/1", "task_id": TASKS[task],
                         "profile": PROFILE, "role": role, "source_sha": SOURCE_SHA,
                         "source_manifest_sha256": MANIFEST_SHA,
                         "protocol_sha256": digest(ROOT / "tasks/intracortical" / TASKS[task] / "protocol.json"),
                         "exporter_sha256": digest(Path(__file__)), "runs": entries}
        manifest_path = role_dir / "manifest.json"
        with manifest_path.open("x") as out:
            json.dump(role_manifest, out, indent=2, sort_keys=True)
            out.write("\n")
        if private:
            os.chmod(manifest_path, 0o600)
        summaries.append({"role": role, "manifest": str(manifest_path), "sha256": digest(manifest_path),
                          "bytes": manifest_path.stat().st_size, "runs": len(entries),
                          "trials": sum(item["trials"] for item in entries)})
    receipt_dir = output_root / "trusted_receipts"
    receipt_dir.mkdir(mode=0o700, exist_ok=True)
    receipt = receipt_dir / f"{task}-{access}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with receipt.open("x") as out:
        json.dump({"schema": f"bpb-{task}-export-receipt/1", "task_id": TASKS[task],
                   "profile": PROFILE, "access": access, "source_sha": SOURCE_SHA,
                   "source_manifest_sha256": MANIFEST_SHA, "exporter_sha256": digest(Path(__file__)),
                   "protocol_sha256": digest(ROOT / "tasks/intracortical" / TASKS[task] / "protocol.json"),
                   "roles": summaries, "source_bindings": bindings,
                   "test_model_evaluated": False, "data_uploaded": False}, out, indent=2, sort_keys=True)
        out.write("\n")
    os.chmod(receipt, 0o600)
    return {"receipt": str(receipt), "roles": summaries, "test_model_evaluated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=TASKS)
    parser.add_argument("--access", required=True, choices=("public", "evaluator"))
    parser.add_argument("--allow-test-export", action="store_true")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-root", type=Path)
    source.add_argument("--content-cache-root", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    if args.access == "evaluator" and not args.allow_test_export:
        parser.error("Evaluator Test export requires --allow-test-export")
    print(json.dumps(export(args.task, args.access, args.source_root or args.content_cache_root,
                            args.output_root, content_cache=args.content_cache_root is not None), sort_keys=True))


if __name__ == "__main__":
    main()
