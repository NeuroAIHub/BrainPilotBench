"""Trusted role-packet and lock checks for source-only MABe22 tasks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat

from mabe_inference import MODEL_FILES, snapshot_model
from mabe_task_package import REPRESENTATION_PUBLIC_EQUIVALENT

TASKS = {"mabe22-supervised-segmentation": ("macro_f1", "BrainPilotBench-MABe22-supervised-positive-pose-valid-v1"),
         "mabe22-representation-classification": ("F1", "bpb-mabe22-paper-style-three-probe-sequence-v1")}


def read_json(path: Path) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
    with path.open(encoding="utf-8") as source:
        result = json.load(source, object_pairs_hook=unique)
    if type(result) is not dict:
        raise ValueError("JSON object required")
    return result


def safe_path(path: Path, *, directory: bool = False) -> None:
    absolute = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("symlink path component")
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("directory required")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("single-link regular file required")


def digest(path: Path) -> tuple[int, str]:
    safe_path(path)
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            checksum.update(chunk)
            size += len(chunk)
    return size, checksum.hexdigest()


def _record(item: object) -> tuple[str, int, str]:
    if type(item) is not dict or set(item) != {"path", "bytes", "sha256"}:
        raise ValueError("file record fields mismatch")
    rel, size, sha = item["path"], item["bytes"], item["sha256"]
    if (not isinstance(rel, str) or not rel or PurePosixPath(rel).is_absolute()
            or any(part in ("", ".", "..") or not all(c.isalnum() or c in "._-" for c in part)
                   for part in rel.split("/")) or type(size) is not int or size <= 0
            or not isinstance(sha, str) or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)):
        raise ValueError("unsafe file record")
    return rel, size, sha


def load_contract(task_dir: Path) -> dict:
    safe_path(task_dir, directory=True)
    contract = read_json(task_dir / "contract.json")
    task_id = task_dir.name
    if (contract.get("schema") != "bpb-mabe-task-contract/1"
            or contract.get("task_id") != task_id or contract.get("task_version") != "0.1-source"
            or task_id not in TASKS
            or (contract.get("metric"), contract.get("profile")) != TASKS[task_id]):
        raise ValueError("MABe task contract identity mismatch")
    for key in ("revision", "public_manifest_sha256", "evaluator_manifest_sha256"):
        value = contract.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("contract digest missing or malformed")
    revision = hashlib.sha256(bytes.fromhex(contract["public_manifest_sha256"])
                              + bytes.fromhex(contract["evaluator_manifest_sha256"])).hexdigest()
    if revision != contract["revision"]:
        raise ValueError("contract revision mismatch")
    for key in ("public_files", "owner_files"):
        rows = contract.get(key)
        if not isinstance(rows, list) or not rows:
            raise ValueError("contract file records missing")
        paths = [_record(row)[0] for row in rows]
        if paths != sorted(set(paths)) or "manifest.json" not in paths:
            raise ValueError("contract file paths duplicate, unsorted, or missing manifest")
    if next(row["sha256"] for row in contract["public_files"] if row["path"] == "manifest.json") != contract["public_manifest_sha256"]:
        raise ValueError("public manifest contract mismatch")
    if next(row["sha256"] for row in contract["owner_files"] if row["path"] == "manifest.json") != contract["evaluator_manifest_sha256"]:
        raise ValueError("evaluator manifest contract mismatch")
    public_equivalent = sorted({row["sha256"] for row in contract["public_files"]}
                               & {row["sha256"] for row in contract["owner_files"]})
    if task_id == "mabe22-representation-classification":
        if (public_equivalent != list(REPRESENTATION_PUBLIC_EQUIVALENT)
                or contract.get("public_equivalent_sha256") != public_equivalent):
            raise ValueError("representation public-equivalent content differs from audited pair")
        public_paths = {sha: [row["path"] for row in contract["public_files"] if row["sha256"] == sha]
                        for sha in public_equivalent}
        owner_paths = {sha: [row["path"] for row in contract["owner_files"] if row["sha256"] == sha]
                       for sha in public_equivalent}
        if (public_paths[public_equivalent[0]] != ["public/probe_profile.json"]
                or owner_paths[public_equivalent[0]] != ["public/probe_profile.json"]
                or public_paths[public_equivalent[1]] != ["public/probe_usertrain/JGC8WCVWHFGORUKI50MD.npz"]
                or len(owner_paths[public_equivalent[1]]) != 7
                or any(not path.startswith("public/probe_pose/") for path in owner_paths[public_equivalent[1]])):
            raise ValueError("audited public-equivalent paths changed")
    elif public_equivalent or "public_equivalent_sha256" in contract:
        raise ValueError("supervised task cannot declare public-equivalent content")
    return contract


def verify_locks(task_dir: Path, contract: dict) -> None:
    entries = read_json(task_dir / "data.lock").get("datasets")
    if not isinstance(entries, list):
        raise ValueError("data.lock datasets missing")
    expected = []
    for role, key in (("public", "public_files"), ("evaluator", "owner_files")):
        for row in contract[key]:
            rel, size, sha = _record(row)
            value = {"name": role + "__" + rel.replace("/", "__"),
                     "uri": f"local://tasks/animal-behavior/{contract['task_id']}/{contract['revision']}/{role}/{rel}",
                     "sha256": sha, "bytes": size,
                     "scope": "public" if role == "public" else "private",
                     "format": "json" if rel.endswith(".json") else "npz"}
            if role == "public":
                value["path"] = rel
            expected.append(value)
    if entries != expected:
        raise ValueError("data.lock differs from contract")
    evaluator_files = [{"name": "evaluator__" + row["path"].replace("/", "__"), **row}
                       for row in contract["owner_files"]]
    expected_lock = {"schema": "bpb-evaluator-source/1",
                     "task_id": contract["task_id"],
                     "repo_id": "local-prepared",
                     "revision": contract["revision"],
                     "files": evaluator_files}
    if "public_equivalent_sha256" in contract:
        expected_lock["public_equivalent_sha256"] = contract["public_equivalent_sha256"]
    if read_json(task_dir / "evaluator.lock") != expected_lock:
        raise ValueError("evaluator.lock differs from contract")


def exact_packet(root: Path, contract: dict, *, evaluator: bool,
                 receipt: bool = False) -> None:
    safe_path(root, directory=True)
    key = "owner_files" if evaluator else "public_files"
    expected = {row["path"] for row in contract[key]}
    if receipt:
        expected.add(".bpb-evaluator.json")
    found = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if found != expected or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("packet includes missing, extra, or linked files")
    for row in contract[key]:
        rel, size, sha = _record(row)
        if digest(root / rel) != (size, sha):
            raise ValueError(f"packet file mismatch: {rel}")
    manifest = read_json(root / "manifest.json")
    if (manifest.get("schema") != "bpb-mabe-role-packet/1"
            or manifest.get("task_id") != contract["task_id"]
            or manifest.get("role") != ("evaluator" if evaluator else "agent")
            or manifest.get("profile") != contract["profile"]
            or manifest.get("source_manifests") != contract["source_manifests"]
            or manifest.get("counts") != contract["counts"]
            or manifest.get("files") != [row for row in contract[key] if row["path"] != "manifest.json"]):
        raise ValueError("packet manifest/contract mismatch")


def copy_checked(source: Path, destination: Path, row: dict) -> None:
    size, sha = row["bytes"], row["sha256"]
    if digest(source) != (size, sha):
        raise ValueError("packet source file changed")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_path(destination.parent, directory=True)
    with source.open("rb") as reader, os.fdopen(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as writer:
        shutil.copyfileobj(reader, writer, 4 * 1024 * 1024)
    if digest(destination) != (size, sha):
        raise ValueError("packet copy differs from source")


def stage_public(task_dir: Path, contract: dict, output: Path) -> None:
    verify_locks(task_dir, contract)
    raw = os.environ.get("BPB_PUBLIC_DATA_ROOT")
    if not raw:
        raise ValueError("BPB_PUBLIC_DATA_ROOT is required")
    source = Path(raw)
    for ancestor in (source, *source.parents):
        if any((ancestor / marker).exists() for marker in (".bpb-private-cache.json", ".bpb-evaluator.json")):
            raise ValueError("public setup cannot use an owner cache")
    exact_packet(source, contract, evaluator=False)
    if output.exists() or output.is_symlink():
        exact_packet(output, contract, evaluator=False)
        return
    output.mkdir(mode=0o700, parents=True)
    for row in contract["public_files"]:
        copy_checked(source / row["path"], output / row["path"], row)
    exact_packet(output, contract, evaluator=False)


def stage_public_cache(task_dir: Path, contract: dict, output: Path) -> None:
    """Stage pristine Node-verified public objects for trusted Valid scoring."""
    verify_locks(task_dir, contract)
    raw = os.environ.get("BPB_CACHE_ROOT")
    root = Path(raw) if raw else Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "brainpilot-bench"
    safe_path(root, directory=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh public score packet required")
    output.mkdir(mode=0o700, parents=True)
    for row in contract["public_files"]:
        source = root / row["sha256"] / "data"
        copy_checked(source, output / row["path"], row)
    exact_packet(output, contract, evaluator=False)


def stage_evaluator(task_dir: Path, contract: dict, prepared_root: Path,
                    output: Path) -> None:
    verify_locks(task_dir, contract)
    if prepared_root.name != "evaluator":
        raise ValueError("prepared evaluator root required")
    marker = prepared_root / ".bpb-evaluator.json"
    receipt = read_json(marker)
    if (receipt.get("schema") != "bpb-prepared-evaluator/1"
            or receipt.get("task_id") != contract["task_id"]
            or receipt.get("revision") != contract["revision"]
            or receipt.get("files") != len(contract["owner_files"])
            or receipt.get("evaluator_lock_sha256") != digest(task_dir / "evaluator.lock")[1]):
        raise ValueError("prepared evaluator receipt mismatch")
    exact_packet(prepared_root, contract, evaluator=True, receipt=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh evaluator packet required")
    output.mkdir(mode=0o700, parents=True)
    for row in contract["owner_files"]:
        copy_checked(prepared_root / row["path"], output / row["path"], row)
    exact_packet(output, contract, evaluator=True)


def submission_dir(artifacts: Path) -> Path:
    safe_path(artifacts, directory=True)
    if {child.name for child in artifacts.iterdir()} != {"submission"}:
        raise ValueError("artifacts must contain only submission/")
    model = artifacts / "submission"
    if {child.name for child in model.iterdir()} != set(MODEL_FILES):
        raise ValueError("model files must be exactly model.py, config.json, weights.npz")
    snapshot_model(model, frozen=False)
    return model
