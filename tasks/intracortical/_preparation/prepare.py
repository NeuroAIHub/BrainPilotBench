"""Maintainer-only asset plan, fetch, and verification for FALCON candidates.

This tool never creates an Agent package. ``public`` selects Train/Valid only;
``evaluator`` selects Test only. Source data are public, but the derived Test is
kept outside the Agent workspace. Download destinations must be outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MANIFEST = HERE / "assets.manifest.json"
API = "https://api.dandiarchive.org/api"
ROLES = {"public": {"train", "valid"}, "evaluator": {"test"}}


def load_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    from check_manifest import validate_manifest, validate_protocol_files
    validate_manifest(manifest)
    validate_protocol_files(manifest)
    return manifest


def select(manifest: dict, task: str, access: str, asset_ids: list[str]) -> list[dict]:
    if task not in manifest["sources"]:
        raise ValueError(f"Unknown task: {task}")
    selected = [a for a in manifest["assets"] if a["task_id"] == task and a["role"] in ROLES[access]]
    if asset_ids:
        unknown = set(asset_ids) - {a["asset_id"] for a in selected}
        if unknown:
            raise ValueError(f"Asset IDs outside {task}/{access}: {sorted(unknown)}")
        selected = [a for a in selected if a["asset_id"] in asset_ids]
    return selected


def safe_destination(path: Path) -> Path:
    path = path.resolve()
    if path == REPO or path.is_relative_to(REPO):
        raise ValueError("Data destination must be outside the Git worktree")
    for ancestor in (path, *path.parents):
        if (ancestor / ".git").exists():
            raise ValueError("Data destination must be outside every Git checkout")
    return path


def file_path(root: Path, asset: dict) -> Path:
    # The caller supplies an access-specific root. Path traversal is rejected
    # before any file write.
    relative = Path(asset["dandiset_id"]) / asset["path"]
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe DANDI asset path")
    destination = (root / relative).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Asset path escapes destination")
    return destination


def verify_one(path: Path, asset: dict) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != asset["size_bytes"]:
        raise ValueError(f"Size mismatch: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != asset["sha256"]:
        raise ValueError(f"SHA-256 mismatch: {path}")


def fetch_one(root: Path, asset: dict) -> str:
    destination = file_path(root, asset)
    if destination.exists():
        verify_one(destination, asset)
        return "already verified"
    # The metadata endpoint checks that the original asset ID still resolves to
    # precisely the frozen bytes, including for mutable draft Dandisets.
    with urlopen(f"{API}/assets/{asset['asset_id']}/", timeout=30) as response:
        live = json.load(response)
    if (live.get("path") != asset["path"] or live.get("contentSize") != asset["size_bytes"]
            or live.get("digest", {}).get("dandi:sha2-256") != asset["sha256"]):
        raise ValueError(f"Frozen asset metadata changed: {asset['asset_id']}")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if "evaluator" in root.parts:
        os.chmod(destination.parent, 0o700)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".partial-", dir=destination.parent, delete=False) as output:
            temp_path = Path(output.name)
            with urlopen(f"{API}/assets/{asset['asset_id']}/download/", timeout=60) as response:
                received = 0
                for chunk in iter(lambda: response.read(4 * 1024 * 1024), b""):
                    received += len(chunk)
                    if received > asset["size_bytes"]:
                        raise ValueError(f"Download exceeds frozen size: {asset['asset_id']}")
                    output.write(chunk)
        verify_one(temp_path, asset)
        if destination.exists():
            raise FileExistsError(destination)
        os.replace(temp_path, destination)
        return "downloaded and verified"
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "fetch", "verify", "inspect"))
    parser.add_argument("--task", required=True)
    parser.add_argument("--access", choices=tuple(ROLES), default="public")
    parser.add_argument("--asset-id", action="append", default=[])
    parser.add_argument("--all-selected", action="store_true", help="Required for bulk fetch")
    parser.add_argument("--dest", type=Path, help="Local data root outside this Git worktree")
    parser.add_argument("--limit-bytes", type=int, default=100_000_000)
    args = parser.parse_args()
    manifest = load_manifest()
    selected = select(manifest, args.task, args.access, args.asset_id)
    total = sum(a["size_bytes"] for a in selected)
    print(f"{args.task} {args.access}: {len(selected)} assets; {total} bytes; roles={sorted(ROLES[args.access])}")
    if args.command == "plan":
        by_role = {role: sum(a["size_bytes"] for a in selected if a["role"] == role)
                   for role in sorted(ROLES[args.access])}
        print(json.dumps(by_role, sort_keys=True))
        return
    if args.dest is None:
        parser.error("--dest is required for fetch, verify, and inspect")
    root = safe_destination(args.dest) / args.access
    print(f"data_root={root}")
    if args.command == "fetch":
        if not args.asset_id and not args.all_selected:
            parser.error("Choose --asset-id or explicitly pass --all-selected")
        if total > args.limit_bytes:
            parser.error(f"Selected {total} bytes exceed --limit-bytes={args.limit_bytes}")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.access == "evaluator":
            os.chmod(root, 0o700)
    for asset in selected:
        path = file_path(root, asset)
        outcome = fetch_one(root, asset) if args.command == "fetch" else (verify_one(path, asset) or "verified")
        print(f"{asset['asset_id']} {asset['role']} {outcome}")
        if args.command == "inspect":
            sys.path.insert(0, str(HERE.parent / "_shared"))
            from native import inspect_nwb
            print(json.dumps(inspect_nwb(path, asset["source_task_id"]), sort_keys=True))


if __name__ == "__main__":
    main()
