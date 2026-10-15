#!/usr/bin/env python3
"""Fetch only pinned clinical iEEG files with bounded independent transfers."""

from __future__ import annotations

import argparse
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = json.loads((ROOT / "full_source_manifest.json").read_text())
ROLES = ("events", "channels", "sidecar", "header", "markers", "signal")
LIMIT = 20_000_000_000
STOP = threading.Event()


def digests(path: Path) -> tuple[int, str, str]:
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            size += len(chunk)
            md5.update(chunk)
            sha.update(chunk)
    return size, md5.hexdigest(), sha.hexdigest()


def git_blob_sha(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, spec: dict) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular source file: {path}")
    size, md5, sha = digests(path)
    if size != spec["bytes"]:
        raise ValueError(f"Source byte count differs: {path}")
    if "md5" in spec and md5 != spec["md5"]:
        raise ValueError(f"Source annex MD5 differs: {path}")
    if "git_blob_sha1" in spec and git_blob_sha(path) != spec["git_blob_sha1"]:
        raise ValueError(f"Source Git blob differs: {path}")
    return sha


def fetch_one(path: Path, spec: dict, reuse: Path | None) -> int:
    if STOP.is_set():
        raise InterruptedError("Download stopped; partial bytes remain on disk")
    if path.exists():
        verify(path, spec)
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if reuse is not None:
        old = reuse / spec["path"]
        if old.is_file() and not old.is_symlink():
            verify(old, spec)
            shutil.copyfile(old, path)
            verify(path, spec)
            return 0
    partial = path.with_name(path.name + ".part")
    if partial.is_symlink() or (partial.exists() and partial.stat().st_size > spec["bytes"]):
        raise ValueError(f"Existing partial file needs operator review: {partial}")
    initial = partial.stat().st_size if partial.exists() else 0
    for head_attempt in range(3):
        if STOP.is_set():
            raise InterruptedError("Download stopped before source metadata request")
        try:
            with urlopen(Request(spec["url"], method="HEAD"), timeout=60) as response:
                if int(response.headers.get("Content-Length", "-1")) != spec["bytes"]:
                    raise ValueError(f"Remote byte count differs from pinned source: {path}")
                etag = response.headers.get("ETag")
            break
        except (OSError, TimeoutError) as error:
            if head_attempt == 2:
                raise RuntimeError(f"Three source metadata attempts failed: {path}") from error
            time.sleep(2 ** head_attempt)
    if "md5" in spec and not etag:
        raise ValueError(f"Source signal has no ETag for safe resume: {path}")
    for attempt in range(3):
        start = partial.stat().st_size if partial.exists() else 0
        if start == spec["bytes"]:
            verify(partial, spec)
            partial.replace(path)
            return 0
        headers = {"If-Match": etag} if etag else {}
        if start:
            headers["Range"] = f"bytes={start}-"
        try:
            with urlopen(Request(spec["url"], headers=headers), timeout=90) as response:
                if start and (response.status != 206 or
                              not response.headers.get("Content-Range", "").startswith(f"bytes {start}-")):
                    raise ValueError(f"Source did not honor exact resume range: {path}")
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) != spec["bytes"] - start:
                    raise ValueError(f"HTTP response exceeds pinned size: {path}")
                with partial.open("ab") as output:
                    while chunk := response.read(1024 * 1024):
                        if STOP.is_set():
                            raise InterruptedError("Download stopped; partial bytes remain on disk")
                        if output.tell() + len(chunk) > spec["bytes"]:
                            raise ValueError(f"Download exceeds pinned size: {path}")
                        output.write(chunk)
            if partial.stat().st_size < spec["bytes"]:
                raise OSError(f"Source response ended before pinned byte count: {path}")
            verify(partial, spec)
            partial.replace(path)
            return spec["bytes"] - initial
        except (OSError, TimeoutError) as error:
            if STOP.is_set():
                raise
            if attempt == 2:
                raise RuntimeError(f"Three attempts failed; partial bytes were preserved: {partial}") from error
            time.sleep(2 ** attempt)
        except Exception:
            raise
    raise AssertionError("Unreachable retry state")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--reuse", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3, 4, 5, 6), default=1,
                        help="Independent source file streams, at most six")
    args = parser.parse_args()
    if SOURCE["schema"] != "bpb-ieeg-film-full-source/1" or len(SOURCE["records"]) != 51:
        raise ValueError("Unexpected full source inventory")
    total = SOURCE["all_source_total_bytes"]
    if total > LIMIT:
        raise ValueError("Pinned clinical source exceeds the 20 GB limit")
    if not args.download:
        print(json.dumps({"status": "metadata_only", "files": 51 * len(ROLES),
                          "signal_bytes": SOURCE["signal_total_bytes"], "all_source_bytes": total,
                          "limit_bytes": LIMIT}, indent=2))
        return
    args.destination.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda _number, _frame: STOP.set())
    signal.signal(signal.SIGINT, lambda _number, _frame: STOP.set())
    receipt_path = args.destination / "source_receipt.json"
    status_path = args.destination / "fetch_status.json"
    started_at = datetime.now(timezone.utc).isoformat()
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("source_git_commit") != SOURCE["source_git_commit"]:
            raise ValueError("Existing receipt belongs to another source version")
    else:
        receipt = {"schema": "bpb-ieeg-film-source-receipt/1",
                   "source_git_commit": SOURCE["source_git_commit"], "files": {}}
    downloaded = 0
    signals = []

    def save_status(state: str) -> None:
        status = {"schema": "bpb-ieeg-film-fetch-status/1", "state": state,
                  "pid": os.getpid(), "started_at_utc": started_at,
                  "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                  "jobs": args.jobs, "completed_source_files": len(receipt["files"]),
                  "downloaded_bytes_this_call": downloaded,
                  "planned_total_bytes": total}
        temp = status_path.with_suffix(".json.part")
        temp.write_text(json.dumps(status, indent=2) + "\n")
        os.replace(temp, status_path)

    finished = [False]
    atexit.register(lambda: None if finished[0] else save_status("stopped" if STOP.is_set() else "failed"))
    save_status("running")

    def save_receipt() -> None:
        temp = receipt_path.with_suffix(".json.part")
        temp.write_text(json.dumps(receipt, indent=2) + "\n")
        os.replace(temp, receipt_path)

    for record in SOURCE["records"]:
        for role in ROLES:
            if args.metadata_only and role == "signal":
                continue
            spec = record["files"][role]
            path = args.destination / "source" / spec["path"]
            if role == "signal" and args.jobs > 1:
                signals.append((record["subject"], path, spec))
                continue
            downloaded += fetch_one(path, spec, args.reuse)
            receipt["files"][spec["path"]] = {"bytes": spec["bytes"], "sha256": verify(path, spec)}
            save_receipt()
            save_status("running")
        if args.jobs == 1 or args.metadata_only:
            print(json.dumps({"completed_subject": record["subject"],
                              "downloaded_bytes_this_call": downloaded}), flush=True)
    if signals:
        def transfer(item):
            subject, path, spec = item
            amount = fetch_one(path, spec, args.reuse)
            return subject, amount, spec, verify(path, spec)

        failures = []
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(transfer, item) for item in signals]
            for future in as_completed(futures):
                if STOP.is_set():
                    break
                try:
                    subject, amount, spec, digest = future.result()
                except Exception as error:
                    failures.append(str(error))
                    print(json.dumps({"source_transfer_failed": str(error)}), flush=True)
                    continue
                downloaded += amount
                receipt["files"][spec["path"]] = {"bytes": spec["bytes"], "sha256": digest}
                save_receipt()
                save_status("running")
                print(json.dumps({"completed_subject": subject,
                                  "downloaded_bytes_this_call": downloaded}), flush=True)
        if STOP.is_set():
            raise InterruptedError("Download stopped; verified files and partial bytes remain")
        if failures:
            raise RuntimeError(f"{len(failures)} clinical source files failed; inspect log and rerun")
    save_status("complete" if not args.metadata_only else "metadata_complete")
    finished[0] = True
    print(json.dumps({"status": "clinical_metadata_verified" if args.metadata_only else "all_51_clinical_sources_verified",
                      "downloaded_bytes_this_call": downloaded,
                      "total_source_bytes": total, "receipt": str(receipt_path)}, indent=2))


if __name__ == "__main__":
    main()
