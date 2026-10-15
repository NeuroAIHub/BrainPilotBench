"""Freeze public FALCON asset metadata; this script never downloads NWB data.

Source scorer: https://github.com/snel-repo/falcon-challenge/tree/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f
The DANDI metadata API is public. Draft versions are bound by individual asset IDs,
SHA-256 digests, sizes, and this snapshot, not by the mutable word "draft" alone.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.request import urlopen


API = "https://api.dandiarchive.org/api"
SOURCE_SHA = "770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f"
SOURCES = {
    "falcon-h1-reach-grasp": ("h1", "000954", "draft", "19250120", r"ses-(\d{8})T", (5, 1, 7)),
    "falcon-h2-handwriting": ("h2", "000950", "0.241029.1403", "20230228", r"ses-(\d{8})", (20, 1, 5)),
    "falcon-m1-emg": ("m1", "000941", "0.241029.1405", "20120928", r"ses-(\d{8})", (3, 1, 3)),
    "falcon-m2-finger-velocity": ("m2", "000953", "draft", "2020-10-28", r"ses-(\d{4}-\d{2}-\d{2})", (3, 1, 4)),
    "falcon-b1-birdsong": ("b1", "001046", "draft", "20210628", r"ses-(\d{8})", (2, 1, 3)),
}


def read_json(url: str) -> dict:
    with urlopen(url, timeout=30) as response:
        return json.load(response)


def list_assets(dandiset: str, version: str) -> list[dict]:
    url = f"{API}/dandisets/{dandiset}/versions/{version}/assets/?page_size=100"
    assets = []
    expected = None
    while url:
        page = read_json(url)
        expected = page["count"]
        assets.extend(page["results"])
        url = page["next"]
    if len(assets) != expected:
        raise ValueError(f"{dandiset}: listed {len(assets)} assets, expected {expected}")
    return assets


def detailed_asset(item: dict) -> dict:
    metadata = read_json(f"{API}/assets/{item['asset_id']}/")
    digest = metadata.get("digest", {})
    sha = digest.get("dandi:sha2-256")
    if not sha or len(sha) != 64:
        raise ValueError(f"No SHA-256 for asset {item['asset_id']}")
    if metadata["path"] != item["path"] or metadata["contentSize"] != item["size"]:
        raise ValueError(f"Asset metadata changed during listing: {item['asset_id']}")
    return {
        "asset_id": item["asset_id"],
        "path": item["path"],
        "size_bytes": item["size"],
        "sha256": sha,
        "dandi_etag": digest.get("dandi:dandi-etag"),
    }


def build_manifest() -> dict:
    assets = []
    sources = {}
    for task_id, (task, dandiset, version, valid_date, date_regex, expected) in SOURCES.items():
        listing = list_assets(dandiset, version)
        selected = []
        excluded_minival = 0
        for item in listing:
            path = item["path"]
            if "minival" in path:
                excluded_minival += 1
                continue
            if "held-in-calib" in path:
                split = "held_in"
            elif "held-out-calib" in path:
                split = "held_out"
            else:
                raise ValueError(f"Unrecognized asset role: {path}")
            match = re.search(date_regex, path)
            if not match:
                raise ValueError(f"Missing session date: {path}")
            date = match.group(1)
            role = "test" if split == "held_out" else "valid" if date == valid_date else "train"
            selected.append((item, date, role))
        held_in_dates = {d for _, d, role in selected if role != "test"}
        if valid_date != max(held_in_dates):
            raise ValueError(f"{task_id}: validation must be final held-in date")
        dates = {role: {d for _, d, r in selected if r == role} for role in ("train", "valid", "test")}
        actual = tuple(len(dates[role]) for role in ("train", "valid", "test"))
        if actual != expected:
            raise ValueError(f"{task_id}: date counts {actual}, expected {expected}")
        if len(set.union(*dates.values())) != sum(actual):
            raise ValueError(f"{task_id}: date occurs in multiple roles")
        with ThreadPoolExecutor(max_workers=12) as pool:
            detail = list(pool.map(detailed_asset, [item for item, _, _ in selected]))
        for metadata, (_, date, role) in zip(detail, selected):
            assets.append({"task_id": task_id, "source_task_id": task, "dandiset_id": dandiset,
                           "version": version, "session_date": date, "role": role, **metadata})
        sources[task_id] = {
            "dandiset_id": dandiset,
            "version": version,
            "version_kind": "published" if version != "draft" else "mutable_draft_asset_snapshot",
            "valid_date": valid_date,
            "dates": {k: sorted(v) for k, v in dates.items()},
            "excluded_minival_files": excluded_minival,
            "bytes_by_role": {role: sum(a["size_bytes"] for a in assets if a["task_id"] == task_id and a["role"] == role)
                              for role in ("train", "valid", "test")},
        }
    assets.sort(key=lambda a: (a["task_id"], a["role"], a["session_date"], a["path"]))
    seen = {}
    for asset in assets:
        key = (asset["task_id"], asset["sha256"])
        if key in seen and seen[key] != asset["role"]:
            raise ValueError(f"Duplicate content across roles: {asset['path']}")
        seen[key] = asset["role"]
    return {
        "schema": "bpb-falcon-public-asset-manifest/1",
        "profile": "bpb-falcon-public-derived-cross-session-zs-v1",
        "upstream_source_sha": SOURCE_SHA,
        "snapshot_utc": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "assets": assets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Frozen manifest already exists: {args.output}; choose a new output path")
    manifest = build_manifest()
    # A frozen source snapshot is never silently replaced by a newer draft.
    with args.output.open("x") as output:
        output.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    for task_id, source in manifest["sources"].items():
        print(task_id, source["bytes_by_role"], f"excluded_minival={source['excluded_minival_files']}")


if __name__ == "__main__":
    main()
