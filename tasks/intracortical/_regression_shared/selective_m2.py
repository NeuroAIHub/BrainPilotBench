"""Extract M2 native arrays from pinned DANDI assets by verified HTTP range.

The DANDI source files contain large fullband recordings that the pinned
FALCON loader does not read. This tool reads only the HDF5 blocks required by
that loader. It verifies asset identity, version membership, S3 ETag, every
Content-Range, and every downloaded range digest. It never claims that the
published whole-file SHA-256 was recomputed locally.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.request import Request, urlopen

import h5py
import numpy as np
from pynwb import NWBHDF5IO

from export import (ARRAYS, ASSET_MANIFEST_SHA, DOMAIN, PROFILE, SOURCE_SHA,
                    SPECS, convert_nwb, digest, frozen_sources, outside_git)


TASK_ID = "falcon-m2-finger-velocity"
SPEC = SPECS[TASK_ID]
API = "https://api.dandiarchive.org/api"
RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z")
MAX_ASSET_BODY = 16_000_000
MAX_TOTAL_BODY = 250_000_000
BLOCK = 65_536


def version_metadata(asset: dict) -> tuple[dict, str]:
    url = (f"{API}/dandisets/{asset['dandiset_id']}/versions/"
           f"{asset['version']}/assets/{asset['asset_id']}/")
    with urlopen(url, timeout=30) as response:
        raw = response.read(200_001)
    if len(raw) > 200_000:
        raise ValueError("asset metadata response exceeded limit")
    metadata = json.loads(raw)
    if (metadata.get("identifier") != asset["asset_id"]
            or metadata.get("path") != asset["path"]
            or metadata.get("contentSize") != asset["size_bytes"]
            or metadata.get("digest", {}).get("dandi:sha2-256") != asset["sha256"]):
        raise ValueError("versioned DANDI asset differs from frozen manifest")
    etag = metadata.get("digest", {}).get("dandi:dandi-etag")
    if (not isinstance(etag, str) or etag != asset["dandi_etag"]
            or re.fullmatch(r"[0-9a-f]{32}(?:-\d+)?", etag) is None):
        raise ValueError("DANDI asset ETag missing or malformed")
    return metadata, hashlib.sha256(raw).hexdigest()


class PinnedRangeFile(io.RawIOBase):
    def __init__(self, asset: dict, etag: str, max_body_bytes: int, range_store: Path):
        self.asset = asset
        self.etag = etag
        self.max_body_bytes = max_body_bytes
        self.pos = 0
        self.downloaded = 0
        self.cache = OrderedDict()
        self.ranges = []
        self.blob_url = None
        self.range_store = range_store
        self.range_store.mkdir(mode=0o700)
        self.saved = {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError("invalid seek mode")
        self.pos = (0, self.pos, self.asset["size_bytes"])[whence] + offset
        if self.pos < 0:
            raise ValueError("negative file seek")
        return self.pos

    def _block(self, number: int) -> bytes:
        if number in self.cache:
            self.cache.move_to_end(number)
            return self.cache[number]
        if number in self.saved:
            info = self.saved[number]
            path = self.range_store / f"{info['offset']:012d}.bin"
            data = path.read_bytes()
            if len(data) != info["bytes"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
                raise ValueError("local selected HTTP range digest changed")
            self.cache[number] = data
            return data
        begin = number * BLOCK
        end = min(begin + BLOCK, self.asset["size_bytes"]) - 1
        needed = end - begin + 1
        if self.downloaded + needed > self.max_body_bytes:
            raise RuntimeError("selected extraction exceeded per-asset byte cap")
        url = self.blob_url or f"{API}/assets/{self.asset['asset_id']}/download/"
        request = Request(url, headers={"Range": f"bytes={begin}-{end}",
                                        "If-Match": f'"{self.etag}"'})
        with urlopen(request, timeout=30) as response:
            header = RANGE.fullmatch(response.headers.get("Content-Range", ""))
            returned_etag = response.headers.get("ETag", "").strip('"')
            if (response.status != 206 or header is None
                    or tuple(map(int, header.groups())) != (begin, end, self.asset["size_bytes"])
                    or returned_etag != self.etag):
                raise ValueError("HTTP range identity, extent, or ETag differs from pinned asset")
            data = response.read(needed + 1)
            final_url = response.geturl()
        if len(data) != needed:
            raise ValueError("HTTP range body length differs from Content-Range")
        if self.blob_url is None:
            self.blob_url = final_url
        record = {"offset": begin, "bytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(), "etag": self.etag}
        path = self.range_store / f"{begin:012d}.bin"
        with path.open("xb") as out:
            out.write(data)
        if self.asset["role"] == "test":
            path.chmod(0o600)
        self.saved[number] = record
        self.downloaded += len(data)
        self.ranges.append(record)
        self.cache[number] = data
        self.cache.move_to_end(number)
        while len(self.cache) > 32:
            self.cache.popitem(last=False)
        return data

    def read(self, size=-1):
        remaining = max(0, self.asset["size_bytes"] - self.pos)
        if size < 0:
            size = remaining
        size = min(size, remaining)
        parts = []
        while size:
            number, inside = divmod(self.pos, BLOCK)
            block = self._block(number)
            piece = block[inside:inside + size]
            parts.append(piece)
            self.pos += len(piece)
            size -= len(piece)
        return b"".join(parts)

    def readinto(self, target):
        data = self.read(len(target))
        target[:len(data)] = data
        return len(data)


class LocalRangeFile(PinnedRangeFile):
    def __init__(self, asset: dict, receipt: dict, root: Path):
        self.asset = asset
        self.pos = 0
        self.cache = OrderedDict()
        self.range_store = root / "ranges"
        self.saved = {item["offset"] // BLOCK: item for item in receipt["ranges"]}

    def _block(self, number: int) -> bytes:
        if number not in self.saved:
            raise ValueError("native conversion requested an unrecorded source range")
        if number in self.cache:
            self.cache.move_to_end(number)
            return self.cache[number]
        info = self.saved[number]
        path = self.range_store / f"{info['offset']:012d}.bin"
        data = path.read_bytes()
        if len(data) != info["bytes"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise ValueError("local selected HTTP range digest changed")
        self.cache[number] = data
        while len(self.cache) > 32:
            self.cache.popitem(last=False)
        return data


def verify_prepared(root: Path, asset: dict) -> dict:
    receipt_path = root / "receipt.json"
    if not root.is_dir() or root.is_symlink() or not receipt_path.is_file():
        raise ValueError("prepared source asset missing or symbolic")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("schema") != "bpb-m2-selected-range-source/1"
            or receipt.get("source_asset_id") != asset["asset_id"]
            or receipt.get("source_sha256_published") != asset["sha256"]
            or receipt.get("source_dandi_etag") != asset["dandi_etag"]
            or receipt.get("dandiset_version") != asset["version"]
            or receipt.get("full_raw_sha256_verified") is not False
            or receipt.get("source_manifest_sha256") != ASSET_MANIFEST_SHA):
        raise ValueError("prepared source receipt differs from frozen source")
    native_metadata_sha = hashlib.sha256(json.dumps(
        receipt.get("native_hdf5_metadata"), sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    if native_metadata_sha != receipt.get("native_hdf5_metadata_sha256"):
        raise ValueError("native HDF5 metadata digest mismatch")
    native_metadata = receipt["native_hdf5_metadata"]
    if (native_metadata.get("units") != 96
            or len(native_metadata.get("velocity_series", [])) != 2
            or len(native_metadata.get("derived_shapes", [])) != 4):
        raise ValueError("native HDF5 dimensions differ from M2 protocol")
    if set(receipt.get("files", {})) != set(ARRAYS):
        raise ValueError("prepared source array set differs from M2 contract")
    if not receipt["ranges"] or sum(item["bytes"] for item in receipt["ranges"]) != receipt["downloaded_bytes"]:
        raise ValueError("selected-range receipt length mismatch")
    if (root / "ranges").is_symlink() or not (root / "ranges").is_dir():
        raise ValueError("selected source range directory is missing or symbolic")
    seen_offsets = set()
    for item in receipt["ranges"]:
        offset = item["offset"]
        path = root / "ranges" / f"{offset:012d}.bin"
        if (offset in seen_offsets or item["etag"] != receipt["source_dandi_etag"]
                or not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"]
                or digest(path) != item["sha256"]):
            raise ValueError("local selected HTTP range differs from its receipt")
        seen_offsets.add(offset)
    for name in ARRAYS:
        path = root / name
        info = receipt["files"][name]
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != info["bytes"]
                or digest(path) != info["sha256"]):
            raise ValueError("prepared source array digest mismatch")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if list(array.shape) != info["shape"] or array.dtype.name != info["dtype"]:
            raise ValueError("prepared source array shape mismatch")
    return receipt


def verify_reconstruction(root: Path, asset: dict) -> dict:
    receipt = verify_prepared(root, asset)
    source = LocalRangeFile(asset, receipt, root)
    with h5py.File(source, "r") as h5:
        with NWBHDF5IO(file=h5, mode="r", load_namespaces=True) as io:
            arrays = convert_nwb(io.read(), SPEC)
    for name, array in zip(ARRAYS, arrays):
        if not np.array_equal(array, np.load(root / name, allow_pickle=False)):
            raise ValueError("derived array differs from locally receipted source ranges")
    return {"asset_id": asset["asset_id"], "source_range_reconstruction_exact": True,
            "timesteps": int(arrays[0].shape[0]), "downloaded_bytes": receipt["downloaded_bytes"]}


def prepare_one(output_root: Path, asset: dict, remaining_bytes: int) -> dict:
    access = "evaluator" if asset["role"] == "test" else "public"
    base = output_root / access / "selected_sources"
    base.mkdir(parents=True, exist_ok=True, mode=0o700 if access == "evaluator" else 0o755)
    if access == "evaluator":
        base.parent.chmod(0o700)
        base.chmod(0o700)
    final = base / asset["asset_id"]
    if final.exists():
        result = verify_prepared(final, asset)
        return {"asset_id": asset["asset_id"], "reused_verified": True,
                "downloaded_bytes": result["downloaded_bytes"]}
    metadata, metadata_sha = version_metadata(asset)
    etag = metadata["digest"]["dandi:dandi-etag"]
    with tempfile.TemporaryDirectory(prefix=f".{asset['asset_id']}-", dir=base) as temporary:
        stage = Path(temporary)
        source = PinnedRangeFile(asset, etag, min(MAX_ASSET_BODY, remaining_bytes), stage / "ranges")
        with h5py.File(source, "r") as h5:
            with NWBHDF5IO(file=h5, mode="r", load_namespaces=True) as io:
                nwb = io.read()
                arrays = convert_nwb(nwb, SPEC)
                native_metadata = {
                    "units": len(nwb.units), "trials": len(nwb.trials),
                    "velocity_series": sorted((name, list(series.data.shape),
                                                list(series.timestamps.shape))
                                               for name, series in nwb.acquisition["finger_vel"].time_series.items()),
                    "eval_mask_shape": list(nwb.acquisition["eval_mask"].data.shape),
                    "derived_shapes": [list(array.shape) for array in arrays],
                }
                native_metadata_sha = hashlib.sha256(json.dumps(
                    native_metadata, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        files = {}
        for name, array in zip(ARRAYS, arrays):
            path = stage / name
            with path.open("xb") as out:
                np.save(out, array, allow_pickle=False)
            if access == "evaluator":
                path.chmod(0o600)
            files[name] = {"shape": list(array.shape), "dtype": array.dtype.name,
                           "bytes": path.stat().st_size, "sha256": digest(path)}
        receipt = {"schema": "bpb-m2-selected-range-source/1", "task_id": TASK_ID,
                   "source_asset_id": asset["asset_id"], "dandiset_id": asset["dandiset_id"],
                   "dandiset_version": asset["version"], "source_path": asset["path"],
                   "role": asset["role"], "session_date": asset["session_date"],
                   "source_bytes_published": asset["size_bytes"],
                   "source_sha256_published": asset["sha256"],
                   "full_raw_sha256_verified": False,
                   "source_manifest_sha256": ASSET_MANIFEST_SHA,
                   "metadata_json_sha256": metadata_sha, "source_dandi_etag": etag,
                   "native_hdf5_metadata": native_metadata,
                   "native_hdf5_metadata_sha256": native_metadata_sha,
                   "range_policy": "exact Content-Range, If-Match and matching ETag on every range",
                   "downloaded_bytes": source.downloaded, "ranges": source.ranges,
                   "files": files, "test_model_evaluated": False}
        receipt_path = stage / "receipt.json"
        with receipt_path.open("x") as out:
            json.dump(receipt, out, sort_keys=True, indent=2)
            out.write("\n")
        if access == "evaluator":
            receipt_path.chmod(0o600)
            stage.chmod(0o700)
        if final.exists():
            raise FileExistsError(final)
        os.replace(stage, final)
    return {"asset_id": asset["asset_id"], "reused_verified": False,
            "downloaded_bytes": source.downloaded,
            "timesteps": int(arrays[0].shape[0]), "valid_timesteps": int(arrays[2].sum())}


def assemble_role(output_root: Path, role: str, assets: list[dict]) -> tuple[dict, list[dict]]:
    access = "evaluator" if role == "test" else "public"
    access_root = output_root / access
    role_root = access_root / role
    if role_root.exists():
        raise FileExistsError(f"role already assembled: {role_root}")
    runs, bindings = [], []
    with tempfile.TemporaryDirectory(prefix=f".{role}-", dir=access_root) as temporary:
        stage = Path(temporary)
        (stage / "runs").mkdir(mode=0o700 if role == "test" else 0o755)
        for index, asset in enumerate(sorted(assets, key=lambda item: (item["session_date"], item["path"])), 1):
            source = access_root / "selected_sources" / asset["asset_id"]
            receipt = verify_prepared(source, asset)
            if receipt["role"] != role or receipt["session_date"] != asset["session_date"]:
                raise ValueError("prepared source role or date changed")
            run_id = f"m2-{role}-{index:04d}"
            run_dir = stage / "runs" / run_id
            run_dir.mkdir(mode=0o700 if role == "test" else 0o755)
            files = {}
            for name in ARRAYS:
                target = run_dir / name
                shutil.copyfile(source / name, target)
                if role == "test":
                    target.chmod(0o600)
                info = receipt["files"][name]
                if target.stat().st_size != info["bytes"] or digest(target) != info["sha256"]:
                    raise ValueError("assembled array differs from selected source")
                files[name] = {"path": str(target.relative_to(stage)), **info}
            mask = np.load(run_dir / "mask.npy", allow_pickle=False)
            trial_start = np.load(run_dir / "trial_start.npy", allow_pickle=False)
            runs.append({"id": run_id, "role": role, "session_id": asset["session_date"],
                         "order": index - 1, "files": files,
                         "valid_timesteps": int(mask.sum()),
                         "trial_starts": int(trial_start.sum())})
            bindings.append({"id": run_id, "role": role, "date": asset["session_date"],
                             "source_asset_id": asset["asset_id"],
                             "source_sha256": asset["sha256"],
                             "source_bytes": asset["size_bytes"],
                             "full_raw_sha256_verified": False,
                             "selected_range_receipt_sha256": digest(source / "receipt.json"),
                             "selected_downloaded_bytes": receipt["downloaded_bytes"],
                             "files": files})
        manifest = {"schema": "bpb-falcon-regression-data/1", "task_id": TASK_ID,
                    "profile": PROFILE, "role": role, "source_sha": SOURCE_SHA,
                    "source_manifest_sha256": ASSET_MANIFEST_SHA,
                    "protocol_sha256": digest(DOMAIN / TASK_ID / "protocol.json"),
                    "exporter_sha256": digest(Path(__file__)),
                    "source_verification": "versioned DANDI metadata and selected HTTP ranges",
                    "full_raw_sha256_verified": False,
                    "boundary_semantics": "native searchsorted(trial.start_time) on velocity timestamps",
                    "runs": runs}
        manifest_path = stage / "manifest.json"
        with manifest_path.open("x") as out:
            json.dump(manifest, out, sort_keys=True, indent=2)
            out.write("\n")
        if role == "test":
            manifest_path.chmod(0o600)
            stage.chmod(0o700)
        os.replace(stage, role_root)
    final_manifest = role_root / "manifest.json"
    return {"role": role, "manifest_path": str(final_manifest),
            "manifest_sha256": digest(final_manifest), "runs": len(runs),
            "session_count": len({item["session_id"] for item in runs})}, bindings


def assemble(output_root: Path, access: str, assets: list[dict]) -> dict:
    roles = ("train", "valid") if access == "public" else ("test",)
    access_root = output_root / access
    access_root.mkdir(parents=True, exist_ok=True,
                      mode=0o700 if access == "evaluator" else 0o755)
    if access == "evaluator":
        access_root.chmod(0o700)
    for asset in assets:
        source_root = access_root / "selected_sources" / asset["asset_id"]
        receipt = verify_prepared(source_root, asset)
        _, metadata_sha = version_metadata(asset)
        if receipt["metadata_json_sha256"] != metadata_sha:
            raise ValueError("versioned source metadata changed after selected extraction")
        verify_reconstruction(source_root, asset)
    summaries, bindings = [], []
    for role in roles:
        selected = [asset for asset in assets if asset["role"] == role]
        summary, role_bindings = assemble_role(output_root, role, selected)
        summaries.append(summary)
        bindings.extend(role_bindings)
    trusted_dir = output_root / "trusted_receipts"
    trusted_dir.mkdir(exist_ok=True, mode=0o700)
    trusted_dir.chmod(0o700)
    receipt_path = trusted_dir / f"m2-{access}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    receipt = {"schema": "bpb-falcon-regression-selective-export/1",
               "task_id": TASK_ID, "access": access, "profile": PROFILE,
               "source_manifest_sha256": ASSET_MANIFEST_SHA,
               "protocol_sha256": digest(DOMAIN / TASK_ID / "protocol.json"),
               "exporter_sha256": digest(Path(__file__)), "source_sha": SOURCE_SHA,
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "roles": summaries, "source_bindings": bindings,
               "full_raw_sha256_verified": False, "test_model_evaluated": False,
               "data_uploaded": False}
    with receipt_path.open("x") as out:
        json.dump(receipt, out, sort_keys=True, indent=2)
        out.write("\n")
    receipt_path.chmod(0o600)
    return {"receipt": str(receipt_path), "roles": summaries,
            "full_raw_sha256_verified": False, "test_model_evaluated": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "assemble"))
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--access", choices=("public", "evaluator"), required=True)
    parser.add_argument("--allow-test-export", action="store_true")
    parser.add_argument("--asset-id", action="append", default=[])
    parser.add_argument("--max-total-body-bytes", type=int, default=MAX_TOTAL_BODY)
    args = parser.parse_args()
    if args.access == "evaluator" and not args.allow_test_export:
        parser.error("evaluator selective conversion requires --allow-test-export")
    if not 1 <= args.max_total_body_bytes <= MAX_TOTAL_BODY:
        parser.error("selected extraction body budget cannot exceed 250 MB")
    output = outside_git(args.output_root)
    _, _, all_assets = frozen_sources(TASK_ID)
    selected = [asset for asset in all_assets
                if asset["role"] in ({"train", "valid"} if args.access == "public" else {"test"})]
    if args.command == "assemble":
        if args.asset_id:
            parser.error("assemble requires every asset for the selected access")
        print(json.dumps(assemble(output, args.access, selected), sort_keys=True))
        return
    if args.asset_id:
        unknown = set(args.asset_id) - {asset["asset_id"] for asset in selected}
        if unknown:
            parser.error(f"asset IDs outside selected access: {sorted(unknown)}")
        selected = [asset for asset in selected if asset["asset_id"] in set(args.asset_id)]
    if args.command == "verify":
        for asset in selected:
            access_root = output / ("evaluator" if asset["role"] == "test" else "public")
            root = access_root / "selected_sources" / asset["asset_id"]
            print(json.dumps(verify_reconstruction(root, asset), sort_keys=True), flush=True)
        return
    output.mkdir(parents=True, exist_ok=True)
    existing = 0
    for asset in all_assets:
        access_root = output / ("evaluator" if asset["role"] == "test" else "public")
        source_root = access_root / "selected_sources" / asset["asset_id"]
        if source_root.exists():
            existing += verify_prepared(source_root, asset)["downloaded_bytes"]
    if existing > args.max_total_body_bytes:
        parser.error("saved selected ranges already exceed the total body budget")
    used = 0
    for asset in selected:
        result = prepare_one(output, asset, args.max_total_body_bytes - existing - used)
        if not result["reused_verified"]:
            used += result["downloaded_bytes"]
        print(json.dumps(result, sort_keys=True), flush=True)
    print(json.dumps({"task_id": TASK_ID, "new_downloaded_bytes": used,
                      "selected_assets": len(selected), "full_raw_sha256_verified": False,
                      "test_model_evaluated": False}, sort_keys=True))


if __name__ == "__main__":
    main()
