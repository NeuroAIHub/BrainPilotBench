"""Fetch pinned M1/M2 source assets through one bounded HTTP range at a time.

Completed chunks remain outside Git with their SHA-256 receipts. A later run
checks each chunk before it resumes. The final file moves into place only after
its frozen byte count and whole-file SHA-256 match the source manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
PREPARATION = HERE.parent / "_preparation" / "prepare.py"
sys.path.insert(0, str(PREPARATION.parent))
spec = importlib.util.spec_from_file_location("falcon_prepare", PREPARATION)
assert spec is not None and spec.loader is not None
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z")


def expired(_signum, _frame):
    raise TimeoutError("one HTTP range exceeded its transfer deadline")


def digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save_receipt(path: Path, receipt: dict) -> None:
    with tempfile.NamedTemporaryFile("w", prefix=".receipt-", dir=path.parent,
                                     delete=False) as out:
        temporary = Path(out.name)
        json.dump(receipt, out, sort_keys=True, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_metadata(asset: dict) -> None:
    with urlopen(f"{prepare.API}/assets/{asset['asset_id']}/", timeout=30) as response:
        live = json.load(response)
    if (live.get("path") != asset["path"] or live.get("contentSize") != asset["size_bytes"]
            or live.get("digest", {}).get("dandi:sha2-256") != asset["sha256"]):
        raise ValueError("frozen asset metadata changed")


def checked_prefix(partial: Path, receipt_path: Path, asset: dict, chunk_bytes: int) -> tuple[dict, int]:
    if not partial.exists() and not receipt_path.exists():
        return {"asset_id": asset["asset_id"], "sha256": asset["sha256"],
                "size_bytes": asset["size_bytes"], "chunk_bytes": chunk_bytes, "chunks": []}, 0
    if not partial.is_file() or partial.is_symlink() or not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("partial source or receipt is missing or symbolic")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("asset_id") != asset["asset_id"] or receipt.get("sha256") != asset["sha256"]
            or receipt.get("size_bytes") != asset["size_bytes"] or receipt.get("chunk_bytes") != chunk_bytes):
        raise ValueError("partial source receipt does not bind frozen asset")
    prefix = 0
    with partial.open("rb") as data:
        for chunk in receipt["chunks"]:
            if chunk["offset"] != prefix or not 0 < chunk["bytes"] <= chunk_bytes:
                raise ValueError("partial source chunk offsets invalid")
            block = data.read(chunk["bytes"])
            if len(block) != chunk["bytes"] or hashlib.sha256(block).hexdigest() != chunk["sha256"]:
                raise ValueError("partial source chunk digest changed")
            prefix += len(block)
    if prefix > asset["size_bytes"] or partial.stat().st_size < prefix:
        raise ValueError("partial source length invalid")
    if partial.stat().st_size > prefix:
        # Only bytes from an interrupted, unreceipted range are discarded.
        with partial.open("r+b") as data:
            data.truncate(prefix)
    return receipt, prefix


def fetch_one(root: Path, asset: dict, chunk_bytes: int, seconds: int) -> str:
    destination = prepare.file_path(root, asset)
    if destination.exists():
        prepare.verify_one(destination, asset)
        return "already verified"
    verify_metadata(asset)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if "evaluator" in root.parts:
        destination.parent.chmod(0o700)
    partial = destination.with_name(destination.name + ".partial")
    receipt_path = destination.with_name(destination.name + ".partial.json")
    receipt, offset = checked_prefix(partial, receipt_path, asset, chunk_bytes)
    if not receipt_path.exists():
        partial.touch(exist_ok=False)
        save_receipt(receipt_path, receipt)
    while offset < asset["size_bytes"]:
        end = min(offset + chunk_bytes, asset["size_bytes"]) - 1
        request = Request(f"{prepare.API}/assets/{asset['asset_id']}/download/",
                          headers={"Range": f"bytes={offset}-{end}"})
        signal.alarm(seconds)
        try:
            with urlopen(request, timeout=60) as response:
                header = RANGE.fullmatch(response.headers.get("Content-Range", ""))
                if (response.status != 206 or header is None
                        or tuple(map(int, header.groups())) != (offset, end, asset["size_bytes"])):
                    raise ValueError("source server did not honor the exact requested byte range")
                hasher = hashlib.sha256()
                received = 0
                with partial.open("ab") as out:
                    while received < end - offset + 1:
                        block = response.read(min(4 * 1024 * 1024, end - offset + 1 - received))
                        if not block:
                            raise ValueError("source range ended early")
                        out.write(block)
                        hasher.update(block)
                        received += len(block)
                    out.flush()
                    os.fsync(out.fileno())
        finally:
            signal.alarm(0)
        receipt["chunks"].append({"offset": offset, "bytes": received,
                                   "sha256": hasher.hexdigest()})
        save_receipt(receipt_path, receipt)
        offset += received
        print(f"progress {asset['asset_id']} {offset}/{asset['size_bytes']}", flush=True)
    if partial.stat().st_size != asset["size_bytes"] or digest_file(partial) != asset["sha256"]:
        raise ValueError("complete source file differs from frozen SHA-256")
    if destination.exists():
        raise FileExistsError(destination)
    os.replace(partial, destination)
    receipt_path.unlink()
    return "downloaded and verified"


def adopt_legacy(root: Path, asset: dict, legacy: Path, chunk_bytes: int) -> None:
    """Bind one interrupted fetch_bounded partial before range resumption."""
    destination = prepare.file_path(root, asset)
    partial = destination.with_name(destination.name + ".partial")
    receipt_path = destination.with_name(destination.name + ".partial.json")
    legacy = legacy.absolute()
    if (legacy.parent != destination.parent or not legacy.name.startswith(".partial-")
            or not legacy.is_file() or legacy.is_symlink() or legacy.stat().st_nlink != 1
            or destination.exists() or partial.exists() or receipt_path.exists()
            or not 0 < legacy.stat().st_size <= chunk_bytes):
        raise ValueError("legacy partial is not a unique bounded file for this asset")
    size = legacy.stat().st_size
    chunk_sha = digest_file(legacy)
    os.replace(legacy, partial)
    receipt = {"asset_id": asset["asset_id"], "sha256": asset["sha256"],
               "size_bytes": asset["size_bytes"], "chunk_bytes": chunk_bytes,
               "chunks": [{"offset": 0, "bytes": size, "sha256": chunk_sha}]}
    save_receipt(receipt_path, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--task", choices=("falcon-m1-emg", "falcon-m2-finger-velocity"))
    parser.add_argument("--asset-id", action="append", default=[])
    parser.add_argument("--adopt-partial", type=Path)
    parser.add_argument("--limit-bytes", type=int, default=18_000_000_000)
    parser.add_argument("--chunk-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--range-seconds", type=int, default=1200)
    args = parser.parse_args()
    if not 1_048_576 <= args.chunk_bytes <= 128 * 1024 * 1024:
        parser.error("chunk size must be between 1 and 128 MiB")
    if not 1 <= args.range_seconds <= 3600:
        parser.error("range deadline must be between 1 and 3600 seconds")
    tasks = {args.task} if args.task else {"falcon-m1-emg", "falcon-m2-finger-velocity"}
    assets = [asset for asset in prepare.load_manifest()["assets"] if asset["task_id"] in tasks]
    if args.asset_id:
        unknown = set(args.asset_id) - {asset["asset_id"] for asset in assets}
        if unknown:
            parser.error(f"asset IDs outside selected task: {sorted(unknown)}")
        assets = [asset for asset in assets if asset["asset_id"] in set(args.asset_id)]
    total = sum(asset["size_bytes"] for asset in assets)
    if total > args.limit_bytes:
        parser.error(f"frozen selection {total} bytes exceeds limit {args.limit_bytes}")
    root = prepare.safe_destination(args.dest)
    if args.adopt_partial is not None:
        if len(assets) != 1:
            parser.error("legacy adoption requires exactly one selected asset ID")
        asset = assets[0]
        access = "evaluator" if asset["role"] == "test" else "public"
        adopt_legacy(root / access, asset, args.adopt_partial, args.chunk_bytes)
    signal.signal(signal.SIGALRM, expired)
    print(f"source bytes={total}; files={len(assets)}", flush=True)
    for asset in assets:
        access = "evaluator" if asset["role"] == "test" else "public"
        access_root = root / access
        access_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if access == "evaluator":
            access_root.chmod(0o700)
        print(f"start {asset['task_id']} {asset['role']} {asset['asset_id']} {asset['size_bytes']}", flush=True)
        print(f"done {asset['asset_id']} {fetch_one(access_root, asset, args.chunk_bytes, args.range_seconds)}", flush=True)


if __name__ == "__main__":
    main()
