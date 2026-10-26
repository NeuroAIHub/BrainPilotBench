"""Build role-separated, source-only MABe22 local delivery packets and locks.

This maintainer tool copies only verified numeric NPZ and JSON files. The
object NPY/H5 source cache is never part of an Agent or evaluator packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

TASKS = ("mabe22-supervised-segmentation", "mabe22-representation-classification")
SOURCE = "tasks/animal-behavior"
REPRESENTATION_PUBLIC_EQUIVALENT = (
    "571a1655db4a02e44dd5c88ba228b785e84ecb7c4b2d9123d7bca7a3c94c4eca",
    "f8c696049cf6244e3f39c5cd6e88b8b425fbaf18b2e9e56610871d1e27e2299e",
)


def digest(path: Path) -> tuple[int, str]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
        raise ValueError(f"single-link regular file required: {path}")
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(4 * 1024 * 1024), b""):
            checksum.update(chunk)
            size += len(chunk)
    return size, checksum.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write_new(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "wb") as writer:
        writer.write(content)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if type(value) is not dict:
        raise ValueError(f"object JSON required: {path}")
    return value


def record(source: Path, rel: str, expected_sha: str | None = None) -> dict:
    if rel.startswith("/") or any(part in ("", ".", "..") for part in rel.split("/")):
        raise ValueError("unsafe packet path")
    size, sha = digest(source)
    if expected_sha and sha != expected_sha:
        raise ValueError(f"prepared source digest mismatch: {rel}")
    return {"path": rel, "bytes": size, "sha256": sha, "source": str(source)}


def _supervised(prepared: Path) -> tuple[list[dict], list[dict], dict]:
    split = read_json(prepared / "mabe_finetune_split.json")["splits"]
    if {role: len(ids) for role, ids in split.items()} != {"train": 54, "val": 11, "test": 43}:
        raise ValueError("supervised split changed")
    pose = read_json(prepared / "pose_preparation_manifest.json")
    labels = read_json(prepared / "label_extraction_manifest.json")
    public, evaluator = [], []
    for role in ("train", "val", "test"):
        for video_id in split[role]:
            entry = pose["files"].get(video_id)
            if not entry or entry["role"] != role:
                raise ValueError("pose manifest/split mismatch")
            source = prepared / entry["path"]
            rel = f"public/pose/{role}/{video_id}.npz"
            item = record(source, rel, entry["sha256"])
            (evaluator if role == "test" else public).append(item)
    for role in ("train", "val", "test"):
        entry = labels["outputs"][role]
        source = prepared / entry["path"]
        rel = ("owner/test_labels.npz" if role == "test" else f"public/{role}_labels.npz")
        (evaluator if role == "test" else public).append(record(source, rel, entry["sha256"]))
    # The trusted runner and scorer use these metadata files inside the
    # evaluator root, never in the Agent development workspace.
    for name in ("pose_preparation_manifest.json", "pose_source_manifest.json",
                 "mabe_finetune_split.json", "label_extraction_manifest.json"):
        evaluator.append(record(prepared / name, name))
    context = {"profile": "BrainPilotBench-MABe22-supervised-positive-pose-valid-v1",
               "metric": "macro_f1", "counts": {key: len(value) for key, value in split.items()},
               "classes": labels["class_order"],
               "source_manifests": {name: digest(prepared / name)[1] for name in
                                    ("pose_preparation_manifest.json", "label_extraction_manifest.json")}}
    return public, evaluator, context


def _representation(prepared: Path) -> tuple[list[dict], list[dict], dict]:
    profile = read_json(prepared / "public/probe_profile.json")
    probe = read_json(prepared / "probe_preparation_manifest.json")
    usertrain = read_json(prepared / "usertrain_preparation_manifest.json")
    if (profile.get("name") != "BrainPilotBench-MABe22-six-classification-sequence-probe-v1"
            or len(probe["pose_sha256_by_video"]) != 1830 or usertrain["videos"] != 784
            or usertrain["schema"] != "bpb-mabe-usertrain-preparation/2"):
        raise ValueError("representation prepared source mismatch")
    public, evaluator = [], []
    for video_id, sha in sorted(usertrain["files"].items()):
        public.append(record(prepared / "public/probe_usertrain" / f"{video_id}.npz",
                             f"public/probe_usertrain/{video_id}.npz", sha))
    for video_id, sha in sorted(probe["pose_sha256_by_video"].items()):
        evaluator.append(record(prepared / "public/probe_pose" / f"{video_id}.npz",
                                f"public/probe_pose/{video_id}.npz", sha))
    for key, entry in sorted(probe["label_files"].items()):
        task, role = key.split("/")
        rel = (f"evaluator/probe_labels/{task}_{role}.npz" if role == "SubmissionTrain"
               else f"owner/probe_labels/{task}_{role}.npz")
        if entry["path"] != rel:
            raise ValueError("probe label role path mismatch")
        evaluator.append(record(prepared / entry["path"], rel, entry["sha256"]))
    # The public profile lists sequence memberships but never label values.
    # The evaluator has a separate verified copy for probe fitting.
    public.append(record(prepared / "public/probe_profile.json", "public/probe_profile.json",
                         probe["profile_sha256"]))
    evaluator.append(record(prepared / "public/probe_profile.json", "public/probe_profile.json",
                            probe["profile_sha256"]))
    evaluator.append(record(prepared / "probe_preparation_manifest.json",
                            "probe_preparation_manifest.json"))
    context = {"profile": "bpb-mabe22-paper-style-three-probe-sequence-v1", "metric": "F1",
               "counts": {"usertrain": 784, "submission": 1830, "probe_targets": 6},
               "source_manifests": {"probe_preparation_manifest.json": digest(prepared / "probe_preparation_manifest.json")[1],
                                    "usertrain_preparation_manifest.json": digest(prepared / "usertrain_preparation_manifest.json")[1],
                                    "probe_profile.json": probe["profile_sha256"]}}
    return public, evaluator, context


def _manifest(task_id: str, role: str, rows: list[dict], context: dict) -> bytes:
    listed = [{key: item[key] for key in ("path", "bytes", "sha256")} for item in rows]
    return json_bytes({"schema": "bpb-mabe-role-packet/1", "task_id": task_id,
                       "role": role, "profile": context["profile"],
                       "source_manifests": context["source_manifests"],
                       "counts": context["counts"], "files": listed})


def plan(task_id: str, prepared: Path) -> dict:
    if task_id not in TASKS:
        raise ValueError("unsupported MABe task")
    public, evaluator, context = ((_supervised if task_id == TASKS[0] else _representation)(prepared))
    for group in (public, evaluator):
        group.sort(key=lambda item: item["path"])
        paths = [item["path"] for item in group]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate packet path")
    public_manifest = _manifest(task_id, "agent", public, context)
    evaluator_manifest = _manifest(task_id, "evaluator", evaluator, context)
    public_sha = hashlib.sha256(public_manifest).hexdigest()
    evaluator_sha = hashlib.sha256(evaluator_manifest).hexdigest()
    revision = hashlib.sha256(bytes.fromhex(public_sha) + bytes.fromhex(evaluator_sha)).hexdigest()
    return {"task_id": task_id, "public": public, "evaluator": evaluator,
            "public_manifest": public_manifest, "evaluator_manifest": evaluator_manifest,
            "public_manifest_sha256": public_sha, "evaluator_manifest_sha256": evaluator_sha,
            "revision": revision, **context}


def copy_checked(source: Path, destination: Path, item: dict) -> None:
    if digest(source) != (item["bytes"], item["sha256"]):
        raise ValueError("source changed during delivery")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(path.is_symlink() for path in (destination.parent, *destination.parent.parents)):
        raise ValueError("symlink destination ancestor")
    with source.open("rb") as reader, os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
        shutil.copyfileobj(reader, writer, 4 * 1024 * 1024)
    if digest(destination) != (item["bytes"], item["sha256"]):
        raise ValueError("delivery copy mismatch")


def _metadata(result: dict) -> dict[str, bytes]:
    task_id, revision = result["task_id"], result["revision"]
    prefix = f"{SOURCE}/{task_id}/{revision}"
    public = [*result["public"], {"path": "manifest.json", "bytes": len(result["public_manifest"]),
                                  "sha256": result["public_manifest_sha256"]}]
    evaluator = [*result["evaluator"], {"path": "manifest.json", "bytes": len(result["evaluator_manifest"]),
                                        "sha256": result["evaluator_manifest_sha256"]}]
    public.sort(key=lambda item: item["path"])
    evaluator.sort(key=lambda item: item["path"])
    data_entries = []
    for role, rows in (("public", public), ("evaluator", evaluator)):
        for item in rows:
            rel = item["path"]
            entry = {"name": f"{role}__" + rel.replace("/", "__"),
                     "uri": f"local://{prefix}/{role}/{rel}",
                     "sha256": item["sha256"], "bytes": item["bytes"],
                     "scope": "public" if role == "public" else "private",
                     "format": "json" if rel.endswith(".json") else "npz"}
            if role == "public":
                entry["path"] = rel
            data_entries.append(entry)
    evaluator_files = [{"name": "evaluator__" + item["path"].replace("/", "__"),
                        **{key: item[key] for key in ("path", "sha256", "bytes")}} for item in evaluator]
    public_equivalent = sorted({row["sha256"] for row in public}
                               & {row["sha256"] for row in evaluator})
    if task_id == TASKS[1]:
        if public_equivalent != list(REPRESENTATION_PUBLIC_EQUIVALENT):
            raise ValueError("unexpected representation public/evaluator byte equivalence")
        public_paths = {sha: [row["path"] for row in public if row["sha256"] == sha]
                        for sha in public_equivalent}
        evaluator_paths = {sha: [row["path"] for row in evaluator if row["sha256"] == sha]
                           for sha in public_equivalent}
        if (public_paths[public_equivalent[0]] != ["public/probe_profile.json"]
                or evaluator_paths[public_equivalent[0]] != ["public/probe_profile.json"]
                or public_paths[public_equivalent[1]] != ["public/probe_usertrain/JGC8WCVWHFGORUKI50MD.npz"]
                or len(evaluator_paths[public_equivalent[1]]) != 7
                or any(not path.startswith("public/probe_pose/") for path in evaluator_paths[public_equivalent[1]])):
            raise ValueError("public equivalent content paths differ from audited profile/all-zero pose")
    elif public_equivalent:
        raise ValueError("unexpected supervised public/evaluator byte equivalence")
    contract = {"schema": "bpb-mabe-task-contract/1", "task_id": task_id,
                "task_version": "0.1-source", "revision": revision,
                "revision_rule": "sha256(raw32(public_manifest_sha256) || raw32(evaluator_manifest_sha256))",
                "public_manifest_sha256": result["public_manifest_sha256"],
                "evaluator_manifest_sha256": result["evaluator_manifest_sha256"],
                "profile": result["profile"], "metric": result["metric"],
                "counts": result["counts"], "source_manifests": result["source_manifests"],
                "public_files": [{key: item[key] for key in ("path", "sha256", "bytes")} for item in public],
                "owner_files": [{key: item[key] for key in ("path", "sha256", "bytes")} for item in evaluator]}
    evaluator_lock = {"schema": "bpb-evaluator-source/1", "task_id": task_id,
                      "repo_id": "local-prepared", "revision": revision,
                      "files": evaluator_files}
    if task_id == TASKS[1]:
        contract["public_equivalent_sha256"] = public_equivalent
        evaluator_lock["public_equivalent_sha256"] = public_equivalent
    return {"data.lock": json_bytes({"datasets": data_entries}),
            "evaluator.lock": json_bytes(evaluator_lock),
            "contract.json": json_bytes(contract)}


def _verify_delivery(destination: Path, result: dict) -> None:
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError("existing delivery must be a real directory")
    expected = {
        f"{role}/{item['path']}": (item["bytes"], item["sha256"])
        for role in ("public", "evaluator") for item in result[role]
    }
    for role in ("public", "evaluator"):
        manifest = result[f"{role}_manifest"]
        expected[f"{role}/manifest.json"] = (len(manifest), result[f"{role}_manifest_sha256"])
    children = list(destination.rglob("*"))
    if any(child.is_symlink() for child in children):
        raise ValueError("delivery contains a symlink")
    found = {str(path.relative_to(destination)) for path in children if path.is_file()}
    if found != set(expected):
        raise ValueError("existing delivery has missing or extra files")
    for rel, binding in expected.items():
        if digest(destination / rel) != binding:
            raise ValueError(f"existing delivery file differs from frozen binding: {rel}")


def deliver(task_dir: Path, local_root: Path, result: dict,
            *, materialize_only: bool = False) -> dict:
    metadata = _metadata(result)
    present = {name for name in metadata if (task_dir / name).exists() or (task_dir / name).is_symlink()}
    if present and present != set(metadata):
        raise ValueError("partial task metadata; preserve and repair the frozen lock set")
    if present:
        for name, expected in metadata.items():
            path = task_dir / name
            if digest(path) != (len(expected), hashlib.sha256(expected).hexdigest()) or path.read_bytes() != expected:
                raise ValueError(f"checked-in task metadata differs from prepared source: {name}")
        metadata_mode = "verified-existing"
    elif materialize_only:
        raise ValueError("materialize-only requires all three checked-in task metadata files")
    else:
        metadata_mode = "created"

    task_id, revision = result["task_id"], result["revision"]
    destination = local_root / SOURCE / task_id / revision
    if destination.exists() or destination.is_symlink():
        _verify_delivery(destination, result)
        delivery_mode = "verified-existing"
    else:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".mabe-materialize-", dir=destination.parent))
        for role in ("public", "evaluator"):
            for item in result[role]:
                copy_checked(Path(item["source"]), staging / role / item["path"], item)
            write_new(staging / role / "manifest.json", result[f"{role}_manifest"])
        _verify_delivery(staging, result)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("delivery revision appeared during materialization")
        os.rename(staging, destination)
        delivery_mode = "materialized"

    if not present:
        task_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
        for name, content in metadata.items():
            write_new(task_dir / name, content, 0o644)
    return {"task_id": task_id, "revision": revision,
            "delivery": str(destination.absolute()), "public_files": len(result["public"]) + 1,
            "evaluator_files": len(result["evaluator"]) + 1,
            "public_manifest_sha256": result["public_manifest_sha256"],
            "evaluator_manifest_sha256": result["evaluator_manifest_sha256"],
            "metadata": metadata_mode, "delivery_state": delivery_mode}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--materialize-only", action="store_true")
    args = parser.parse_args()
    if args.write and args.materialize_only:
        parser.error("use either --write or --materialize-only")
    result = plan(args.task_dir.name, args.prepared)
    output = (deliver(args.task_dir, args.local_root, result,
                      materialize_only=args.materialize_only)
              if args.write or args.materialize_only else
              {"task_id": result["task_id"], "revision": result["revision"],
               "public_files": len(result["public"]) + 1,
               "evaluator_files": len(result["evaluator"]) + 1,
               "public_manifest_sha256": result["public_manifest_sha256"],
               "evaluator_manifest_sha256": result["evaluator_manifest_sha256"]})
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
