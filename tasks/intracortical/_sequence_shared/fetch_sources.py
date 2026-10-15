"""Fetch exact frozen H2/B1 NWB assets with one bounded, resumable stream."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import urllib.request

from export import MANIFEST, MANIFEST_SHA, TASKS, digest, outside_git


RANGE_RE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)\Z")


def hash_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def regular_file(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def destination(root: Path, item: dict) -> Path:
    relative = Path(item["dandiset_id"]) / item["path"]
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe frozen asset path")
    access_root = root / ("evaluator" if item["role"] == "test" else "public")
    path = access_root / relative
    if not path.resolve().is_relative_to(access_root.resolve()):
        raise ValueError("Asset escapes its access directory")
    return path


def fetch(root: Path, task: str, budget: int, prior_bytes: int,
          max_new_files: int | None) -> dict:
    root = outside_git(root)
    if digest(MANIFEST) != MANIFEST_SHA:
        raise ValueError("Frozen asset manifest changed")
    manifest = json.loads(MANIFEST.read_text())
    selected = [a for a in manifest["assets"] if a["task_id"] == TASKS[task]]
    selected.sort(key=lambda a: (a["task_id"] != TASKS["h2"],
                                 {"train": 0, "valid": 1, "test": 2}[a["role"]], a["session_date"]))
    root.mkdir(parents=True, exist_ok=True)
    lock = root / f".{task}-fetch.lock"
    with lock.open("a+b") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        transferred = 0
        new_files = 0
        complete = 0
        for item in selected:
            path = destination(root, item)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if (not regular_file(path) or path.stat().st_size != item["size_bytes"] or
                        hash_file(path) != item["sha256"]):
                    raise ValueError(f"Existing frozen source differs: {item['asset_id']}")
                complete += 1
                print(json.dumps({"verified_existing": item["task_id"], "role": item["role"],
                                  "date": item["session_date"]}), flush=True)
                continue
            if max_new_files is not None and new_files >= max_new_files:
                break
            partial = path.with_suffix(".download-part")
            if partial.exists() and not regular_file(partial):
                raise ValueError("Partial source is not a unique regular file")
            offset = partial.stat().st_size if partial.exists() else 0
            if offset < 0 or offset > item["size_bytes"]:
                raise ValueError("Partial source has an invalid size")
            if offset == item["size_bytes"]:
                if hash_file(partial) != item["sha256"]:
                    raise ValueError("Complete partial source SHA-256 differs")
                os.chmod(partial, 0o600 if item["role"] == "test" else 0o644)
                partial.replace(path)
                complete += 1
                new_files += 1
                print(json.dumps({"recovered_complete_partial": item["task_id"],
                                  "role": item["role"], "date": item["session_date"]}), flush=True)
                continue
            if prior_bytes + transferred + (item["size_bytes"] - offset) > budget:
                raise ValueError("Remaining network transfer exceeds byte budget")
            headers = {"User-Agent": "BrainPilotBench-frozen-asset-fetch/1"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(
                f"https://api.dandiarchive.org/api/assets/{item['asset_id']}/download/", headers=headers)
            deadline = time.monotonic() + 7200
            with urllib.request.urlopen(request, timeout=120) as response:
                if offset:
                    match = RANGE_RE.fullmatch(response.headers.get("Content-Range", ""))
                    if (response.status != 206 or match is None or
                            (int(match[1]), int(match[2]), int(match[3])) !=
                            (offset, item["size_bytes"] - 1, item["size_bytes"])):
                        raise ValueError("Server did not honor the exact asset Range")
                elif response.status != 200:
                    raise ValueError("Unexpected full asset response status")
                reported_length = response.headers.get("Content-Length")
                if (reported_length is not None and
                        int(reported_length) != item["size_bytes"] - offset):
                    raise ValueError("HTTP body length differs from frozen asset remainder")
                with partial.open("ab" if partial.exists() else "xb") as out:
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Per-file transfer exceeded two hours")
                        block = response.read(4 * 1024 * 1024)
                        if not block:
                            break
                        transferred += len(block)
                        if (prior_bytes + transferred > budget or
                                out.tell() + len(block) > item["size_bytes"]):
                            raise ValueError("Transfer exceeded frozen size or network budget")
                        out.write(block)
            if partial.stat().st_size != item["size_bytes"]:
                raise ValueError(f"Incomplete HTTP body for frozen source: {item['asset_id']}")
            if hash_file(partial) != item["sha256"]:
                raise ValueError(f"Downloaded source SHA-256 differs: {item['asset_id']}")
            os.chmod(partial, 0o600 if item["role"] == "test" else 0o644)
            partial.replace(path)
            complete += 1
            new_files += 1
            print(json.dumps({"downloaded": item["task_id"], "role": item["role"],
                              "date": item["session_date"], "bytes": item["size_bytes"],
                              "network_bytes_this_run": transferred}), flush=True)
        return {"selected": len(selected), "complete": complete, "new_files": new_files,
                "network_bytes_this_run": transferred, "network_bytes_including_prior": transferred + prior_bytes,
                "byte_budget": budget}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=("h2", "b1"))
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--network-byte-budget", type=int, default=3_000_000_000)
    parser.add_argument("--prior-network-bytes", type=int, default=0)
    parser.add_argument("--max-new-files", type=int)
    args = parser.parse_args()
    if args.network_byte_budget <= 0 or args.prior_network_bytes < 0 or args.max_new_files is not None and args.max_new_files < 0:
        parser.error("Invalid transfer limits")
    print(json.dumps(fetch(args.source_root, args.task, args.network_byte_budget,
                           args.prior_network_bytes, args.max_new_files), sort_keys=True))


if __name__ == "__main__":
    main()
