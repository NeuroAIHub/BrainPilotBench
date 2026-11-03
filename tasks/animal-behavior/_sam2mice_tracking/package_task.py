"""Package author frames and GT only after source review and split freezing."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

from fetch_sources import ARTICLE, EXPECTED_BYTES, EXPECTED_MD5, FILE_ID, FILE_NAME, SOURCE_URL
from inference import MAX_FEATURE_BYTES, load_features, load_truth, validate_detections
from task_common import (PROFILE, ROLES, SEQUENCE_ID, SHA, TASK_ID, VERSION, copy_checked,
                         digest, encoded, exact_packet, mkdir_safe, read_json, relative_path,
                         safe_path, source_locks, validate_contract, verify_locks)


def save_bytes(path: Path, data: bytes) -> None:
    mkdir_safe(path.parent)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
        writer.write(data)


def save_npz(path: Path, **arrays) -> dict:
    mkdir_safe(path.parent)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
        np.savez_compressed(writer, **arrays)
    return digest(path)


def read_source(source: Path) -> tuple[dict, dict[int, dict]]:
    safe_path(source, directory=True, owner=True)
    safe_path(source / "complete.json", owner=True)
    complete = read_json(source / "complete.json")
    if (complete.get("schema") != "bpb-sam2mice-tracking-prepared/1"
            or complete.get("source_verified") is not True or complete.get("fixture") is not False
            or not isinstance(complete.get("files"), dict)
            or not {"paired-frames.json", "audit.json"} <= set(complete["files"])):
        raise ValueError("verified complete source preparation required")
    for name, binding in complete["files"].items():
        relative_path(name)
        if (not isinstance(binding, dict) or set(binding) != {"bytes", "sha256"}
                or type(binding["bytes"]) is not int or binding["bytes"] < 0
                or not isinstance(binding["sha256"], str) or not SHA.fullmatch(binding["sha256"])):
            raise ValueError("invalid prepared-source binding")
        safe_path(source / name, owner=True)
        if digest(source / name) != binding:
            raise ValueError("prepared source changed")
    paired_digest = digest(source / "paired-frames.json")["sha256"]
    if complete.get("paired_manifest_sha256") != paired_digest:
        raise ValueError("source pair-manifest digest differs")
    manifest = read_json(source / "paired-frames.json")
    audit = read_json(source / "audit.json")
    provenance = complete.get("source")
    expected_source = {"schema": "bpb-sam2mice-source/1", "status": "verified", "file": FILE_NAME,
                       "file_id": FILE_ID, "bytes": EXPECTED_BYTES, "md5": EXPECTED_MD5,
                       "source_url": SOURCE_URL, "source_article": ARTICLE, "license": "CC-BY-4.0"}
    if (not isinstance(provenance, dict)
            or any(provenance.get(key) != value for key, value in expected_source.items())
            or not isinstance(provenance.get("sha256"), str) or not SHA.fullmatch(provenance["sha256"])
            or manifest.get("source") != provenance or audit.get("source") != provenance
            or audit.get("schema") != "bpb-sam2mice-source-audit/1"
            or audit.get("upstream_commit") != "80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98"):
        raise ValueError("prepared source provenance differs from the pinned author release")
    if (manifest.get("schema") != "bpb-sam2mice-source-pairs/1"
            or manifest.get("source_sequence") != "openfield_five_mouse"
            or not isinstance(manifest.get("pairs"), list) or not manifest["pairs"]):
        raise ValueError("author source-pair manifest required")
    pairs = {}
    for pair in manifest["pairs"]:
        required = {"frame_index", "image", "truth", "image_sha256", "truth_sha256", "width", "height",
                    "image_source_member", "truth_source_member"}
        if (not isinstance(pair, dict) or set(pair) != required
                or type(pair["frame_index"]) is not int or not 0 <= pair["frame_index"] <= 99999
                or pair["frame_index"] in pairs
                or any(type(pair[key]) is not int or not 1 <= pair[key] <= 4096 for key in ("width", "height"))):
            raise ValueError("invalid author source pair")
        index = pair["frame_index"]
        if pair["image"] != f"raw_frames/{index:05d}.jpg" or pair["truth"] != f"ground_truth/{index:05d}.txt":
            raise ValueError("source pair paths differ from original frame index")
        for field, folder, suffix in (("image", "openfield_five_mouse", "jpg"),
                                      ("truth", "ground_truth_bb_labels", "txt")):
            if (pair[field + "_source_member"] != f"SAM2_Mice/benchmark_data/{folder}/{index:05d}.{suffix}"
                    or pair[field] not in complete["files"]
                    or complete["files"][pair[field]]["sha256"] != pair[field + "_sha256"]):
                raise ValueError("pair does not bind the author's original frame or GT")
        pairs[index] = pair
    return complete, pairs


def reviewed_sequences(source: Path, review_path: Path, split_path: Path,
                       pairs: dict[int, dict]) -> tuple[dict, dict, list[dict]]:
    review, split = read_json(review_path), read_json(split_path)
    complete_hash = digest(source / "complete.json")["sha256"]
    paired_hash = digest(source / "paired-frames.json")["sha256"]
    if (review.get("schema") != "bpb-sam2mice-tracking-source-review/1"
            or review.get("status") != "passed"
            or review.get("source_complete_sha256") != complete_hash
            or review.get("paired_manifest_sha256") != paired_hash
            or any(review.get(key) is not True for key in (
                "author_gt_verified", "image_label_alignment_verified", "identity_continuity_verified", "clean_input_verified"))
            or not isinstance(review.get("basis"), str) or not review["basis"].strip()):
        raise ValueError("explicit source review must pass and bind the current source")
    if (split.get("schema") != "bpb-sam2mice-tracking-split-review/1"
            or split.get("status") != "frozen" or split.get("task_id") != TASK_ID
            or split.get("task_version") != VERSION or split.get("profile") != PROFILE
            or split.get("source_complete_sha256") != complete_hash
            or split.get("paired_manifest_sha256") != paired_hash
            or split.get("source_review_sha256") != digest(review_path)["sha256"]
            or split.get("no_model_scores_used") is not True
            or not isinstance(split.get("rule"), dict)
            or not isinstance(split["rule"].get("description"), str) or not split["rule"]["description"].strip()
            or not isinstance(split.get("sequences"), list) or not split["sequences"]):
        raise ValueError("explicit pre-analysis split review required")
    used, identifiers = set(), set()
    for sequence in split["sequences"]:
        if (not isinstance(sequence, dict) or set(sequence) != {"id", "split", "frame_indices"}
                or not isinstance(sequence["id"], str) or not SEQUENCE_ID.fullmatch(sequence["id"])
                or sequence["id"] in identifiers or sequence["split"] not in ROLES
                or not isinstance(sequence["frame_indices"], list) or not 1 <= len(sequence["frame_indices"]) <= 128):
            raise ValueError("invalid frozen sequence")
        indices = sequence["frame_indices"]
        if (any(type(index) is not int or index not in pairs or index in used for index in indices)
                or any(second != first + 1 for first, second in zip(indices, indices[1:]))):
            raise ValueError("sequences must preserve unique contiguous paired source frames")
        used.update(indices)
        identifiers.add(sequence["id"])
    for role in ROLES:
        count = sum(sequence["split"] == role for sequence in split["sequences"])
        if not 1 <= count <= 128:
            raise ValueError("each frozen role requires bounded nonempty sequence coverage")
    return review, split, sorted(split["sequences"], key=lambda row: row["id"])


def read_image(source: Path, pair: dict) -> np.ndarray:
    path = source / pair["image"]
    if digest(path)["sha256"] != pair["image_sha256"]:
        raise ValueError("original source image changed")
    with Image.open(path) as image:
        if image.format != "JPEG" or image.size != (pair["width"], pair["height"]):
            raise ValueError("original image format or dimensions differ")
        result = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if digest(path)["sha256"] != pair["image_sha256"]:
        raise ValueError("original source image changed during decoding")
    return result


def truth_rows(source: Path, pair: dict, local_frame: int) -> list[list[float]]:
    path = source / pair["truth"]
    if digest(path)["sha256"] != pair["truth_sha256"]:
        raise ValueError("original author GT changed")
    result = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) != 5:
            raise ValueError("author GT row must contain an ID and four normalized coordinates")
        identity = int(fields[0])
        if str(identity) != fields[0]:
            raise ValueError("author GT identity must be an integer")
        center_x, center_y, width, height = map(float, fields[1:])
        result.append([local_frame, identity, center_x - width / 2, center_y - height / 2,
                       center_x + width / 2, center_y + height / 2])
    if digest(path)["sha256"] != pair["truth_sha256"]:
        raise ValueError("original author GT changed during reading")
    return result


def build_packets(source: Path, review_path: Path, split_path: Path, output: Path) -> dict:
    evidence = {path: digest(path) for path in (source / "complete.json", source / "paired-frames.json", review_path, split_path)}
    _, pairs = read_source(source)
    _, split, sequences = reviewed_sequences(source, review_path, split_path, pairs)
    image_sizes = {(pair["width"], pair["height"]) for pair in pairs.values()}
    if len(image_sizes) != 1:
        raise ValueError("one image size is required for the source recording")
    width, height = image_sizes.pop()
    # Inspect all selected source bytes before writing any role packet.
    pixel_roles = {}
    for sequence in sequences:
        if len(sequence["frame_indices"]) * width * height * 3 > MAX_FEATURE_BYTES - 4096:
            raise ValueError("sequence exceeds the bounded RGB packet size")
        labels = []
        for local_frame, index in enumerate(sequence["frame_indices"]):
            image = read_image(source, pairs[index])
            checksum = hashlib.sha256(image.tobytes()).hexdigest()
            previous = pixel_roles.setdefault(checksum, sequence["split"])
            if previous != sequence["split"]:
                raise ValueError("identical decoded images cross frozen data roles")
            labels.extend(truth_rows(source, pairs[index], local_frame))
        target = validate_detections(np.asarray(labels, dtype=np.float64).reshape(-1, 6), len(sequence["frame_indices"]))
        if not len(target):
            raise ValueError("each frozen sequence requires at least one author GT object")
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh packet output required")
    mkdir_safe(output)
    role_files, manifests = {}, {}
    for packet_role, roles in (("public", ("train", "valid")), ("evaluator", ("test",))):
        rows, files = [], []
        for sequence in sequences:
            if sequence["split"] not in roles:
                continue
            images, labels = [], []
            for local_frame, index in enumerate(sequence["frame_indices"]):
                images.append(read_image(source, pairs[index]))
                labels.extend(truth_rows(source, pairs[index], local_frame))
            frame_count = len(images)
            prefix = sequence["split"] + "/" + sequence["id"]
            feature_path, label_path = prefix + ".features.npz", prefix + ".truth.npz"
            features = save_npz(output / packet_role / feature_path, frames=np.stack(images))
            target = validate_detections(np.asarray(labels, dtype=np.float64).reshape(-1, 6), frame_count)
            truth = save_npz(output / packet_role / label_path, detections=target)
            load_features(output / packet_role / feature_path, expected_bytes=features["bytes"],
                          expected_sha256=features["sha256"], frames=frame_count)
            load_truth(output / packet_role / label_path, expected_bytes=truth["bytes"],
                       expected_sha256=truth["sha256"], frames=frame_count)
            rows.append({"id": sequence["id"], "split": sequence["split"], "frames": frame_count,
                         "feature_path": feature_path, "feature_bytes": features["bytes"], "feature_sha256": features["sha256"],
                         "label_path": label_path, "label_bytes": truth["bytes"], "label_sha256": truth["sha256"]})
            files.extend(({"path": feature_path, **features}, {"path": label_path, **truth}))
        files.sort(key=lambda row: row["path"])
        manifest = {"schema": "bpb-sam2mice-tracking-role-packet/1", "task_id": TASK_ID,
                    "task_version": VERSION, "role": packet_role, "profile": PROFILE,
                    "image_size": [width, height], "sequences": rows, "files": files}
        raw = encoded(manifest)
        save_bytes(output / packet_role / "manifest.json", raw)
        manifests[packet_role] = hashlib.sha256(raw).hexdigest()
        role_files[packet_role] = sorted([*files, {"path": "manifest.json", "bytes": len(raw),
                                                   "sha256": manifests[packet_role]}], key=lambda row: row["path"])
    revision = hashlib.sha256(bytes.fromhex(manifests["public"]) + bytes.fromhex(manifests["evaluator"])).hexdigest()
    contract = {
        "schema": "bpb-sam2mice-tracking-task-contract/1", "task_id": TASK_ID,
        "task_version": VERSION, "profile": PROFILE, "metric": "mota", "secondary_metrics": ["idf1"],
        "iou_threshold": 0.5, "image_size": [width, height], "revision": revision,
        "revision_rule": "sha256(raw32(public_manifest_sha256) || raw32(evaluator_manifest_sha256))",
        "public_manifest_sha256": manifests["public"], "evaluator_manifest_sha256": manifests["evaluator"],
        "source_complete_sha256": evidence[source / "complete.json"]["sha256"],
        "source_review_sha256": evidence[review_path]["sha256"], "split_review_sha256": evidence[split_path]["sha256"],
        "public_files": role_files["public"], "owner_files": role_files["evaluator"],
        "counts": {role: {"sequences": sum(row["split"] == role for row in sequences),
                           "frames": sum(len(row["frame_indices"]) for row in sequences if row["split"] == role)}
                   for role in ROLES},
        "split_rule": split["rule"],
    }
    if any(digest(path) != binding for path, binding in evidence.items()):
        raise ValueError("source or review evidence changed during packaging")
    validate_contract(contract)
    data_lock, evaluator_lock = source_locks(contract)
    for name, value in (("contract.json", contract), ("data.lock", data_lock), ("evaluator.lock", evaluator_lock)):
        save_bytes(output / name, encoded(value))
    copy_checked(review_path, output / "source-review.json", {"path": "source-review.json", **evidence[review_path]})
    copy_checked(split_path, output / "split-review.json", {"path": "split-review.json", **evidence[split_path]})
    exact_packet(output / "public", contract, evaluator=False)
    exact_packet(output / "evaluator", contract, evaluator=True)
    save_bytes(output / "complete.json", encoded({
        "schema": "bpb-sam2mice-tracking-packets/1", "task_id": TASK_ID, "revision": revision,
        "source_review_passed": True, "split_frozen": True,
        "source_complete_sha256": contract["source_complete_sha256"],
        "metadata": {name: digest(output / name) for name in (
            "contract.json", "data.lock", "evaluator.lock", "source-review.json", "split-review.json")},
    }))
    return contract


def bind_and_materialize(packets_root: Path, task_dir: Path, local_root: Path, *, materialize_only: bool = False) -> dict:
    safe_path(packets_root, directory=True, owner=True)
    done = read_json(packets_root / "complete.json")
    if (done.get("schema") != "bpb-sam2mice-tracking-packets/1" or done.get("task_id") != TASK_ID
            or done.get("source_review_passed") is not True or done.get("split_frozen") is not True
            or task_dir.name != TASK_ID):
        raise ValueError("completed reviewed packet package required")
    metadata = {}
    required = {"contract.json", "data.lock", "evaluator.lock", "source-review.json", "split-review.json"}
    if not isinstance(done.get("metadata"), dict) or set(done["metadata"]) != required:
        raise ValueError("complete packet metadata bindings required")
    for name in sorted(required):
        if digest(packets_root / name) != done["metadata"][name]:
            raise ValueError("packet metadata receipt differs")
        metadata[name] = (packets_root / name).read_bytes()
    contract = validate_contract(read_json(packets_root / "contract.json"))
    review, split = read_json(packets_root / "source-review.json"), read_json(packets_root / "split-review.json")
    expected_data, expected_evaluator = source_locks(contract)
    if (read_json(packets_root / "data.lock") != expected_data
            or read_json(packets_root / "evaluator.lock") != expected_evaluator):
        raise ValueError("packet locks differ from the scientific content")
    if (contract["revision"] != done.get("revision")
            or contract["source_complete_sha256"] != done.get("source_complete_sha256")
            or contract["source_review_sha256"] != digest(packets_root / "source-review.json")["sha256"]
            or contract["split_review_sha256"] != digest(packets_root / "split-review.json")["sha256"]
            or review.get("schema") != "bpb-sam2mice-tracking-source-review/1"
            or review.get("status") != "passed"
            or any(review.get(key) is not True for key in (
                "author_gt_verified", "image_label_alignment_verified", "identity_continuity_verified", "clean_input_verified"))
            or split.get("schema") != "bpb-sam2mice-tracking-split-review/1"
            or split.get("status") != "frozen" or split.get("no_model_scores_used") is not True
            or review.get("source_complete_sha256") != contract["source_complete_sha256"]
            or split.get("source_complete_sha256") != contract["source_complete_sha256"]
            or split.get("source_review_sha256") != contract["source_review_sha256"]):
        raise ValueError("packet revision or review bindings differ")
    exact_packet(packets_root / "public", contract, evaluator=False)
    exact_packet(packets_root / "evaluator", contract, evaluator=True)
    bind_names = ("contract.json", "data.lock", "evaluator.lock")
    present = {name for name in bind_names if (task_dir / name).exists() or (task_dir / name).is_symlink()}
    if present and present != set(bind_names):
        raise ValueError("partial task bindings must be preserved and reconciled")
    if materialize_only and not present:
        raise ValueError("materialization requires checked-in bindings")
    if present:
        safe_path(task_dir / "contract.json")
        if (task_dir / "contract.json").read_bytes() != metadata["contract.json"]:
            raise ValueError("checked-in binding differs from regenerated source")
        verify_locks(task_dir, contract)
    else:
        mkdir_safe(task_dir)
        for name in bind_names:
            save_bytes(task_dir / name, metadata[name])
    destination = local_root / "tasks/animal-behavior" / TASK_ID / contract["revision"]
    if destination.exists() or destination.is_symlink():
        safe_path(destination, directory=True, owner=True)
        if {path.name for path in destination.iterdir()} != {"public", "evaluator"}:
            raise ValueError("extra or incomplete local delivery paths")
        exact_packet(destination / "public", contract, evaluator=False)
        exact_packet(destination / "evaluator", contract, evaluator=True)
        mode = "verified-existing"
    else:
        for role, key in (("public", "public_files"), ("evaluator", "owner_files")):
            for row in contract[key]:
                copy_checked(packets_root / role / row["path"], destination / role / row["path"], row)
        exact_packet(destination / "public", contract, evaluator=False)
        exact_packet(destination / "evaluator", contract, evaluator=True)
        mode = "created"
    return {"task_id": TASK_ID, "revision": contract["revision"], "mode": mode,
            "public_files": len(contract["public_files"]), "evaluator_files": len(contract["owner_files"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("prepared", "review", "split", "output"):
        build.add_argument("--" + name, type=Path, required=True)
    bind = sub.add_parser("bind")
    for name in ("packets", "task-dir", "local-root"):
        bind.add_argument("--" + name, type=Path, required=True)
    bind.add_argument("--materialize-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "build":
        contract = build_packets(args.prepared, args.review, args.split, args.output)
        print(json.dumps({"task_id": TASK_ID, "revision": contract["revision"], "counts": contract["counts"]}))
    else:
        print(json.dumps(bind_and_materialize(args.packets, args.task_dir, args.local_root,
                                              materialize_only=args.materialize_only)))


if __name__ == "__main__":
    main()
