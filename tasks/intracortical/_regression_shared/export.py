"""Export pinned FALCON M1-A or M2 NWB files to four stream arrays per run.

The conversion reads Test labels only in a trusted evaluator process. It does
not run a model. Its bin edges and trial markers follow the pinned native loader.
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


HERE = Path(__file__).resolve().parent
DOMAIN = HERE.parent
REPO = DOMAIN.parents[1]
ASSET_MANIFEST = DOMAIN / "_preparation/assets.manifest.json"
ASSET_MANIFEST_SHA = "b83c065c76b71c76c00076e35ab242a426c85dad9cfd7f54b4e05af6c0dc5ce4"
SOURCE_SHA = "770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f"
PROFILE = "bpb-falcon-public-derived-cross-session-zs-v1"
SPECS = {
    "falcon-m1-emg": {"native": "m1", "channels": 64, "outputs": 16, "container": "preprocessed_emg", "timestamp_bin_start": False, "counts": {"train": (3, 3), "valid": (1, 1), "test": (3, 3)}},
    "falcon-m2-finger-velocity": {"native": "m2", "channels": 96, "outputs": 2, "container": "finger_vel", "timestamp_bin_start": True, "counts": {"train": (6, 3), "valid": (1, 1), "test": (6, 4)}},
}
ARRAYS = ("x.npy", "y.npy", "mask.npy", "trial_start.npy")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def outside_git(path: Path) -> Path:
    path = path.resolve()
    if any((ancestor / ".git").exists() for ancestor in (path, *path.parents)):
        raise ValueError("data root must be outside every Git checkout")
    return path


def frozen_sources(task_id: str) -> tuple[dict, dict, list[dict]]:
    if task_id not in SPECS or digest(ASSET_MANIFEST) != ASSET_MANIFEST_SHA:
        raise ValueError("unknown task or changed source manifest")
    task = DOMAIN / task_id
    protocol_path = task / "protocol.json"
    manifest = json.loads(ASSET_MANIFEST.read_text())
    protocol = json.loads(protocol_path.read_text())
    if (manifest["upstream_source_sha"] != SOURCE_SHA or manifest["profile"] != PROFILE
            or protocol["source"]["sha"] != SOURCE_SHA or protocol["profile"] != PROFILE
            or protocol["task_id"] != task_id):
        raise ValueError("source, profile, or task binding changed")
    assets = [asset for asset in manifest["assets"] if asset["task_id"] == task_id]
    if any(asset["dandiset_id"] != protocol["source"]["dandiset"]
           or asset["version"] != protocol["source"]["version"]
           or asset["source_task_id"] != SPECS[task_id]["native"] for asset in assets):
        raise ValueError("source asset DANDI identity differs from protocol")
    for role, counts in SPECS[task_id]["counts"].items():
        chosen = [asset for asset in assets if asset["role"] == role]
        dates = sorted({asset["session_date"] for asset in chosen})
        if ((len(chosen), len(dates)) != counts or dates != protocol["split"][f"{role}_dates"]
                or any("minival" in asset["path"] for asset in chosen)):
            raise ValueError(f"incomplete or changed {task_id} {role} inventory")
    return manifest, protocol, assets


def source_path(source_root: Path, asset: dict) -> Path:
    access = "evaluator" if asset["role"] == "test" else "public"
    relative = Path(asset["dandiset_id"]) / asset["path"]
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe asset path")
    access_root = (source_root / access).resolve()
    path = (access_root / relative).resolve()
    if not path.is_relative_to(access_root):
        raise ValueError("asset path escapes role root")
    return path


def bin_units(units, timestamps: np.ndarray, *, is_start: bool) -> np.ndarray:
    """Match pinned dataloaders.bin_units, including its discontinuity mask."""
    ends = timestamps + 0.02 if is_start else timestamps.copy()
    gaps = np.diff(ends)
    if (gaps <= 0).any():
        raise ValueError("non-increasing native timestamps")
    if not np.allclose(gaps, 0.02):
        new_ends = [ends[0]]
        keep = [True]
        for index, gap in enumerate(gaps):
            if not np.isclose(gap, 0.02) and gap > 0.02:
                new_ends.extend((ends[index + 1] - 0.02, ends[index + 1]))
                keep.extend((False, True))
            else:
                new_ends.append(ends[index + 1])
                keep.append(True)
        ends = np.asarray(new_ends)
        keep = np.asarray(keep, dtype=bool)
    else:
        keep = np.ones(len(ends), dtype=bool)
    edges = np.concatenate(([ends[0] - 0.02], ends))
    x = np.empty((len(timestamps), len(units)), dtype=np.uint8)
    for channel, (_, unit) in enumerate(units.iterrows()):
        counts = np.histogram(unit.spike_times, bins=edges)[0][keep]
        if len(counts) != len(timestamps) or np.any(counts > 255):
            raise ValueError("native spike bin count or length invalid")
        x[:, channel] = counts.astype(np.uint8)
    return x


def convert_nwb(nwb, spec: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    units = nwb.units.to_dataframe()
    series = nwb.acquisition[spec["container"]]
    names = list(series.time_series)
    if len(units) != spec["channels"] or len(names) != spec["outputs"]:
        raise ValueError("native channel or target width changed")
    data, all_timestamps = [], []
    for name in names:
        item = series.get_timeseries(name)
        data.append(np.asarray(item.data[:], dtype=np.float64))
        all_timestamps.append(np.asarray(item.timestamps[:], dtype=np.float64))
    timestamps = all_timestamps[0] if not spec["timestamp_bin_start"] else all_timestamps[-1]
    if (any(values.shape != timestamps.shape for values in data)
            or any(not np.array_equal(stamps, timestamps) for stamps in all_timestamps)):
        raise ValueError("target series timestamps disagree")
    y = np.stack(data, axis=1)
    mask = np.asarray(nwb.acquisition["eval_mask"].data[:], dtype=bool)
    if (timestamps.ndim != 1 or len(timestamps) < 2 or mask.shape != timestamps.shape
            or not np.isfinite(timestamps).all() or not np.isfinite(y).all()
            or not np.any(mask) or nwb.trials is None):
        raise ValueError("target, timestamp, trial, or mask invalid")
    x = bin_units(units, timestamps, is_start=spec["timestamp_bin_start"])
    trial_starts = nwb.trials.to_dataframe().start_time.to_numpy(dtype=np.float64)
    switch = np.searchsorted(timestamps, trial_starts)
    if not np.isfinite(trial_starts).all() or np.any(switch >= len(timestamps)):
        raise ValueError("trial starts outside native timestamp range")
    trial_start = np.zeros(len(timestamps), dtype=bool)
    trial_start[switch] = True
    return x, y, mask, trial_start



def convert(path: Path, spec: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        return convert_nwb(io.read(), spec)

def save_array(path: Path, array: np.ndarray, test: bool, role_root: Path) -> dict:
    with path.open("xb") as out:
        np.save(out, array, allow_pickle=False)
    if test:
        path.chmod(0o600)
    return {"path": str(path.relative_to(role_root)), "shape": list(array.shape),
            "dtype": array.dtype.name, "sha256": digest(path), "bytes": path.stat().st_size}


def export(task_id: str, access: str, source_root: Path, output_root: Path) -> dict:
    _, protocol, assets = frozen_sources(task_id)
    spec = SPECS[task_id]
    roles = ("train", "valid") if access == "public" else ("test",)
    output_root.mkdir(parents=True, exist_ok=True)
    access_root = output_root / access
    access_root.mkdir(exist_ok=True, mode=0o700 if access == "evaluator" else 0o755)
    if access == "evaluator":
        access_root.chmod(0o700)
    summaries, bindings = [], []
    for role in roles:
        selected = sorted((asset for asset in assets if asset["role"] == role),
                          key=lambda asset: (asset["session_date"], asset["path"]))
        role_root = access_root / role
        role_root.mkdir(mode=0o700 if role == "test" else 0o755)
        (role_root / "runs").mkdir(mode=0o700 if role == "test" else 0o755)
        runs = []
        for index, asset in enumerate(selected, 1):
            raw = source_path(source_root, asset)
            if not raw.is_file() or raw.stat().st_size != asset["size_bytes"] or digest(raw) != asset["sha256"]:
                raise ValueError(f"source asset incomplete or changed: {asset['asset_id']}")
            x, y, mask, trial_start = convert(raw, spec)
            run_id = f"{spec['native']}-{role}-{index:04d}"
            run_root = role_root / "runs" / run_id
            run_root.mkdir(mode=0o700 if role == "test" else 0o755)
            files = {name: save_array(run_root / name, array, role == "test", role_root)
                     for name, array in zip(ARRAYS, (x, y, mask, trial_start))}
            runs.append({"id": run_id, "role": role, "session_id": asset["session_date"],
                         "order": index - 1, "files": files, "valid_timesteps": int(mask.sum()),
                         "trial_starts": int(trial_start.sum())})
            bindings.append({"id": run_id, "role": role, "date": asset["session_date"],
                             "source_asset_id": asset["asset_id"], "source_sha256": asset["sha256"],
                             "source_bytes": asset["size_bytes"], "files": files})
            print(f"exported {run_id} T={len(x)} valid={mask.sum()}", flush=True)
        role_manifest = {"schema": "bpb-falcon-regression-data/1", "task_id": task_id,
                         "profile": PROFILE, "role": role, "source_sha": SOURCE_SHA,
                         "source_manifest_sha256": ASSET_MANIFEST_SHA,
                         "protocol_sha256": digest(DOMAIN / task_id / "protocol.json"),
                         "exporter_sha256": digest(Path(__file__)),
                         "boundary_semantics": "native searchsorted(trial.start_time) on target timestamps",
                         "runs": runs}
        manifest_path = role_root / "manifest.json"
        with manifest_path.open("x") as out:
            json.dump(role_manifest, out, sort_keys=True, indent=2)
            out.write("\n")
        if role == "test":
            manifest_path.chmod(0o600)
        summaries.append({"role": role, "manifest_path": str(manifest_path),
                          "manifest_sha256": digest(manifest_path), "runs": len(runs),
                          "session_count": len({run["session_id"] for run in runs})})
    receipt_root = output_root / "trusted_receipts"
    receipt_root.mkdir(exist_ok=True, mode=0o700)
    receipt_root.chmod(0o700)
    receipt_path = receipt_root / f"{spec['native']}-{access}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    receipt = {"schema": "bpb-falcon-regression-export/1", "task_id": task_id,
               "access": access, "profile": PROFILE, "source_manifest_sha256": ASSET_MANIFEST_SHA,
               "protocol_sha256": digest(DOMAIN / task_id / "protocol.json"),
               "exporter_sha256": digest(Path(__file__)), "source_sha": SOURCE_SHA,
               "created_utc": datetime.now(timezone.utc).isoformat(), "roles": summaries,
               "source_bindings": bindings, "test_model_evaluated": False, "data_uploaded": False}
    with receipt_path.open("x") as out:
        json.dump(receipt, out, sort_keys=True, indent=2)
        out.write("\n")
    receipt_path.chmod(0o600)
    return {"receipt": str(receipt_path), "roles": summaries, "test_model_evaluated": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True, choices=tuple(SPECS))
    parser.add_argument("--access", required=True, choices=("public", "evaluator"))
    parser.add_argument("--allow-test-export", action="store_true")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    if args.access == "evaluator" and not args.allow_test_export:
        parser.error("evaluator conversion requires --allow-test-export")
    source = outside_git(args.source_root)
    output = outside_git(args.output_root)
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        parser.error("raw and derived roots must be separate")
    print(json.dumps(export(args.task_id, args.access, source, output), sort_keys=True))


if __name__ == "__main__":
    main()
