"""Fetch pinned MABe22 pose files and make numeric-only, label-free Agent inputs.

The Caltech object labels are converted separately by mabe_trusted_extract.py
inside a no-network container. This module never loads an object NPY.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import os
from pathlib import Path
import pickle
import re
import tempfile
from urllib.request import Request, urlopen

import h5py
import numpy as np

REVISION = "22019237bee137b74f8211977779c822236b8402"
DATASET = "WeihanLikk/ResiFuse-MABe22"
ROOT = f"https://huggingface.co/datasets/{DATASET}"
TREE = f"https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}/deeplabcut_filtered?recursive=false&limit=1000"
PARTS = ("nose", "left ear", "right ear", "neck", "center back", "left forepaw",
         "right forepaw", "left hindpaw", "right hindpaw", "tail base",
         "tail middle", "tail tip")
MICE = ("A0", "A1", "A2")
COORDS = ("x", "y", "likelihood")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_ids(root: Path) -> dict[str, list[str]]:
    split = json.loads((root / "mabe_finetune_split.json").read_text())["splits"]
    if {k: len(v) for k, v in split.items()} != {"train": 54, "val": 11, "test": 43}:
        raise ValueError("unexpected pinned supervised split")
    all_ids = [x for v in split.values() for x in v]
    if len(set(all_ids)) != 108 or any(not re.fullmatch(r"[A-Z0-9]{20}", x) for x in all_ids):
        raise ValueError("invalid split IDs")
    return split


def source_manifest(root: Path) -> dict:
    """Resolve the exact 108 H5 paths and LFS SHA256s at the pinned revision."""
    needed = {video_id for ids in split_ids(root).values() for video_id in ids}
    found: dict[str, dict] = {}
    next_url = TREE
    pages = 0
    while next_url:
        if pages > 10 or not next_url.startswith("https://huggingface.co/api/datasets/"):
            raise ValueError("unexpected Hugging Face pagination")
        with urlopen(Request(next_url, headers={"User-Agent": "BrainPilotBench-source-prep/1"}), timeout=60) as response:
            entries = json.load(response)
            link = response.headers.get("Link", "")
        for entry in entries:
            path = entry.get("path", "")
            match = re.fullmatch(r"deeplabcut_filtered/([A-Z0-9]{20}).*_el\.h5", path)
            if not match or match.group(1) not in needed:
                continue
            video_id = match.group(1)
            if video_id in found:
                raise ValueError(f"multiple pose files for {video_id}")
            lfs = entry.get("lfs") or {}
            if not re.fullmatch(r"[0-9a-f]{64}", lfs.get("oid", "")) or not 0 < lfs.get("size", 0) < 10_000_000:
                raise ValueError("missing or oversized LFS object")
            found[video_id] = {"path": path, "size": lfs["size"], "sha256": lfs["oid"]}
        match = re.search(r'<(https://huggingface\.co/[^>]+)>; rel="next"', link)
        next_url = match.group(1) if match else None
        pages += 1
    missing = sorted(needed - set(found))
    if missing:
        raise ValueError(f"missing pinned pose files for {len(missing)} split IDs: {missing[:5]}")
    manifest = {"schema": "bpb-mabe-pose-source/1", "dataset": DATASET,
                "revision": REVISION, "split_sha256": sha256(root / "mabe_finetune_split.json"),
                "videos": dict(sorted(found.items()))}
    (root / "pose_source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def download_pose(root: Path, manifest: dict, workers: int = 6) -> dict:
    target_dir = root / "pose_h5"
    target_dir.mkdir(parents=True, exist_ok=True)

    def fetch(item: tuple[str, dict]) -> tuple[str, str]:
        video_id, source = item
        target = target_dir / f"{video_id}.h5"
        if target.exists() and target.stat().st_size == source["size"] and sha256(target) == source["sha256"]:
            return video_id, "cached"
        url = f"{ROOT}/resolve/{REVISION}/{source['path']}?download=true"
        with tempfile.NamedTemporaryFile(dir=target_dir, prefix=f".{video_id}.", delete=False) as temp:
            temp_path = Path(temp.name)
            try:
                with urlopen(Request(url, headers={"User-Agent": "BrainPilotBench-source-prep/1"}), timeout=120) as response:
                    while chunk := response.read(1024 * 1024):
                        temp.write(chunk)
                        if temp.tell() > source["size"]:
                            raise ValueError(f"download larger than pinned size: {video_id}")
                temp.flush()
                if temp.tell() != source["size"] or sha256(temp_path) != source["sha256"]:
                    raise ValueError(f"LFS hash or size mismatch: {video_id}")
                os.replace(temp_path, target)
                return video_id, "downloaded"
            finally:
                temp_path.unlink(missing_ok=True)

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, item): item[0] for item in manifest["videos"].items()}
        for future in as_completed(futures):
            video_id, status = future.result()
            results[video_id] = status
    return {"videos": len(results), "downloaded": sum(v == "downloaded" for v in results.values()),
            "cached": sum(v == "cached" for v in results.values()),
            "bytes": sum(v["size"] for v in manifest["videos"].values())}


class _MetadataUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        raise ValueError("H5 column metadata may contain only literal tuples and strings")


def read_pose(path: Path) -> np.ndarray:
    """Decode only the numeric table and its restricted, small column-name list."""
    with h5py.File(path) as h5:
        table = h5["tracks/table"]
        if table.shape != (1801,) or table.dtype["values_block_0"].shape != (108,):
            raise ValueError(f"unexpected pose table shape: {path.name}")
        metadata = bytes(table.attrs["values_block_0_kind"])
        if len(metadata) > 10000:
            raise ValueError("oversized H5 metadata")
        columns = _MetadataUnpickler(io.BytesIO(metadata)).load()
        if (type(columns) is not list or len(columns) != 108
                or any(type(col) is not tuple or len(col) != 4
                       or any(type(part) is not str for part in col) for col in columns)):
            raise ValueError("invalid H5 column metadata")
        if len({col[0] for col in columns}) != 1:
            raise ValueError("mixed H5 scorer columns")
        expected = {(mouse, part, coord) for mouse in MICE for part in PARTS for coord in COORDS}
        if {(a, b, c) for _, a, b, c in columns} != expected:
            raise ValueError("missing or duplicate mouse, keypoint, or coordinate")
        indices = table["index"][:]
        if not np.array_equal(indices, np.arange(1801)):
            raise ValueError("pose frame indices are not 0..1800")
        raw = table["values_block_0"][:1800]
    output = np.empty((1800, 3, 12, 3), dtype=np.float32)
    for col_index, (_, mouse, part, coord) in enumerate(columns):
        output[:, MICE.index(mouse), PARTS.index(part), COORDS.index(coord)] = raw[:, col_index]
    if np.isinf(output).any():
        raise ValueError("infinite pose value")
    return output


def prepare_pose(root: Path, manifest: dict) -> dict:
    split = split_ids(root)
    public = root / "public" / "pose"
    records = {}
    for role, ids in split.items():
        destination = public / role
        destination.mkdir(parents=True, exist_ok=True)
        for video_id in ids:
            source = root / "pose_h5" / f"{video_id}.h5"
            entry = manifest["videos"][video_id]
            if not source.exists() or source.stat().st_size != entry["size"] or sha256(source) != entry["sha256"]:
                raise ValueError(f"missing or unverified pose H5: {video_id}")
            pose = read_pose(source)
            target = destination / f"{video_id}.npz"
            with target.open("wb") as output:
                np.savez_compressed(output, pose=pose, frame_index=np.arange(1800, dtype=np.int32))
            records[video_id] = {"role": role, "path": str(target.relative_to(root)),
                                 "sha256": sha256(target), "frames": 1800,
                                 "finite_fraction": float(np.isfinite(pose).mean())}
    result = {"schema": "bpb-mabe-pose-preparation/1", "source_manifest_sha256": sha256(root / "pose_source_manifest.json"),
              "alignment": "H5 index 0..1799 matches each 1800-frame Caltech map span; terminal index 1800 excluded as in pinned ResiFuse preprocessing truncation",
              "axes": ["frame", "mouse A0/A1/A2", "bodypart", "x/y/likelihood"],
              "bodyparts": list(PARTS), "files": dict(sorted(records.items()))}
    (root / "pose_preparation_manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return {"videos": len(records), "frames_per_video": 1800,
            "min_finite_fraction": min(v["finite_fraction"] for v in records.values())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("resolve", "fetch", "prepare"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.command == "resolve":
        result = source_manifest(args.root)
        print(json.dumps({"videos": len(result["videos"]), "bytes": sum(v["size"] for v in result["videos"].values())}))
    else:
        manifest = json.loads((args.root / "pose_source_manifest.json").read_text())
        if manifest["revision"] != REVISION or manifest["split_sha256"] != sha256(args.root / "mabe_finetune_split.json"):
            raise ValueError("source manifest does not match pinned revision and split")
        result = download_pose(args.root, manifest, args.workers) if args.command == "fetch" else prepare_pose(args.root, manifest)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
