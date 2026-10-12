#!/usr/bin/env python3
"""Verify and safely stage one pinned brain-age archive into a fresh directory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from zipfile import ZipFile


CONTRACTS = {
    "agent": {
        "prefix": "agent_data",
        "sha256": "45f8b641dac566e6ed1ba52b531a87d65400addc44ce4163f4f63df34d5933cc",
        "bytes": 3729262581,
        "subjects": 449,
    },
    "evaluator": {
        "prefix": "evaluator_data",
        "sha256": "08c908acef3fd26ea3efe59b4a0eaeb7c12f1c15d3c3f1b3a617b9fdecfd3c62",
        "bytes": 930013448,
        "subjects": 112,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def checked_members(archive: ZipFile, prefix: str) -> list[tuple[object, Path | None]]:
    result = []
    seen: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        if not name or "\\" in name or "\x00" in name or name.startswith("/"):
            raise ValueError(f"unsafe archive member: {name!r}")
        parts = name.rstrip("/").split("/")
        if any(part in ("", ".", "..") for part in parts) or parts[0] != prefix:
            raise ValueError(f"archive member outside {prefix}/: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate archive member: {name!r}")
        seen.add(name)
        mode = (info.external_attr >> 16) & 0o170000
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"archive link or special member: {name!r}")
        rel = Path(*parts[1:]) if len(parts) > 1 else None
        result.append((info, rel))
    return result


def csv_ids(path: Path, expected_columns: list[str]) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_columns:
            raise ValueError(f"unexpected columns in {path.name}")
        rows = list(reader)
    ids = [row["subject_id"] for row in rows]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError(f"empty or duplicate subject IDs in {path.name}")
    return ids


def validate_staged(root: Path, role: str, expected_count: int) -> None:
    ids = csv_ids(root / "subjects.csv", ["subject_id", "image_path"])
    if len(ids) != expected_count:
        raise ValueError(f"expected {expected_count} subjects, found {len(ids)}")
    manifest = json.loads((root / "files_manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    if manifest.get("n_subjects") != expected_count or not isinstance(files, list) or len(files) != expected_count:
        raise ValueError("image manifest subject count mismatch")
    paths = set()
    for record in files:
        rel = PurePosixPath(record["image_path"])
        if len(rel.parts) != 2 or rel.parts[0] != "images" or rel.name in ("", ".", ".."):
            raise ValueError("invalid image manifest path")
        image = root / "images" / rel.name
        if not image.is_file() or image.stat().st_size != record["bytes"]:
            raise ValueError(f"missing or wrong-sized image: {rel.name}")
        paths.add(rel.name)
    if len(paths) != expected_count or {p.name for p in (root / "images").iterdir()} != paths:
        raise ValueError("duplicate or unlisted image")
    if role == "agent":
        if csv_ids(root / "ages.csv", ["subject_id", "age"]) != ids:
            raise ValueError("public ages do not match subject order")
        if (root / "labels").exists():
            raise ValueError("evaluator labels in agent archive")
    else:
        if csv_ids(root / "labels" / "true_ages.csv", ["subject_id", "age"]) != ids:
            raise ValueError("hidden ages do not match subject order")
        if (root / "ages.csv").exists():
            raise ValueError("public ages found in evaluator archive")


def stage(archive_path: Path, dest: Path, role: str) -> dict:
    contract = CONTRACTS[role]
    archive_path = archive_path.resolve(strict=True)
    dest = dest.expanduser().absolute()
    if dest.exists() or dest.is_symlink():
        raise ValueError(f"staging destination already exists: {dest}")
    if archive_path.stat().st_size != contract["bytes"] or sha256(archive_path) != contract["sha256"]:
        raise ValueError("archive bytes or SHA-256 do not match data.lock")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.parent.resolve() != dest.parent:
        raise ValueError("staging destination parent must not be a symlink")
    with tempfile.TemporaryDirectory(prefix=f".{dest.name}-staging-", dir=dest.parent) as temp:
        staging = Path(temp)
        with ZipFile(archive_path) as archive:
            members = checked_members(archive, contract["prefix"])
            for info, rel in members:
                if rel is None:
                    continue
                target = staging / rel
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                    if target.stat().st_size != info.file_size:
                        raise ValueError(f"incomplete extraction: {info.filename}")
        validate_staged(staging, role, contract["subjects"])
        receipt = {
            "role": role,
            "archive_sha256": contract["sha256"],
            "archive_bytes": contract["bytes"],
            "subjects": contract["subjects"],
            "images": contract["subjects"],
            "status": "archive_and_structure_verified",
        }
        (staging / "PREPARED.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        if os.name != "nt":
            # Agent containers may use a different UID; evaluator files remain owner-only.
            dir_mode, file_mode = (0o755, 0o644) if role == "agent" else (0o700, 0o600)
            for item in staging.rglob("*"):
                item.chmod(dir_mode if item.is_dir() else file_mode)
            staging.chmod(dir_mode)
        os.replace(staging, dest)
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--role", choices=CONTRACTS, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.archive, args.destination, args.role), sort_keys=True))


if __name__ == "__main__":
    main()
