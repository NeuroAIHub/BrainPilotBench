#!/usr/bin/env python3
"""Audit or stage exactly 152 pinned Psych-101 public train/valid files.

This tool has no Test path, private inventory, Agent runtime, or model code.
`--audit-source` and `--verify` are read-only. `--stage` exclusively creates
a fresh, owner-only local candidate; it never overwrites an existing target.
If staging fails after creation, the partial directory remains unverified for
diagnosis and the same path cannot be retried until an operator resolves it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

from responses import parse_transcript


INDEX = Path(__file__).resolve().parents[1] / "public-source-index.json"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TASK_ID = re.compile(r"psych101-[a-z0-9-]+\Z")
FILES = ("train.jsonl", "valid.jsonl")
CANDIDATE_STATUS = "public_packet_candidate_not_published_or_scored"
VERIFIED_STATUS = "public_packet_candidate_verified_not_published_or_scored"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def regular_file(path: Path) -> None:
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
        raise ValueError(f"Expected a standalone public regular file: {path}")


def real_directory(path: Path) -> Path:
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode):
        raise ValueError(f"Expected a real directory: {path}")
    return path.resolve(strict=True)


def load_index(path: Path) -> dict:
    regular_file(path)
    index = json.loads(path.read_text(encoding="utf-8"))
    if (index.get("schema") != "bpb-psych101-public-source-index/1" or
            index.get("source_package_version") != "published-20261002-v1" or
            index.get("task_count") != 76 or index.get("split_count") != 152 or
            len(index.get("tasks", [])) != 76 or
            index.get("source_public_bytes") != 859179475 or
            index.get("public_rows") != 60092 or
            index.get("public_responses") != 10681650):
        raise ValueError("Unexpected frozen public source index")
    seen_ids, seen_experiments, seen_slugs = set(), set(), set()
    for task in index["tasks"]:
        task_id, experiment, slug = task["task_id"], task["experiment_id"], task["source_slug"]
        if (not TASK_ID.fullmatch(task_id) or task_id in seen_ids or experiment in seen_experiments or
                not isinstance(experiment, str) or "/" not in experiment or not experiment.endswith(".csv") or
                slug != Path(slug).name or slug in ("", ".", "..") or slug in seen_slugs):
            raise ValueError("Duplicate or unsafe task identity in public index")
        seen_ids.add(task_id); seen_experiments.add(experiment); seen_slugs.add(slug)
        if set(task["splits"]) != {"train", "valid"}:
            raise ValueError("Unexpected split set")
        for split in ("train", "valid"):
            record = task["splits"][split]
            if (not HEX64.fullmatch(record.get("sha256", "")) or
                    any(type(record.get(key)) is not int or record[key] <= 0
                        for key in ("rows", "responses", "bytes"))):
                raise ValueError("Invalid pinned public split record")
    totals = {key: sum(task["splits"][split][key] for task in index["tasks"]
                       for split in ("train", "valid")) for key in ("rows", "responses", "bytes")}
    if totals != {"rows": index["public_rows"], "responses": index["public_responses"],
                  "bytes": index["source_public_bytes"]}:
        raise ValueError("Public index totals differ from split records")
    return index


def source_task_dir(source_root: Path, task: dict) -> Path:
    folder = source_root / task["source_slug"]
    if real_directory(folder) != folder.resolve() or source_root not in folder.resolve().parents:
        raise ValueError("Public task directory escapes source root")
    return folder


def verify_split(path: Path, expected: dict, experiment: str, *, parse_rows: bool) -> dict:
    regular_file(path)
    if path.stat().st_size != expected["bytes"]:
        raise ValueError(f"Public split byte count differs: {path}")
    h = hashlib.sha256()
    rows = responses = 0
    participants = set()
    with path.open("rb") as stream:
        for raw in stream:
            h.update(raw)
            if parse_rows:
                row = json.loads(raw)
                if set(row) != {"experiment", "participant", "text"} or row["experiment"] != experiment:
                    raise ValueError(f"Unexpected public experiment/row: {path}")
                participant = str(row["participant"])
                if participant in participants:
                    raise ValueError(f"Repeated public participant in {path}")
                participants.add(participant)
                parsed = parse_transcript(row["text"])
                if not parsed.responses:
                    raise ValueError(f"Empty marked response sequence: {path}")
                rows += 1
                responses += len(parsed.responses)
    if h.hexdigest() != expected["sha256"]:
        raise ValueError(f"Public split SHA-256 differs: {path}")
    if parse_rows and (rows, responses) != (expected["rows"], expected["responses"]):
        raise ValueError(f"Public split row/response count differs: {path}")
    return {"rows": rows, "responses": responses, "participants": participants}


def audit_source(source_path: Path, index: dict) -> dict:
    source_root = real_directory(source_path)
    if source_root.name != index["source_package_version"]:
        raise ValueError("Wrong published public package version")
    state_path = source_root / "state.json"
    regular_file(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if (state.get("schema") != "psych101-public-package-state/1" or
            state.get("version") != index["source_package_version"] or
            state.get("public_task_count") != index["task_count"]):
        raise ValueError("Public package state/version/count mismatch")
    totals = {"tasks": 0, "files": 0, "bytes": 0, "rows": 0, "responses": 0}
    for task in index["tasks"]:
        folder = source_task_dir(source_root, task)
        spec_path = folder / "spec.json"
        regular_file(spec_path)
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if (spec.get("schema") != "psych101-published-task/1" or
                spec.get("task_version") != index["source_package_version"] or
                spec.get("experiment_id") != task["experiment_id"] or
                spec.get("task_id") != "psych101/" + task["experiment_id"].removesuffix(".csv") or
                spec.get("source_public_sha256") != index["source_public_sha256"] or
                spec.get("splits") != task["splits"]):
            raise ValueError(f"Public spec differs from pinned index: {task['source_slug']}")
        groups = {}
        for split in ("train", "valid"):
            name = f"{split}.jsonl"
            path = folder / name
            if path.resolve() != folder / name:
                raise ValueError("Public split path escaped its task directory")
            checked = verify_split(path, task["splits"][split], task["experiment_id"], parse_rows=True)
            groups[split] = checked["participants"]
            totals["files"] += 1
            for key in ("bytes", "rows", "responses"):
                totals[key] += task["splits"][split][key]
        if groups["train"] & groups["valid"]:
            raise ValueError(f"Public train/valid participant overlap: {task['experiment_id']}")
        totals["tasks"] += 1
    if totals != {"tasks": 76, "files": 152, "bytes": 859179475,
                  "rows": 60092, "responses": 10681650}:
        raise ValueError("Source audit totals differ from frozen index")
    return totals


def checked_output_path(destination: Path, source_root: Path) -> Path:
    output = destination.absolute()
    if os.path.lexists(output):
        raise ValueError("Packet destination exists; choose a fresh path")
    parent = output.parent
    cursor = parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError("Packet destination has a symbolic-link ancestor")
        cursor = cursor.parent
    parent_real = real_directory(parent)
    parent_meta = parent_real.stat()
    if parent_meta.st_uid != os.getuid() or parent_meta.st_mode & 0o077:
        raise ValueError("Packet staging parent must be owned by this user and mode 0700")
    source_real = real_directory(source_root)
    candidate = parent_real / output.name
    if candidate == source_real or source_real in candidate.parents or candidate in source_real.parents:
        raise ValueError("Packet destination must be separate from published source")
    return candidate


def copy_verified(source: Path, destination: Path, expected: dict) -> None:
    regular_file(source)
    with source.open("rb") as stream, destination.open("xb") as output:
        shutil.copyfileobj(stream, output, length=8 * 1024 * 1024)
    verify_split(destination, expected, "", parse_rows=False)
    destination.chmod(0o444)


def packet_manifest(index: dict) -> dict:
    files = []
    for task in index["tasks"]:
        for split in ("train", "valid"):
            files.append({"task_id": task["task_id"], "source_experiment_id": task["experiment_id"],
                          "source_slug": task["source_slug"], "split": split,
                          "path": f"public-tasks/{task['task_id']}/{split}.jsonl",
                          **task["splits"][split]})
    return {"schema": "bpb-psych101-public-packet/2",
            "status": CANDIDATE_STATUS,
            "source_package_version": index["source_package_version"],
            "source_index_sha256": index["source_index_sha256"],
            "source_public_sha256": index["source_public_sha256"],
            "task_count": 76, "split_count": 152, "public_bytes": 859179475,
            "public_rows": 60092, "marked_responses": 10681650,
            "private_test_included": False, "files": files}


def legacy_packet_manifest(index: dict) -> dict:
    """Exact manifest expected from the already verified v1 packet."""
    manifest = packet_manifest(index)
    manifest["schema"] = "bpb-psych101-public-packet/1"
    manifest["status"] = VERIFIED_STATUS
    return manifest


def verify_packet(destination: Path, index: dict) -> dict:
    root = real_directory(destination)
    manifest_path = root / "MANIFEST.json"
    regular_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest != packet_manifest(index) and manifest != legacy_packet_manifest(index):
        raise ValueError("Packet manifest differs from frozen public selection")
    expected_paths = {"MANIFEST.json"}
    expected_directories = {"public-tasks"}
    for item in manifest["files"]:
        rel = item["path"]
        path = root / rel
        if path.resolve() != root / rel or root not in path.resolve().parents:
            raise ValueError("Packet file escaped destination")
        verify_split(path, item, item["source_experiment_id"], parse_rows=False)
        expected_paths.add(rel)
        expected_directories.add(str(Path(rel).parent))
    actual_paths, actual_directories = set(), set()
    for path in root.rglob("*"):
        rel = str(path.relative_to(root))
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            actual_directories.add(rel)
        elif stat.S_ISREG(mode):
            actual_paths.add(rel)
        else:
            raise ValueError(f"Packet contains a linked or special entry: {rel}")
    if actual_paths != expected_paths or actual_directories != expected_directories:
        raise ValueError("Packet has missing or extra files/directories")
    return {"status": VERIFIED_STATUS, "task_count": 76, "split_count": 152,
            "public_bytes": 859179475, "manifest_sha256": digest(manifest_path)}


def stage_packet(source_path: Path, destination: Path, index: dict) -> dict:
    source_root = real_directory(source_path)
    output = checked_output_path(destination, source_root)
    audit_source(source_root, index)
    os.umask(0o077)
    try:
        output.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as error:
        raise ValueError("Packet destination appeared during staging; refusing replacement") from error
    (output / "public-tasks").mkdir(mode=0o700)
    for task in index["tasks"]:
        source_dir = source_task_dir(source_root, task)
        packet_dir = output / "public-tasks" / task["task_id"]
        packet_dir.mkdir(mode=0o700)
        for split in ("train", "valid"):
            copy_verified(source_dir / f"{split}.jsonl", packet_dir / f"{split}.jsonl",
                          task["splits"][split])
    manifest_path = output / "MANIFEST.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(packet_manifest(index), ensure_ascii=False,
                                sort_keys=True, indent=2) + "\n")
    manifest_path.chmod(0o444)
    return verify_packet(output, index)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--audit-source", action="store_true")
    mode.add_argument("--stage", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--index", type=Path, default=INDEX)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    index = load_index(args.index)
    if args.plan:
        result = {"status": "plan_only_no_files_written", "source_package_version": index["source_package_version"],
                  "task_count": 76, "split_count": 152, "public_bytes": 859179475,
                  "layout": "<destination>/public-tasks/<bpb-task-id>/{train,valid}.jsonl",
                  "manifest": "<destination>/MANIFEST.json", "private_test": False}
    elif args.audit_source:
        if args.source_root is None:
            parser.error("--audit-source requires --source-root")
        result = {"status": "public_source_audited_no_files_written",
                  **audit_source(args.source_root, index)}
    elif args.stage:
        if args.source_root is None or args.destination is None:
            parser.error("--stage requires --source-root and --destination")
        result = stage_packet(args.source_root, args.destination, index)
    else:
        if args.destination is None:
            parser.error("--verify requires --destination")
        result = verify_packet(args.destination, index)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Psych-101 public packet failed: {error}", file=sys.stderr)
        raise SystemExit(1)
