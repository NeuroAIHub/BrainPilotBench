"""Trusted CalMS21 scorer; candidate Python runs only inside pinned Docker image.

The model API is load_model(config, weights_path).predict_proba(keypoints,
scores, context). Context has task, group, class_count. Each full sequence is
passed once; no frames are dropped. Test must be requested explicitly.
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
import subprocess
import sys
import tempfile

import numpy as np

from calms_freeze import _safe_file, snapshot
from calms_metrics import CLASSIC_VOCAB, score_sequences, score_task2, score_task3
from calms_prepare import ARRAY_SPEC, SOURCE_SHA256, _assert_no_symlink_ancestors, _file_digest, _private_directory, _private_file, _safe_sequence_id, _verify_rows as verify_task1_rows, verify_prepared as verify_task1

IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _manifest(path: Path, *, private: bool = True) -> dict:
    (_private_file if private else _safe_file)(path)
    if path.stat().st_nlink != 1:
        raise ValueError("manifest hard link forbidden")
    if path.stat().st_size > 5_000_000:
        raise ValueError("manifest exceeds size bound")
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("manifest object required")
    return data


def _verify_public_rows(base: Path, rows: list[dict], task: str, role: str,
                        vocabs: dict[str, dict[str, int]]) -> tuple[set, int]:
    if base.is_symlink() or not base.is_dir():
        raise ValueError("public split directory required")
    expected_files, ids, frames = set(), set(), 0
    for row in rows:
        expected_keys = {"id", "file", "frames", "bytes", "sha256"} if task == "task1" else {"group", "id", "file", "frames", "bytes", "sha256"}
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise ValueError("public row schema mismatch")
        group = row.get("group", "annotator-id_0")
        if group not in vocabs:
            raise ValueError("public row group mismatch")
        if task == "task1":
            sequence_id = _safe_sequence_id(row["id"], "train")
            expected_name = hashlib.sha256(sequence_id.encode()).hexdigest() + ".npz"
        else:
            from calms_family_prepare import _safe_id
            sequence_id = _safe_id(row["id"], task, group, "train")
            expected_name = hashlib.sha256((group + "\0" + sequence_id).encode()).hexdigest() + ".npz"
        key = (group, sequence_id)
        if key in ids or row["file"] != expected_name or expected_name in expected_files:
            raise ValueError("public row ID or filename mismatch")
        ids.add(key)
        expected_files.add(expected_name)
        keypoints, scores, labels = _read_sequence(base, row, private=False)
        if np.any(labels >= len(vocabs[group])) or np.any((scores < 0) | (scores > 1)):
            raise ValueError("public label or confidence vocabulary mismatch")
        frames += len(labels)
    if {item.name for item in base.iterdir()} != expected_files:
        raise ValueError("public split file set mismatch")
    return ids, frames


def _prepared(prepared: Path, split: str) -> tuple[str, list[dict], dict[str, dict[str, int]], Path, str]:
    public = _manifest(prepared / "public/manifest.json")
    task = public.get("task")
    if task == "task1":
        verify_task1(prepared, include_owner=split == "test")
        vocab_by_group = {"annotator-id_0": CLASSIC_VOCAB}
    elif task in ("task2", "task3"):
        from calms_family_prepare import verify_prepared as verify_family
        verify_family(prepared, include_owner=split == "test")
        vocab_by_group = public["vocab_by_group"]
    else:
        raise ValueError("unsupported prepared task")
    if split == "test":
        owner = _manifest(prepared / "owner/test-manifest.json")
        if owner.get("task") != task:
            raise ValueError("owner/public task mismatch")
        if task != "task1" and owner.get("vocab_by_group") != vocab_by_group:
            raise ValueError("owner/public vocabulary mismatch")
        rows, base, manifest_path = owner["sequences"], prepared / "owner/test", prepared / "owner/test-manifest.json"
    else:
        rows, base, manifest_path = public["splits"]["valid"], prepared / "public/valid", prepared / "public/manifest.json"
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty evaluation split")
    return task, rows, vocab_by_group, base, _file_digest(manifest_path)[1]


def _role_packet(packet: Path, split: str, expected_sha: str) -> tuple[str, list[dict], dict[str, dict[str, int]], Path, str]:
    """Verify a role-only packet without opening or requiring its opposite role."""
    if not SHA_RE.fullmatch(expected_sha):
        raise ValueError("expected manifest SHA-256 required")
    if packet.is_symlink() or not packet.is_dir():
        raise ValueError("role packet directory required")
    role = "public" if split == "valid" else "owner"
    opposite = "owner" if role == "public" else "public"
    if (packet / opposite).exists() or (packet / opposite).is_symlink():
        raise ValueError("role packet contains opposite role")
    required_children = ({"manifest.json", "train", "valid"} if role == "public"
                         else {"test-manifest.json", "test"})
    if {entry.name for entry in (packet / role).iterdir()} != required_children:
        raise ValueError("role packet file set mismatch")
    manifest_path = packet / role / ("manifest.json" if split == "valid" else "test-manifest.json")
    (_safe_file if role == "public" else _private_file)(manifest_path)
    if manifest_path.stat().st_nlink != 1:
        raise ValueError("role manifest hard link forbidden")
    if _file_digest(manifest_path)[1] != expected_sha:
        raise ValueError("role manifest differs from trusted contract SHA-256")
    manifest = _manifest(manifest_path, private=role != "public")
    task = manifest.get("task")
    if task not in ("task1", "task2", "task3"):
        raise ValueError("unsupported task")
    if split == "valid":
        if manifest.get("schema") not in ("bpb-calms21-public/1", "bpb-calms21-family-public/1"):
            raise ValueError("public manifest schema mismatch")
        rows = manifest.get("splits", {}).get("valid")
        train = manifest.get("splits", {}).get("train")
        if not isinstance(train, list) or not isinstance(rows, list):
            raise ValueError("public split rows missing")
        all_roles = (("train", train), ("valid", rows))
        if set(manifest.get("splits", {})) != {"train", "valid"}:
            raise ValueError("public split set mismatch")
    else:
        if manifest.get("schema") not in ("bpb-calms21-owner-test/1", "bpb-calms21-family-owner-test/1"):
            raise ValueError("owner manifest schema mismatch")
        rows = manifest.get("sequences")
        all_roles = (("test", rows),)
    if task == "task1":
        if (manifest.get("source_sha256") != SOURCE_SHA256 or manifest.get("arrays") != ARRAY_SPEC
                or manifest.get("vocab") != CLASSIC_VOCAB):
            raise ValueError("Task1 source, array, or vocabulary mismatch")
        vocabs = {"annotator-id_0": CLASSIC_VOCAB}
    else:
        from calms_family_prepare import SOURCE, _verify_rows as verify_family_rows, vocab_by_group
        if (manifest.get("arrays") != ARRAY_SPEC or manifest.get("vocab_by_group") != vocab_by_group(task)
                or manifest.get("source_md5") != SOURCE[task]["md5"]
                or not SHA_RE.fullmatch(str(manifest.get("source_sha256", "")))):
            raise ValueError("family source, array, or vocabulary mismatch")
        vocabs = vocab_by_group(task)
    seen_by_role = {}
    for name, group_rows in all_roles:
        base = packet / role / name
        if not isinstance(group_rows, list) or not group_rows:
            raise ValueError("empty role packet split")
        if role == "public":
            ids, frames = _verify_public_rows(base, group_rows, task, name, vocabs)
            seen_by_role[name] = ids
        elif task == "task1":
            ids, frames = verify_task1_rows(base, group_rows, "train" if name in ("train", "valid") else "test")
            for row in group_rows:
                _safe_file(base / row["file"])
            seen_by_role[name] = ids
        else:
            ids, _, _, frames = verify_family_rows(base, group_rows, task, "train" if name in ("train", "valid") else "test")
            seen_by_role[name] = ids
        count = manifest.get("counts", {}).get(name) if split == "valid" else manifest.get("counts")
        if count != {"sequences": len(ids), "frames": frames}:
            raise ValueError("role packet count mismatch")
    if split == "valid" and seen_by_role["train"] & seen_by_role["valid"]:
        raise ValueError("Train/Valid overlap")
    return task, rows, vocabs, packet / role / split, expected_sha


def _image_id(image: str) -> str:
    if not IMAGE_RE.fullmatch(image):
        raise ValueError("image must be immutable sha256 ID")
    result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15)
    if result.returncode or result.stdout.strip() != image:
        raise RuntimeError("pinned Docker image unavailable")
    return image


def _read_sequence(base: Path, row: dict, *, private: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    name = row.get("file")
    if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}\.npz", name):
        raise ValueError("unsafe sequence filename")
    path = base / name
    (_private_file if private else _safe_file)(path)
    if path.stat().st_nlink != 1:
        raise ValueError("prepared sequence hard link forbidden")
    if _file_digest(path) != (row.get("bytes"), row.get("sha256")):
        raise ValueError("prepared sequence byte/SHA-256 mismatch")
    with np.load(path, allow_pickle=False) as source:
        if set(source.files) != {"keypoints", "scores", "labels"}:
            raise ValueError("prepared sequence array schema")
        keypoints, scores, labels = source["keypoints"], source["scores"], source["labels"]
    n = row.get("frames")
    if type(n) is not int or n <= 0 or keypoints.shape != (n, 2, 2, 7) or scores.shape != (n, 2, 7) or labels.shape != (n,):
        raise ValueError("prepared sequence frame shape")
    if keypoints.dtype != np.float32 or scores.dtype != np.float32 or labels.dtype != np.uint8:
        raise ValueError("prepared sequence dtype mismatch")
    if not np.isfinite(keypoints).all() or not np.isfinite(scores).all():
        raise ValueError("nonfinite feature")
    return keypoints, scores, labels


def _predict(image: str, submission: Path, keypoints: np.ndarray, scores: np.ndarray,
             context: dict, scratch: Path) -> np.ndarray:
    # No prepared root or labels are mounted. Staging contains only this sequence.
    input_dir = scratch / "input"
    output_dir = scratch / "output"
    input_dir.mkdir(mode=0o700)
    output_dir.mkdir(mode=0o700)
    with (input_dir / "features.npz").open("xb") as stream:
        np.savez(stream, keypoints=keypoints, scores=scores)
    (input_dir / "context.json").write_text(json.dumps(context), encoding="utf-8")
    os.chmod(input_dir / "features.npz", 0o600)
    os.chmod(input_dir / "context.json", 0o600)
    uid, gid = (os.getuid(), os.getgid()) if os.getuid() != 0 else (65532, 65532)
    if os.getuid() == 0:
        for path in (input_dir, output_dir, input_dir / "features.npz", input_dir / "context.json"):
            os.chown(path, uid, gid)
    worker = Path(__file__).with_name("calms_worker.py")
    command = ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", "64", "--cpus", "2", "--memory", "1g", "--memory-swap", "1g",
               "--ulimit", "fsize=16777216:16777216", "--ulimit", "nofile=64:64",
               "--user", f"{uid}:{gid}",
               "--tmpfs", "/tmp:rw,nosuid,noexec,size=64m",
               "--mount", f"type=bind,src={input_dir},dst=/input,readonly",
               "--mount", f"type=bind,src={output_dir},dst=/output",
               "--mount", f"type=bind,src={submission},dst=/model,readonly",
               "--mount", f"type=bind,src={worker},dst=/worker/calms_worker.py,readonly",
               image, "/input/features.npz", "/input/context.json", "/model", "/output/predictions.npy"]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError("isolated prediction failed") from exc
    if result.returncode:
        raise RuntimeError("isolated prediction rejected")
    result_path = output_dir / "predictions.npy"
    if set(path.name for path in output_dir.iterdir()) != {"predictions.npy"}:
        raise ValueError("unexpected isolated output files")
    if result_path.is_symlink() or not stat.S_ISREG(result_path.lstat().st_mode) or result_path.stat().st_nlink != 1:
        raise ValueError("invalid isolated output")
    if stat.S_IMODE(result_path.stat().st_mode) != 0o600:
        raise ValueError("isolated output must be private 0600")
    max_bytes = len(keypoints) * context["class_count"] * 8 + 4096
    if result_path.stat().st_size > max_bytes:
        raise ValueError("isolated output exceeds bound")
    with result_path.open("rb") as stream:
        prediction = np.load(stream, allow_pickle=False)
    if prediction.shape != (len(keypoints), context["class_count"]) or not np.issubdtype(prediction.dtype, np.floating):
        raise ValueError("prediction shape/dtype mismatch")
    if not np.isfinite(prediction).all() or np.any((prediction < 0) | (prediction > 1)):
        raise ValueError("invalid probabilities")
    if not np.allclose(prediction.sum(axis=1), 1, rtol=0, atol=1e-5):
        raise ValueError("probability rows do not sum to one")
    return prediction


def _source_digest(prepared: Path, source_zip: Path) -> dict:
    _safe_file(source_zip)
    evidence = _manifest(prepared / "preparation-evidence.json")
    expected_sha = evidence.get("source_sha256")
    expected_bytes = evidence.get("source_bytes")
    if type(expected_bytes) is not int or not isinstance(expected_sha, str):
        raise ValueError("source evidence incomplete")
    size, sha = _file_digest(source_zip)
    if (size, sha) != (expected_bytes, expected_sha):
        raise ValueError("original source ZIP bytes or SHA-256 mismatch")
    return {"bytes": size, "sha256": sha}


def evaluate(prepared: Path | None, submission: Path, image: str, source_zip: Path | None,
             split: str = "valid", run_kind: str = "agent-submission",
             role_packet: Path | None = None, expected_manifest_sha256: str | None = None) -> dict:
    if split not in ("valid", "test"):
        raise ValueError("split must be valid or test")
    if run_kind not in ("agent-submission", "fixed-reference"):
        raise ValueError("run kind must be explicit")
    image = _image_id(image)  # No host fallback.
    if role_packet is not None:
        if prepared is not None or source_zip is not None or expected_manifest_sha256 is None:
            raise ValueError("role packet requires only trusted manifest digest")
        source_before = None
        task, rows, vocabs, base, manifest_sha = _role_packet(role_packet, split, expected_manifest_sha256)
    else:
        if prepared is None or source_zip is None or expected_manifest_sha256 is not None:
            raise ValueError("full prepared mode requires original source ZIP")
        source_before = _source_digest(prepared, source_zip)
        task, rows, vocabs, base, manifest_sha = _prepared(prepared, split)
    model_before = snapshot(submission, frozen=True)
    truth: dict[str, dict[str, np.ndarray]] = {}
    predicted: dict[str, dict[str, np.ndarray]] = {}
    with tempfile.TemporaryDirectory(prefix="bpb-calms-run-") as directory:
        scratch_root = Path(directory)
        os.chmod(scratch_root, 0o700)
        model_mount = submission
        if os.getuid() == 0:
            # Keep the frozen original private while exposing an exact read-only
            # copy to a non-root container user.
            model_mount = scratch_root / "model"
            model_mount.mkdir(mode=0o755)
            for name in (*model_before, "freeze.json"):
                shutil.copyfile(submission / name, model_mount / name)
                os.chmod(model_mount / name, 0o644)
            if {name: _file_digest(model_mount / name)[1] for name in model_before} != {
                    name: entry["sha256"] for name, entry in model_before.items()}:
                raise ValueError("container model staging digest mismatch")
        for index, row in enumerate(rows):
            group = row.get("group", "annotator-id_0")
            if group not in vocabs or not isinstance(row.get("id"), str):
                raise ValueError("row group or sequence ID mismatch")
            keypoints, scores, labels = _read_sequence(base, row,
                                                        private=not (role_packet is not None and split == "valid"))
            context = {"task": task, "group": group, "class_count": len(vocabs[group])}
            sequence_dir = scratch_root / str(index)
            sequence_dir.mkdir(mode=0o700)
            probability = _predict(image, model_mount, keypoints, scores, context, sequence_dir)
            if row["id"] in truth.setdefault(group, {}):
                raise ValueError("duplicate sequence ID")
            truth[group][row["id"]] = labels
            predicted.setdefault(group, {})[row["id"]] = probability
            # Private arrays and predictions live only in this owner-controlled process.
            for path in (sequence_dir / "input/features.npz", sequence_dir / "input/context.json",
                         sequence_dir / "output/predictions.npy"):
                path.unlink()
            (sequence_dir / "input").rmdir()
            (sequence_dir / "output").rmdir()
            sequence_dir.rmdir()
    if snapshot(submission, frozen=True) != model_before:
        raise ValueError("frozen submission mutated during evaluation")
    if role_packet is not None:
        _role_packet(role_packet, split, expected_manifest_sha256)
    else:
        if _source_digest(prepared, source_zip) != source_before:
            raise ValueError("original source ZIP mutated during evaluation")
        _prepared(prepared, split)
    if task == "task1":
        if set(truth) != {"annotator-id_0"}:
            raise ValueError("Task1 group mismatch")
        metrics = score_sequences(truth["annotator-id_0"], predicted["annotator-id_0"], task=task, vocab=CLASSIC_VOCAB)
    elif task == "task2":
        metrics = score_task2(truth, predicted, vocabs)
    else:
        if split == "valid":
            public_manifest = _manifest(base.parent / "manifest.json",
                                        private=role_packet is None)
            unavailable = public_manifest.get("validation_unavailable_groups", [])
            if (not isinstance(unavailable, list) or any(group not in vocabs for group in unavailable)
                    or set(truth) != set(vocabs) - set(unavailable)):
                raise ValueError("Task3 Valid group coverage mismatch")
            if unavailable:
                groups = {group: score_sequences(truth[group], predicted[group],
                                                 task="task3", vocab=vocabs[group])
                          for group in sorted(truth)}
                metrics = {"f1": None, "groups": groups,
                           "validation_unavailable_groups": sorted(unavailable),
                           "aggregate_complete": False}
            else:
                metrics = score_task3(truth, predicted, vocabs)
        else:
            metrics = score_task3(truth, predicted, vocabs)
    return {"schema": "bpb-calms21-isolated-result/1", "task": task, "split": split,
            "kind": run_kind, "image_id": image,
            "frozen_files": model_before, "prepared_manifest_sha256": manifest_sha,
            "source_zip": source_before,
            "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, help="legacy complete preparation root")
    parser.add_argument("--public-packet", type=Path, help="public-only packet for Valid")
    parser.add_argument("--owner-packet", type=Path, help="owner-only packet for explicit Test")
    parser.add_argument("--expected-manifest-sha256", help="trusted contract digest for role-only packet")
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--image", required=True, help="immutable local image ID sha256:...")
    parser.add_argument("--source-zip", type=Path, help="original source archive for legacy complete mode")
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    parser.add_argument("--run-kind", choices=("agent-submission", "fixed-reference"), default="agent-submission")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if sum(value is not None for value in (args.prepared, args.public_packet, args.owner_packet)) != 1:
        parser.error("select exactly one prepared or role packet input")
    if args.public_packet is not None and args.split != "valid":
        parser.error("public packet supports Valid only")
    if args.owner_packet is not None and args.split != "test":
        parser.error("owner packet requires --split test")
    if args.split == "test" and "owner" not in args.report.parts:
        parser.error("Test report path must be under an owner directory")
    _assert_no_symlink_ancestors(args.report)
    if args.split == "test":
        _private_directory(args.report.parent)
    packet = args.public_packet if args.split == "valid" else args.owner_packet
    result = evaluate(args.prepared, args.submission, args.image, args.source_zip, args.split,
                      args.run_kind, packet, args.expected_manifest_sha256)
    if args.report.exists() or args.report.is_symlink():
        raise FileExistsError("fresh report path required")
    with os.fdopen(os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if args.split == "valid":
        print(json.dumps(result, sort_keys=True))
    else:
        print(json.dumps({"task": result["task"], "split": "test", "scored": True,
                          "report": str(args.report), "metrics_redacted": True}))


if __name__ == "__main__":
    main()
