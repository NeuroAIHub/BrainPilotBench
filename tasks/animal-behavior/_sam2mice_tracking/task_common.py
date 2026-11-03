"""Trusted packet and source-lock checks for the SAM2Mice tracking task."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from sam2mice_transport import transport_metadata

TASK_ID = "sam2mice-multi-animal-tracking"
VERSION = "0.1"
PROFILE = "bpb-sam2mice-automatic-tracking-v1"
MODEL_FILES = ("model.py", "config.json", "weights.npz")
SHA = re.compile(r"^[0-9a-f]{64}$")
SEQUENCE_ID = re.compile(r"^sequence-[0-9a-f]{16}$")
ROLES = ("train", "valid", "test")


def safe_path(path: Path, *, directory: bool = False, owner: bool = False) -> None:
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symbolic path components are forbidden")
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("ordinary directory required")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("independent regular file required")
    if owner and info.st_mode & 0o077:
        raise ValueError("owner-only data permissions required")


def digest(path: Path) -> dict:
    safe_path(path)
    before = path.stat()
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            hasher.update(block)
    after = path.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError("file changed during hashing")
    return {"bytes": before.st_size, "sha256": hasher.hexdigest()}


def read_json(path: Path) -> dict:
    safe_path(path)
    if path.stat().st_size > 4_000_000:
        raise ValueError("metadata exceeds bound")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite JSON value")

    result = json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(result, dict):
        raise ValueError("JSON object required")
    return result


def encoded(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def mkdir_safe(path: Path) -> None:
    missing, cursor = [], path
    while not cursor.exists():
        if cursor.is_symlink():
            raise ValueError("dangling directory link forbidden")
        missing.append(cursor)
        if cursor.parent == cursor:
            raise ValueError("no existing directory ancestor")
        cursor = cursor.parent
    safe_path(cursor, directory=True)
    for child in reversed(missing):
        child.mkdir(mode=0o700)
    safe_path(path, directory=True)


def relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value
            or any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) or part in (".", "..")
                   for part in value.split("/"))):
        raise ValueError("unsafe relative data path")
    return value


def record(row: dict) -> tuple[str, int, str]:
    if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
        raise ValueError("file record keys differ")
    relative = relative_path(row["path"])
    if (type(row["bytes"]) is not int or row["bytes"] <= 0
            or not isinstance(row["sha256"], str) or not SHA.fullmatch(row["sha256"])):
        raise ValueError("invalid file binding")
    return relative, row["bytes"], row["sha256"]


def copy_checked(source: Path, destination: Path, row: dict) -> None:
    _, size, checksum = record(row)
    expected = {"bytes": size, "sha256": checksum}
    if digest(source) != expected:
        raise ValueError("source differs from frozen file binding")
    mkdir_safe(destination.parent)
    with source.open("rb") as reader, os.fdopen(os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
        shutil.copyfileobj(reader, writer, 4 * 1024 * 1024)
    if digest(destination) != expected or digest(source) != expected:
        raise ValueError("copied file differs from frozen binding")


def source_locks(contract: dict) -> tuple[dict, dict]:
    datasets = []
    for role, key in (("public", "public_files"), ("evaluator", "owner_files")):
        for row in contract[key]:
            relative, size, checksum = record(row)
            entry = {
                "name": role + "__" + relative.replace("/", "__"),
                "uri": f"local://tasks/animal-behavior/{TASK_ID}/{contract['revision']}/{role}/{relative}",
                "sha256": checksum, "bytes": size,
                "scope": "public" if role == "public" else "private",
                "format": "json" if relative.endswith(".json") else "npz",
            }
            if role == "public":
                entry["path"] = relative
            datasets.append(entry)
    evaluator = {
        "schema": "bpb-evaluator-source/1", "task_id": TASK_ID,
        "repo_id": "local-prepared", "revision": contract["revision"],
        "files": [{"name": "evaluator__" + row["path"].replace("/", "__"), **row}
                  for row in contract["owner_files"]],
    }
    return {"datasets": datasets}, evaluator


def validate_contract(value: dict) -> dict:
    if (value.get("schema") != "bpb-sam2mice-tracking-task-contract/1"
            or value.get("task_id") != TASK_ID or value.get("task_version") != VERSION
            or value.get("profile") != PROFILE or value.get("metric") != "mota"
            or value.get("secondary_metrics") != ["idf1"] or value.get("iou_threshold") != 0.5):
        raise ValueError("tracking task contract identity differs")
    for field in ("revision", "public_manifest_sha256", "evaluator_manifest_sha256",
                  "source_complete_sha256", "source_review_sha256", "split_review_sha256"):
        if not isinstance(value.get(field), str) or not SHA.fullmatch(value[field]):
            raise ValueError("invalid contract digest")
    revision = hashlib.sha256(bytes.fromhex(value["public_manifest_sha256"])
                              + bytes.fromhex(value["evaluator_manifest_sha256"])).hexdigest()
    if revision != value["revision"]:
        raise ValueError("content revision differs from role manifests")
    dimensions = value.get("image_size")
    if (not isinstance(dimensions, list) or len(dimensions) != 2
            or any(type(item) is not int or not 1 <= item <= 4096 for item in dimensions)):
        raise ValueError("invalid image dimensions")
    counts = value.get("counts")
    if not isinstance(counts, dict) or set(counts) != set(ROLES):
        raise ValueError("complete role counts required")
    for count in counts.values():
        if (not isinstance(count, dict) or set(count) != {"sequences", "frames"}
                or type(count["sequences"]) is not int or not 1 <= count["sequences"] <= 128
                or type(count["frames"]) is not int
                or not count["sequences"] <= count["frames"] <= count["sequences"] * 128):
            raise ValueError("invalid role counts")
    for key, field in (("public_files", "public_manifest_sha256"),
                       ("owner_files", "evaluator_manifest_sha256")):
        rows = value.get(key)
        if not isinstance(rows, list) or not rows:
            raise ValueError("missing role files")
        paths = [record(row)[0] for row in rows]
        if paths != sorted(set(paths)) or paths.count("manifest.json") != 1:
            raise ValueError("role files duplicate, unsorted or missing manifest")
        if next(row["sha256"] for row in rows if row["path"] == "manifest.json") != value[field]:
            raise ValueError("role manifest hash differs")
    public_features = {row["sha256"] for row in value["public_files"] if row["path"].endswith(".features.npz")}
    owner_features = {row["sha256"] for row in value["owner_files"] if row["path"].endswith(".features.npz")}
    if public_features & owner_features:
        raise ValueError("public/evaluator feature equivalence requires separate review")
    return value


def load_contract(task_dir: Path) -> dict:
    safe_path(task_dir, directory=True)
    if task_dir.name != TASK_ID:
        raise ValueError("tracking task directory differs")
    return validate_contract(read_json(task_dir / "contract.json"))


def verify_locks(task_dir: Path, contract: dict) -> None:
    expected_data, expected_evaluator = transport_metadata(task_dir, contract, *source_locks(contract))
    if (read_json(task_dir / "data.lock") != expected_data
            or read_json(task_dir / "evaluator.lock") != expected_evaluator):
        raise ValueError("data/evaluator lock differs from scientific content")


def exact_packet(root: Path, contract: dict, *, evaluator: bool, receipt: bool = False) -> dict:
    safe_path(root, directory=True, owner=evaluator)
    validate_contract(contract)
    records = contract["owner_files" if evaluator else "public_files"]
    expected = {row["path"] for row in records} | ({".bpb-evaluator.json"} if receipt else set())
    expected_dirs = {str(parent) for relative in expected for parent in Path(relative).parents if str(parent) != "."}
    files, directories = set(), set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("packet contains a symbolic link")
        relative = str(path.relative_to(root))
        if path.is_dir():
            directories.add(relative)
            safe_path(path, directory=True, owner=evaluator)
        else:
            files.add(relative)
            safe_path(path, owner=evaluator)
    if files != expected or directories != expected_dirs:
        raise ValueError("packet contains missing or extra paths")
    for row in records:
        relative, size, checksum = record(row)
        if digest(root / relative) != {"bytes": size, "sha256": checksum}:
            raise ValueError("packet file hash differs")
    manifest = read_json(root / "manifest.json")
    if (set(manifest) != {"schema", "task_id", "task_version", "role", "profile", "image_size", "sequences", "files"}
            or manifest["schema"] != "bpb-sam2mice-tracking-role-packet/1"
            or manifest["task_id"] != TASK_ID or manifest["task_version"] != VERSION
            or manifest["role"] != ("evaluator" if evaluator else "public")
            or manifest["profile"] != PROFILE or manifest["image_size"] != contract["image_size"]
            or manifest["files"] != [row for row in records if row["path"] != "manifest.json"]):
        raise ValueError("packet manifest identity differs")
    sequences = manifest["sequences"]
    if not isinstance(sequences, list) or not sequences:
        raise ValueError("missing packet sequences")
    identifiers, named = set(), set()
    bindings = {row["path"]: row for row in records}
    for sequence in sequences:
        if (set(sequence) != {"id", "split", "frames", "feature_path", "feature_bytes", "feature_sha256",
                             "label_path", "label_bytes", "label_sha256"}
                or not isinstance(sequence.get("id"), str) or not SEQUENCE_ID.fullmatch(sequence["id"])
                or sequence["id"] in identifiers
                or sequence["split"] not in (("test",) if evaluator else ("train", "valid"))
                or type(sequence["frames"]) is not int or not 1 <= sequence["frames"] <= 128):
            raise ValueError("invalid role sequence")
        identifiers.add(sequence["id"])
        for kind in ("feature", "label"):
            relative = relative_path(sequence[kind + "_path"])
            suffix = ".features.npz" if kind == "feature" else ".truth.npz"
            if (relative != sequence["split"] + "/" + sequence["id"] + suffix
                    or relative in named or relative not in bindings
                    or bindings[relative] != {"path": relative, "bytes": sequence[kind + "_bytes"],
                                              "sha256": sequence[kind + "_sha256"]}):
                raise ValueError("sequence/file binding differs")
            named.add(relative)
    if named != set(bindings) - {"manifest.json"}:
        raise ValueError("unreferenced packet file")
    for role in (("test",) if evaluator else ("train", "valid")):
        selected = [row for row in sequences if row["split"] == role]
        if contract["counts"][role] != {"sequences": len(selected), "frames": sum(row["frames"] for row in selected)}:
            raise ValueError("complete sequence role coverage required")
    return manifest


def _public_storage(source: Path) -> None:
    source = source.absolute()
    for parent in (source, *source.parents):
        if (parent / ".bpb-private-cache.json").exists() or (parent / ".bpb-evaluator.json").exists():
            raise ValueError("public operation cannot use evaluator storage")


def stage_public_cache(task_dir: Path, contract: dict, output: Path) -> dict:
    verify_locks(task_dir, contract)
    configured = os.environ.get("BPB_CACHE_ROOT")
    cache = Path(configured) if configured else Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "brainpilot-bench"
    safe_path(cache, directory=True)
    _public_storage(cache)
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh public packet required")
    mkdir_safe(output)
    for row in contract["public_files"]:
        copy_checked(cache / row["sha256"] / "data", output / row["path"], row)
    return exact_packet(output, contract, evaluator=False)


def stage_public_workspace(task_dir: Path, contract: dict, output: Path) -> None:
    verify_locks(task_dir, contract)
    configured = os.environ.get("BPB_PUBLIC_DATA_ROOT")
    if not configured:
        raise ValueError("BPB_PUBLIC_DATA_ROOT is required")
    source = Path(configured)
    _public_storage(source)
    exact_packet(source, contract, evaluator=False)
    if output.exists() or output.is_symlink():
        exact_packet(output, contract, evaluator=False)
        return
    mkdir_safe(output)
    for row in contract["public_files"]:
        copy_checked(source / row["path"], output / row["path"], row)
    exact_packet(output, contract, evaluator=False)


def stage_evaluator(task_dir: Path, contract: dict, source: Path, output: Path) -> dict:
    verify_locks(task_dir, contract)
    if source.name != "evaluator":
        raise ValueError("prepared /evaluator root required")
    marker = read_json(source / ".bpb-evaluator.json")
    lock = read_json(task_dir / "evaluator.lock")
    if (marker.get("schema") != "bpb-prepared-evaluator/1" or marker.get("task_id") != TASK_ID
            or marker.get("revision") != lock["revision"] or marker.get("files") != len(contract["owner_files"])
            or marker.get("evaluator_lock_sha256") != digest(task_dir / "evaluator.lock")["sha256"]):
        raise ValueError("prepared evaluator receipt differs")
    exact_packet(source, contract, evaluator=True, receipt=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh owner packet required")
    mkdir_safe(output)
    for row in contract["owner_files"]:
        copy_checked(source / row["path"], output / row["path"], row)
    return exact_packet(output, contract, evaluator=True)


def submission_dir(artifacts: Path) -> Path:
    safe_path(artifacts, directory=True)
    if {path.name for path in artifacts.iterdir()} != {"submission"}:
        raise ValueError("artifacts must contain only submission/")
    source = artifacts / "submission"
    safe_path(source, directory=True)
    if {path.name for path in source.iterdir()} != set(MODEL_FILES):
        raise ValueError("exact three-file submission required")
    for name in MODEL_FILES:
        safe_path(source / name)
    return source
