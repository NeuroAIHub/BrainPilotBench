"""Build or materialize source-only CalMS locks and a local:// delivery tree.

This is a maintainer preparation tool. It never copies raw ZIPs into tasks or
Agent workspaces. All source NPZ files are independently copied, not linked.
In a clone with checked-in locks, --materialize-only verifies their exact
planned contents and restores the local tree without rewriting metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from calms_family_prepare import verify_prepared as verify_family
from calms_prepare import verify_prepared as verify_task1


TASKS = {
    "calms21-classic-classification": ("task1", "classic-three-behavior-F1"),
    "calms21-annotation-style-transfer": ("task2", "five-annotator-equal-mean-F1"),
    "calms21-few-shot-behavior": ("task3", "seven-binary-positive-F1-private-only"),
}
DOMAIN = "animal-behavior"


def _digest(path: Path) -> tuple[int, str]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
        raise ValueError(f"regular single-link source required: {path}")
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            size += len(block)
            h.update(block)
    return size, h.hexdigest()


def _unique_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _write_json(path: Path, value: object) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _files(root: Path, expected: set[str]) -> list[str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source subtree must be a directory")
    found = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if found != expected or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("source subtree files differ from manifest")
    return sorted(found)


def _copy_one(source: Path, destination: Path, size: int, sha: str) -> None:
    if _digest(source) != (size, sha):
        raise ValueError(f"source file changed: {source}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for part in (destination.parent, *destination.parent.parents):
        if part.is_symlink():
            raise ValueError("delivery symlink ancestor")
    with source.open("rb") as reader, os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
        shutil.copyfileobj(reader, writer, length=4 * 1024 * 1024)
    if _digest(destination) != (size, sha):
        raise ValueError("delivery copy differs from source")


def _verify_delivery(destination: Path, public: list[dict], owner: list[dict]) -> None:
    """Accept only the complete immutable revision, including directory modes."""
    expected_files = {"public/" + item["path"]: (item["bytes"], item["sha256"]) for item in public}
    expected_files.update({"evaluator/" + item["path"]: (item["bytes"], item["sha256"])
                           for item in owner})
    expected_dirs = {"public", "evaluator"}
    for relative in expected_files:
        parent = Path(relative).parent
        while str(parent) != ".":
            expected_dirs.add(str(parent))
            parent = parent.parent
    for part in (destination, *destination.parents):
        if part.is_symlink():
            raise ValueError("delivery symlink ancestor")
    if not destination.is_dir() or stat.S_IMODE(destination.lstat().st_mode) != 0o700:
        raise ValueError("delivery revision must be a private 0700 directory")
    found_files, found_dirs = set(), set()
    for path in destination.rglob("*"):
        relative = str(path.relative_to(destination))
        if path.is_symlink():
            raise ValueError("delivery contains a symlink")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("delivery directory is not 0700")
            found_dirs.add(relative)
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("delivery file must be an independent 0600 file")
            expected = expected_files.get(relative)
            if expected is None or _digest(path) != expected:
                raise ValueError(f"delivery file differs from frozen metadata: {relative}")
            found_files.add(relative)
        else:
            raise ValueError("delivery contains a special file")
    if found_files != set(expected_files) or found_dirs != expected_dirs:
        raise ValueError("delivery revision has missing or extra files/directories")


def build(task_dir: Path, prepared: Path, local_root: Path, *, materialize_only: bool = False) -> dict:
    os.umask(0o077)
    task_id = task_dir.name
    if task_id not in TASKS:
        raise ValueError("unsupported CalMS task directory")
    task, profile = TASKS[task_id]
    (verify_task1 if task == "task1" else verify_family)(prepared, include_owner=True)
    public_root, owner_root = prepared / "public", prepared / "owner"
    public = _unique_json(public_root / "manifest.json")
    owner = _unique_json(owner_root / "test-manifest.json")
    if public.get("task") != task or owner.get("task") != task:
        raise ValueError("prepared source task mismatch")
    _, public_sha = _digest(public_root / "manifest.json")
    _, owner_sha = _digest(owner_root / "test-manifest.json")
    revision = hashlib.sha256(bytes.fromhex(public_sha) + bytes.fromhex(owner_sha)).hexdigest()
    public_expected = {"manifest.json"} | {f"{split}/{row['file']}" for split in ("train", "valid")
                                    for row in public["splits"][split]}
    owner_expected = {"test-manifest.json"} | {f"test/{row['file']}" for row in owner["sequences"]}
    public_files = _files(public_root, public_expected)
    owner_files = _files(owner_root, owner_expected)
    prefix = f"tasks/{DOMAIN}/{task_id}/{revision}"
    data_entries = []
    contract_public, contract_owner, evaluator_files = [], [], []
    for rel in public_files:
        size, sha = _digest(public_root / rel)
        name = "public__" + rel.replace("/", "__")
        data_entries.append({"name": name, "uri": f"local://{prefix}/public/{rel}",
                             "sha256": sha, "bytes": size, "scope": "public",
                             "format": "json" if rel.endswith(".json") else "npz",
                             "path": f"public/{rel}"})
        contract_public.append({"path": rel, "sha256": sha, "bytes": size})
    for rel in owner_files:
        size, sha = _digest(owner_root / rel)
        name = "evaluator__" + rel.replace("/", "__")
        data_entries.append({"name": name, "uri": f"local://{prefix}/evaluator/{rel}",
                             "sha256": sha, "bytes": size, "scope": "private",
                             "format": "json" if rel.endswith(".json") else "npz"})
        item = {"name": name, "path": rel, "sha256": sha, "bytes": size}
        evaluator_files.append(item)
        contract_owner.append({"path": rel, "sha256": sha, "bytes": size})
    source_sha = public["source_sha256"]
    if owner["source_sha256"] != source_sha:
        raise ValueError("source SHA mismatch")
    contract = {
        "schema": "bpb-calms21-task-contract/1", "task_id": task_id,
        "task_version": "0.1-source", "source_task": task,
        "source_sha256": source_sha, "source_role": "official Train/Test; derived Valid from official Train",
        "public_manifest_sha256": public_sha, "owner_manifest_sha256": owner_sha,
        "revision": revision, "revision_rule": "sha256(raw32(public_manifest_sha256) || raw32(owner_manifest_sha256))",
        "profile": profile, "metric": "F1", "public_counts": public["counts"],
        "owner_test_counts": owner["counts"],
        "validation_unavailable_groups": public.get("validation_unavailable_groups", []),
        "public_files": contract_public, "owner_files": contract_owner,
        "groups": list(public.get("vocab_by_group", {"annotator-id_0": public.get("vocab", {})})),
    }
    evaluator_lock = {"schema": "bpb-evaluator-source/1", "task_id": task_id,
                      "repo_id": "local-prepared", "revision": revision, "files": evaluator_files}
    if materialize_only:
        if task_dir.is_symlink() or not task_dir.is_dir():
            raise ValueError("--materialize-only requires an existing plain task directory")
    else:
        task_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    planned = {"data.lock": {"datasets": data_entries}, "evaluator.lock": evaluator_lock,
               "contract.json": contract}
    present = {name for name in planned if (task_dir / name).exists() or (task_dir / name).is_symlink()}
    if present and present != set(planned):
        raise ValueError("partial checked-in CalMS metadata; refusing materialization")
    if materialize_only and not present:
        raise ValueError("--materialize-only requires all three checked-in metadata files")
    if present:
        for name, expected in planned.items():
            path = task_dir / name
            _digest(path)
            if _unique_json(path) != expected:
                raise ValueError(f"checked-in {name} differs from verified prepared source")
    destination = local_root / prefix
    if destination.exists() or destination.is_symlink():
        _verify_delivery(destination, contract_public, contract_owner)
        delivery_state = "reused_verified"
    else:
        for part in (destination.parent, *destination.parent.parents):
            if part.is_symlink():
                raise ValueError("delivery symlink ancestor")
        destination.mkdir(mode=0o700, parents=True)
        for rel in public_files:
            item = next(entry for entry in contract_public if entry["path"] == rel)
            _copy_one(public_root / rel, destination / "public" / rel, item["bytes"], item["sha256"])
        for rel in owner_files:
            item = next(entry for entry in contract_owner if entry["path"] == rel)
            _copy_one(owner_root / rel, destination / "evaluator" / rel, item["bytes"], item["sha256"])
        _verify_delivery(destination, contract_public, contract_owner)
        delivery_state = "created_verified"
    if not present:
        for name, value in planned.items():
            _write_json(task_dir / name, value)
    return {"task_id": task_id, "revision": revision, "local_root": str(local_root.absolute()),
            "delivery": str(destination.absolute()), "public_files": len(public_files),
            "owner_files": len(owner_files), "source_sha256": source_sha,
            "metadata": "reused_unchanged" if present else "created",
            "delivery_state": delivery_state}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--materialize-only", action="store_true",
                        help="require matching checked-in locks; copy or verify local:// data only")
    args = parser.parse_args()
    print(json.dumps(build(args.task_dir, args.prepared, args.local_root,
                           materialize_only=args.materialize_only), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
