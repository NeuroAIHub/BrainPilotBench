"""Trusted, source-bound H1 NWB exporter for BPB's derived cross-session profile.

Use --access public for the 13 held-in Train/Valid assets. Use the separate
--access evaluator --allow-test-export command for the 14 held-out calibration
assets. The latter conversion reads Test target arrays only in this trusted
process; it never runs a Test model or prints their values. No output is
written to Git or uploaded. Upstream NWB field/binner semantics follow the
MIT-licensed FALCON dataloaders.py at source 770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f.
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


TASK_DIR = Path(__file__).resolve().parent.parent
REPO = TASK_DIR.parents[2]
ASSET_MANIFEST = REPO / "tasks/intracortical/_preparation/assets.manifest.json"
PROTOCOL = TASK_DIR / "protocol.json"
PROFILE = "bpb-falcon-public-derived-cross-session-zs-v1"
SOURCE_SHA = "770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f"
ASSET_MANIFEST_SHA = "b83c065c76b71c76c00076e35ab242a426c85dad9cfd7f54b4e05af6c0dc5ce4"
PROTOCOL_SHA = "bb2c05bd00872bb49ba40f39a19df3f30e9a6b07414ba5f1c432bbc8c138af5e"
EXPECTED = {"train": (11, 5), "valid": (2, 1), "test": (14, 7)}
ARRAY_NAMES = ("x.npy", "y.npy", "mask.npy", "trial_start.npy")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_external(path: Path) -> Path:
    path = path.resolve()
    for ancestor in (path, *path.parents):
        if (ancestor / ".git").exists():
            raise ValueError("NWB and derived arrays must remain outside every Git checkout")
    return path


def load_sources() -> tuple[dict, dict]:
    if sha256_file(ASSET_MANIFEST) != ASSET_MANIFEST_SHA or sha256_file(PROTOCOL) != PROTOCOL_SHA:
        raise ValueError("Frozen manifest or H1 protocol SHA changed")
    manifest = json.loads(ASSET_MANIFEST.read_text())
    protocol = json.loads(PROTOCOL.read_text())
    if manifest["schema"] != "bpb-falcon-public-asset-manifest/1" or manifest["profile"] != PROFILE:
        raise ValueError("Wrong source manifest profile")
    if manifest["upstream_source_sha"] != SOURCE_SHA or protocol["source"]["sha"] != SOURCE_SHA:
        raise ValueError("Wrong upstream FALCON source")
    if protocol["profile"] != PROFILE or protocol["task_id"] != "falcon-h1-reach-grasp":
        raise ValueError("Wrong task protocol")
    assets = [a for a in manifest["assets"] if a["task_id"] == "falcon-h1-reach-grasp"]
    if len(assets) != 27:
        raise ValueError("H1 source inventory is incomplete")
    for role in EXPECTED:
        chosen = [a for a in assets if a["role"] == role]
        dates = {a["session_date"] for a in chosen}
        if (len(chosen), len(dates)) != EXPECTED[role] or sorted(dates) != protocol["split"][f"{role}_dates"]:
            raise ValueError(f"H1 {role} inventory does not match protocol")
        if any("minival" in a["path"] for a in chosen):
            raise ValueError("Duplicate minival is forbidden")
    return manifest, protocol


def source_path(source_root: Path | None, cache_root: Path | None, asset: dict) -> Path:
    if cache_root is not None:
        # Matches BPB's content cache: <cacheRoot>/<sha256>/data. The SHA is
        # verified again before any NWB file is opened.
        root = cache_root.resolve()
        path = (root / asset["sha256"] / "data").resolve()
        if not path.is_relative_to(root):
            raise ValueError("Content-cache path escapes its root")
        return path
    assert source_root is not None
    access = "evaluator" if asset["role"] == "test" else "public"
    relative = Path(asset["dandiset_id"]) / asset["path"]
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe source path")
    root = (source_root / access).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Source path escapes its access root")
    return path


def verify_source(path: Path, asset: dict) -> None:
    if not path.is_file() or path.stat().st_size != asset["size_bytes"]:
        raise ValueError(f"Missing or changed source asset {asset['asset_id']}")
    if sha256_file(path) != asset["sha256"]:
        raise ValueError(f"Source SHA-256 mismatch for {asset['asset_id']}")


def convert_nwb(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        nwb = io.read()
        units = nwb.units.to_dataframe()
        y = np.asarray(nwb.acquisition["OpenLoopKinematicsVelocity"].data[:], dtype=np.float64)
        mask = np.asarray(nwb.acquisition["eval_mask"].data[:], dtype=bool)
        trial_num = np.asarray(nwb.acquisition["TrialNum"].data[:])
        clock = nwb.acquisition["OpenLoopKinematics"]
        if len(units) != 176 or y.ndim != 2 or y.shape[1] != 7 or len(y) < 2:
            raise ValueError("Native H1 channel or target dimensions changed")
        if mask.shape != (len(y),) or trial_num.shape != (len(y),):
            raise ValueError("Native H1 mask or TrialNum length changed")
        if not np.isfinite(y).all() or not np.isfinite(trial_num).all():
            raise ValueError("Non-finite target or TrialNum")
        if not np.isclose(clock.rate, 0.02, rtol=0, atol=1e-8):
            raise ValueError("Native H1 clock is not 20 ms")
        timestamps = clock.offset + np.arange(len(y), dtype=np.float64) * clock.rate
        if not np.isfinite(timestamps).all():
            raise ValueError("Non-finite H1 clock")
        edges = np.concatenate(([timestamps[0] - 0.02], timestamps))
        x = np.empty((len(y), 176), dtype=np.uint8)
        for channel, (_, unit) in enumerate(units.iterrows()):
            count, _ = np.histogram(unit.spike_times, bins=edges)
            if np.any(count > np.iinfo(np.uint8).max):
                raise ValueError("Spike count exceeds native uint8 representation")
            x[:, channel] = count.astype(np.uint8)
        # FALCON dataloaders.py: np.concatenate([[False], np.diff(trial_num)>0]).
        # True is at the first sample of the new trial, not the previous end.
        trial_start = np.concatenate(([False], np.diff(trial_num) > 0)).astype(bool)
        return x, y, mask, trial_start


def save_array(path: Path, array: np.ndarray, role: str) -> dict:
    with path.open("xb") as output:
        np.save(output, array, allow_pickle=False)
    if role == "test":
        os.chmod(path, 0o600)
    return {"path": str(path.relative_to(path.parents[2])), "shape": list(array.shape),
            "dtype": array.dtype.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def export_role(source_root: Path | None, cache_root: Path | None, output_root: Path, role: str, assets: list[dict], session_ids: dict[str, str]) -> tuple[dict, list[dict]]:
    access = "evaluator" if role == "test" else "public"
    role_root = output_root / access / role
    role_root.mkdir(parents=True, exist_ok=False, mode=0o700 if role == "test" else 0o755)
    if role == "test":
        os.chmod(role_root, 0o700)
    runs_root = role_root / "runs"
    runs_root.mkdir(mode=0o700 if role == "test" else 0o755)
    entries, trusted = [], []
    for index, asset in enumerate(sorted(assets, key=lambda a: (a["session_date"], a["path"])), 1):
        source = source_path(source_root, cache_root, asset)
        verify_source(source, asset)
        x, y, mask, trial_start = convert_nwb(source)
        run_id = f"h1-{role}-{index:04d}"
        run_root = runs_root / run_id
        run_root.mkdir(mode=0o700 if role == "test" else 0o755)
        arrays = dict(zip(ARRAY_NAMES, (x, y, mask, trial_start)))
        files = {name: save_array(run_root / name, array, role) for name, array in arrays.items()}
        # Public-facing run entries contain no raw source path or asset ID.
        entries.append({"id": run_id, "role": role, "session_id": session_ids[asset["session_date"]],
                        "order": index - 1, "files": files,
                        "valid_timesteps": int(mask.sum()), "trial_starts": int(trial_start.sum())})
        trusted.append({"id": run_id, "role": role, "date": asset["session_date"],
                        "source_asset_id": asset["asset_id"], "source_path": str(source),
                        "source_sha256": asset["sha256"], "source_bytes": asset["size_bytes"],
                        "files": files})
    role_manifest = {
        "schema": "bpb-h1-evaluation-data/1",
        "profile": PROFILE,
        "role": role,
        "source_sha": SOURCE_SHA,
        "source_manifest_sha256": ASSET_MANIFEST_SHA,
        "protocol_sha256": PROTOCOL_SHA,
        "exporter_sha256": sha256_file(Path(__file__)),
        "boundary_semantics": "trial_start[t] is true at the first sample of a new trial; no synthetic last-sample marker",
        "runs": entries,
    }
    manifest_path = role_root / "manifest.json"
    with manifest_path.open("x") as output:
        json.dump(role_manifest, output, sort_keys=True, indent=2)
        output.write("\n")
    if role == "test":
        os.chmod(manifest_path, 0o600)
    return {"role": role, "manifest_path": str(manifest_path), "manifest_sha256": sha256_file(manifest_path),
            "runs": len(entries), "session_count": len({a["session_date"] for a in assets})}, trusted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access", required=True, choices=("public", "evaluator"))
    parser.add_argument("--allow-test-export", action="store_true", help="Required with evaluator access")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-root", type=Path, help="Exact DANDI tree with separate public/evaluator roots")
    source.add_argument("--content-cache-root", type=Path, help="BPB cache root containing <sha256>/data")
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    if args.access == "evaluator" and not args.allow_test_export:
        parser.error("Evaluator conversion requires --allow-test-export")
    source_root = safe_external(args.source_root) if args.source_root else None
    cache_root = safe_external(args.content_cache_root) if args.content_cache_root else None
    output_root = safe_external(args.output_root)
    actual_source_root = source_root or cache_root
    assert actual_source_root is not None
    if actual_source_root == output_root or actual_source_root.is_relative_to(output_root) or output_root.is_relative_to(actual_source_root):
        raise ValueError("Raw and derived roots must be separate")
    manifest, _ = load_sources()
    assets = [a for a in manifest["assets"] if a["task_id"] == "falcon-h1-reach-grasp"]
    all_dates = sorted({a["session_date"] for a in assets})
    session_ids = {date: date for date in all_dates}
    roles = ("train", "valid") if args.access == "public" else ("test",)
    output_root.mkdir(parents=True, exist_ok=True)
    access_root = output_root / args.access
    access_root.mkdir(mode=0o700 if args.access == "evaluator" else 0o755, exist_ok=True)
    if args.access == "evaluator":
        os.chmod(access_root, 0o700)
    summaries, trusted = [], []
    for role in roles:
        selected = [a for a in assets if a["role"] == role]
        summary, records = export_role(source_root, cache_root, output_root, role, selected, session_ids)
        summaries.append(summary)
        trusted.extend(records)
    trusted_dir = output_root / "trusted_receipts"
    trusted_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(trusted_dir, 0o700)
    receipt_path = trusted_dir / f"h1-{args.access}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    receipt = {"schema": "bpb-h1-export-receipt/1", "access": args.access, "profile": PROFILE,
               "source_manifest_sha256": ASSET_MANIFEST_SHA, "protocol_sha256": PROTOCOL_SHA,
               "exporter_sha256": sha256_file(Path(__file__)), "source_sha": SOURCE_SHA,
               "created_utc": datetime.now(timezone.utc).isoformat(), "roles": summaries,
               "source_bindings": trusted, "test_model_evaluated": False,
               "data_uploaded": False}
    with receipt_path.open("x") as output:
        json.dump(receipt, output, sort_keys=True, indent=2)
        output.write("\n")
    os.chmod(receipt_path, 0o600)
    print(json.dumps({"receipt": str(receipt_path), "roles": summaries,
                      "test_model_evaluated": False}, sort_keys=True))


if __name__ == "__main__":
    main()
