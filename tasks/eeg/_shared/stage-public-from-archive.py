"""Maintainer-only, allowlisted export from a mixed public/private task tar.

--plan reads the tar index and the small original public task spec for its hash.
--extract writes only four declared public files to a fresh task-scoped
local:// staging directory. Never run this helper inside an Agent workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile

from prepare import FILES

SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]+\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_PUBLIC_BYTES = 32 * 1024**3
MAX_SPEC_BYTES = 4 * 1024 * 1024


def read_contract(task: Path) -> dict:
    contract = json.loads((task / "contract.json").read_text(encoding="utf-8"))
    if set(contract.get("data_files", {})) != set(FILES):
        raise ValueError("contract must declare exactly four public data files")
    for field in ("task_id", "source_task_version"):
        value = contract.get(field)
        if not isinstance(value, str) or not SAFE_COMPONENT.fullmatch(value) or value in (".", ".."):
            raise ValueError(f"unsafe {field} in contract")
    if not isinstance(contract.get("source_task_spec_sha256"), str) or not SHA256.fullmatch(contract["source_task_spec_sha256"]):
        raise ValueError("contract has no original task-spec SHA-256")
    total = 0
    for name in FILES:
        item = contract["data_files"][name]
        if (not isinstance(item, dict) or type(item.get("bytes")) is not int or
                not 0 < item["bytes"] <= MAX_PUBLIC_BYTES or
                not isinstance(item.get("sha256"), str) or not SHA256.fullmatch(item["sha256"])):
            raise ValueError(f"invalid declared public file: {name}")
        total += item["bytes"]
    if total > MAX_PUBLIC_BYTES:
        raise ValueError("declared public package exceeds the 32 GiB export cap")
    return contract


def inspect_tar(archive: tarfile.TarFile, contract: dict) -> dict:
    seen = set()
    members = {}
    private_members = 0
    for member in archive.getmembers():
        name = member.name
        parts = PurePosixPath(name).parts
        if (not name or name.startswith("/") or "\\" in name or "\x00" in name or
                not parts or name.rstrip("/") != str(PurePosixPath(name)) or
                any(part in (".", "..") for part in parts) or
                member.issym() or member.islnk() or
                not (member.isdir() or member.isfile())):
            raise ValueError(f"unsafe tar member: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate tar member: {name!r}")
        seen.add(name)
        if member.isfile() and not 0 <= member.size <= MAX_PUBLIC_BYTES:
            raise ValueError(f"oversized tar member: {name!r}")
        members[name] = member
        if parts[0] == "private":
            private_members += 1
    spec = members.get("public/task_spec.json")
    if spec is None or not spec.isfile() or not 0 < spec.size <= MAX_SPEC_BYTES:
        raise ValueError("missing or oversized public/task_spec.json")
    with archive.extractfile(spec) as stream:
        raw_spec = stream.read(MAX_SPEC_BYTES + 1)
    if len(raw_spec) != spec.size or hashlib.sha256(raw_spec).hexdigest() != contract["source_task_spec_sha256"]:
        raise ValueError("original public task spec differs from frozen SHA-256")
    for name in FILES:
        member = members.get("public/data/" + name)
        if member is None or not member.isfile() or member.size != contract["data_files"][name]["bytes"]:
            raise ValueError(f"public/data/{name} is missing, unsafe or has wrong byte count")
    return {
        "task_id": contract["task_id"],
        "source_task_version": contract["source_task_version"],
        "source_task_spec_sha256": contract["source_task_spec_sha256"],
        "public_file_count": len(FILES),
        "public_bytes": sum(contract["data_files"][name]["bytes"] for name in FILES),
        "private_members_in_source_archive": private_members,
        "private_files_staged": 0,
        "relative_staging_directory": contract["task_id"] + "/" + contract["source_task_version"],
        "status": "plan_only",
    }


def stage(task: Path, archive_path: Path, output_root: Path | None = None, *, extract: bool = False) -> dict:
    contract = read_contract(task)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("source archive must be a regular file")
    with tarfile.open(archive_path, "r:*") as archive:
        plan = inspect_tar(archive, contract)
        if not extract:
            return plan
        if output_root is None or not output_root.is_absolute():
            raise ValueError("--extract requires an absolute --output-root")
        if output_root.is_symlink():
            raise ValueError("public staging root cannot be a symlink")
        output_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        parent = output_root / contract["task_id"]
        if parent.is_symlink():
            raise ValueError("task staging parent cannot be a symlink")
        parent.mkdir(mode=0o700, exist_ok=True)
        if stat.S_IMODE(parent.stat().st_mode) != 0o700:
            raise ValueError("task staging parent must be mode 0700")
        final = parent / contract["source_task_version"]
        if final.exists() or final.is_symlink():
            raise FileExistsError("refusing to overwrite an existing public staging directory")
        lock = parent / ("." + contract["source_task_version"] + ".export.lock")
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        temporary = None
        try:
            if final.exists() or final.is_symlink():
                raise FileExistsError("public staging target appeared during export")
            temporary = Path(tempfile.mkdtemp(prefix=".public-", dir=parent))
            file_hashes = {}
            for name in FILES:
                member = archive.getmember("public/data/" + name)
                expected = contract["data_files"][name]
                target = temporary / name
                copied = 0
                h = hashlib.sha256()
                with archive.extractfile(member) as source, target.open("xb") as output:
                    for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
                        copied += len(block)
                        if copied > expected["bytes"]:
                            raise ValueError(f"public {name} exceeded declared byte count")
                        h.update(block)
                        output.write(block)
                if copied != expected["bytes"] or h.hexdigest() != expected["sha256"]:
                    raise ValueError(f"public {name} failed SHA-256 check")
                target.chmod(0o444)
                file_hashes[name] = h.hexdigest()
            complete = {
                "schema": "eeg-public-archive-export/1",
                "status": "complete",
                "task_id": contract["task_id"],
                "source_task_version": contract["source_task_version"],
                "source_task_spec_sha256": contract["source_task_spec_sha256"],
                "public_file_sha256": file_hashes,
                "private_files_staged": 0,
            }
            receipt = temporary / "complete.json"
            receipt.write_text(json.dumps(complete, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            receipt.chmod(0o600)
            if final.exists() or final.is_symlink():
                raise FileExistsError("refusing to overwrite public staging target")
            os.rename(temporary, final)
            temporary = None
            return {**plan, "status": "complete", "public_file_sha256": file_hashes,
                    "staging_directory": str(final)}
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)
            lock.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="read-only tar index and contract check")
    mode.add_argument("--extract", action="store_true", help="stage only four public files in a new 0700 directory")
    parser.add_argument("--task", required=True, help="task directory containing a frozen contract.json")
    parser.add_argument("--archive", required=True, help="owner-held mixed public/private packet master tar")
    parser.add_argument("--output-root", help="absolute, maintainer-only staging root required for --extract")
    args = parser.parse_args()
    if args.extract and not args.output_root:
        parser.error("--extract requires --output-root")
    result = stage(Path(args.task), Path(args.archive),
                   Path(args.output_root) if args.output_root else None, extract=args.extract)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
