#!/usr/bin/env python3
"""Fetch only the pinned sub-02 BrainVision recording and public sidecars.

This script does not fetch the copyrighted movie, fMRI, other participants, or
any benchmark Test export. It uses hashes from the pinned OpenNeuro Git tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


TASK_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((TASK_ROOT / "source_manifest.json").read_text())
BASE = MANIFEST["representative"]["source_root_relative_directory"]
GIT_RAW = (
    "https://raw.githubusercontent.com/OpenNeuroDatasets/ds003688/"
    + MANIFEST["dataset_git_commit"]
    + "/"
)
S3_BASE = "https://s3.amazonaws.com/openneuro.org/ds003688/"


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def digest_ok(path: Path, spec: dict) -> bool:
    if not path.is_file():
        return False
    if "bytes" in spec and path.stat().st_size != spec["bytes"]:
        return False
    data = path.read_bytes()
    if "md5" in spec and hashlib.md5(data).hexdigest() != spec["md5"]:
        return False
    if "git_blob_sha1" in spec and git_blob_sha1(data) != spec["git_blob_sha1"]:
        return False
    return True


def fetch_one(destination: Path, spec: dict, url: str, max_bytes: int) -> int:
    target = destination / BASE / spec["name"]
    if target.exists():
        if not digest_ok(target, spec):
            raise ValueError(f"Existing file failed source digest: {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    if partial.exists():
        raise ValueError(f"Existing partial file needs operator review: {partial}")
    count = 0
    with urlopen(url, timeout=60) as response, partial.open("xb") as output:
        reported = response.headers.get("Content-Length")
        if reported is not None and int(reported) > max_bytes:
            raise ValueError(f"Source exceeds allowed download size: {spec['name']}")
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > max_bytes:
                raise ValueError(f"Download exceeded allowed size: {spec['name']}")
            output.write(chunk)
    if not digest_ok(partial, spec):
        raise ValueError(f"Downloaded file failed pinned source digest: {partial}")
    partial.rename(target)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--download", action="store_true", help="Fetch the pinned public source files")
    args = parser.parse_args()
    files = MANIFEST["representative"]["files"]
    limit = MANIFEST["download_limit_bytes_for_representative"]
    if not args.download:
        print(json.dumps({
            "status": "plan_only",
            "destination": str(args.destination / BASE),
            "source_signal_bytes": files["signal"]["bytes"],
            "limit_bytes": limit,
            "files": [files[key]["name"] for key in files],
        }, indent=2))
        return
    downloaded = 0
    for key in ("channels", "sidecar", "events", "header", "markers", "signal"):
        spec = files[key]
        url = (GIT_RAW if "git_blob_sha1" in spec else S3_BASE) + BASE + "/" + spec["name"]
        downloaded += fetch_one(args.destination, spec, url, limit - downloaded)
    print(json.dumps({
        "status": "source_hashes_verified",
        "subject": MANIFEST["representative"]["subject"],
        "directory": str(args.destination / BASE),
        "bytes_downloaded_this_call": downloaded,
        "signal_sha256": hashlib.sha256((args.destination / BASE / files["signal"]["name"]).read_bytes()).hexdigest(),
    }, indent=2))


if __name__ == "__main__":
    main()
