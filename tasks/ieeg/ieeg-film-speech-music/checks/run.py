#!/usr/bin/env python3
"""Score shuffled film windows through a bounded, isolated model process."""

from __future__ import annotations

import argparse
import base64
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("model.py", "config.json", "weights.safetensors")
IMAGE_RE = re.compile(r"(?:sha256:[a-f0-9]{64}|[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64})\Z")


def resolve_image(explicit: str | None) -> str:
    image = explicit or os.environ.get("BPB_INFERENCE_IMAGE")
    if not image or IMAGE_RE.fullmatch(image) is None:
        raise ValueError("Set --image or BPB_INFERENCE_IMAGE to an immutable image ID or registry digest")
    return image


def install_termination_handler() -> None:
    def interrupt(_number, _frame):
        raise KeyboardInterrupt("Film scoring received SIGTERM")

    signal.signal(signal.SIGTERM, interrupt)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular(path: Path, max_bytes: int) -> None:
    if path.is_symlink():
        raise ValueError(f"Symlink is not an accepted input: {path}")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= max_bytes:
        raise ValueError(f"Input is not a bounded, unique regular file: {path}")


def bound(path: Path, spec: dict, max_bytes: int) -> None:
    regular(path, max_bytes)
    if path.stat().st_size != spec["bytes"] or sha256(path) != spec["sha256"]:
        raise ValueError(f"Frozen file differs: {path}")


def strict_json(path: Path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value
    return json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def write_owner_json(path: Path, value: dict, owner: Path) -> str:
    parent = path.parent.resolve()
    if (path.is_symlink() or path.exists() or not parent.is_relative_to(owner.resolve())):
        raise ValueError("Owner output must be a new path inside the owner directory")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".film-report-", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("Owner output lacks mode 0600")
    return sha256(path)


def stage_submission(source: Path, destination: Path, frozen: Path | None) -> dict:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Submission must be a directory, not a symlink")
    if set(path.name for path in source.iterdir()) != set(REQUIRED):
        raise ValueError("Submission must contain exactly model.py, config.json, and weights.safetensors")
    destination.mkdir(mode=0o755)
    limits = {"model.py": 200_000, "config.json": 64_000, "weights.safetensors": 100_000_000}
    hashes = {}
    for name in REQUIRED:
        regular(source / name, limits[name])
        shutil.copyfile(source / name, destination / name)
        hashes[name] = sha256(destination / name)
        (destination / name).chmod(0o644)
    config = strict_json(destination / "config.json")
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object")
    if frozen is not None:
        if strict_json(frozen) != {"schema": "bpb-ieeg-film-frozen-submission/1", "sha256": hashes}:
            raise ValueError("Frozen submission receipt differs")
    return hashes


class Worker:
    def __init__(self, image: str, submission: Path, max_channels: int):
        if IMAGE_RE.fullmatch(image) is None:
            raise ValueError("Docker image must be an immutable image ID")
        self.name = "bpb-film-" + uuid.uuid4().hex
        self.deadline = time.monotonic() + 900
        self.max_packet = min(8_000_000, ((max_channels * 512 * 4 + 2) // 3) * 4 + 1024)
        command = ["docker", "run", "--rm", "-i", "--name", self.name,
                   "--log-driver", "none",
                   "--network", "none", "--read-only", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges", "--cpus", "2", "--memory", "4g",
                   "--pids-limit", "128", "--user", "65534:65534",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
                   "--mount", f"type=bind,src={submission},dst=/submission,readonly",
                   "--mount", f"type=bind,src={Path(__file__).with_name('worker.py')},dst=/worker.py,readonly",
                   image, "python", "-u", "/worker.py"]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def predict(self, x: np.ndarray, subject_id: str) -> float:
        if x.dtype != np.float32 or x.ndim != 2 or x.shape[1] != 512 or not np.isfinite(x).all():
            raise ValueError("Input window must be finite float32[C,512]")
        nonce = uuid.uuid4().hex
        packet = json.dumps({"nonce": nonce, "subject_id": subject_id, "channels": x.shape[0],
                             "window_b64": base64.b64encode(x.astype("<f4", copy=False).tobytes()).decode()},
                            separators=(",", ":")).encode() + b"\n"
        if len(packet) > self.max_packet or select.select([self.process.stdout], [], [], 0)[0]:
            raise ValueError("Oversized window or unsolicited worker output")
        deadline = min(self.deadline, time.monotonic() + 30)
        written = 0
        while written < len(packet):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.process.poll() is not None:
                raise TimeoutError("Worker stopped before it received the window")
            if select.select([], [self.process.stdin], [], remaining)[1]:
                written += os.write(self.process.stdin.fileno(), packet[written:])
        response = bytearray()
        while b"\n" not in response:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Worker prediction timeout")
            if select.select([self.process.stdout], [], [], remaining)[0]:
                chunk = os.read(self.process.stdout.fileno(), 513 - len(response))
                if not chunk:
                    raise ValueError("Worker closed output before its prediction")
                response.extend(chunk)
                if len(response) > 512:
                    raise ValueError("Worker output exceeded 512 bytes")
        line, _, extra = response.partition(b"\n")
        if extra:
            raise ValueError("Worker sent unsolicited output")
        reply = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite reply")))
        value = reply.get("probability") if isinstance(reply, dict) else None
        if (set(reply) != {"nonce", "probability"} or reply["nonce"] != nonce
                or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Worker returned an invalid probability")
        return float(value)

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=15)
        finally:
            self.process.stdin.close()
            self.process.stdout.close()
            subprocess.run(["docker", "rm", "-f", self.name], check=False, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def evaluate(data_root: Path, submission: Path, role: str, image: str,
             frozen: Path | None, owner_test: bool):
    if role == "test" and (frozen is None or not owner_test):
        raise ValueError("Owner Test requires an explicit owner flag and frozen submission receipt")
    if role == "validation" and (frozen is not None or owner_test):
        raise ValueError("Validation does not accept an owner Test receipt")
    derived = data_root / "derived-v2"
    owner = derived / "owner"
    if role == "test" and (frozen.is_symlink() or
                           not frozen.resolve().is_relative_to(owner.resolve()) or
                           stat.S_IMODE(frozen.stat().st_mode) != 0o600):
        raise ValueError("Owner Test requires a 0600 frozen receipt inside owner data")
    common = strict_json(owner / "common_contract.json")
    if strict_json(ROOT / "contract.json") != common:
        raise ValueError("Owner common contract differs from the tracked contract")
    if common.get("schema") != "bpb-ieeg-film-common-contract/2" or not common.get("test_exported"):
        raise ValueError("Incomplete film common contract")
    bound(ROOT / "protocol.json", {"bytes": (ROOT / "protocol.json").stat().st_size,
                                    "sha256": common["protocol_sha256"]}, 20_000)
    bound(ROOT / "full_source_manifest.json", {"bytes": (ROOT / "full_source_manifest.json").stat().st_size,
                                               "sha256": common["source_manifest_sha256"]}, 200_000)
    if (sha256(ROOT / "cohort_inventory.json") != common["cohort_inventory_sha256"] or
            sha256(ROOT / "source_manifest.json") != common["source_metadata_sha256"]):
        raise ValueError("Pinned cohort or source metadata differs from the common contract")
    if common["preparation_code_sha256"] != sha256(ROOT / "env" / "prepare_full.py"):
        raise ValueError("Preparation code differs from the common contract")
    bound(data_root / "source_receipt.json", {"bytes": (data_root / "source_receipt.json").stat().st_size,
                                             "sha256": common["source_receipt_sha256"]}, 100_000)
    bound(owner / "lineage.json", {"bytes": (owner / "lineage.json").stat().st_size,
                                  "sha256": common["lineage_sha256"]}, 3_000_000)
    lineage = strict_json(owner / "lineage.json")
    train_entry = common["roles"]["train"]
    train_manifest_path = derived / train_entry["path"]
    bound(train_manifest_path, train_entry, 200_000)
    train_metadata = {item["subject_id"]: item["files"]["metadata"]
                      for item in strict_json(train_manifest_path)["subjects"]}
    entry = common["roles"][role]
    manifest_path = derived / entry["path"]
    bound(manifest_path, entry, 200_000)
    manifest = strict_json(manifest_path)
    if manifest["role"] != role or len(manifest["subjects"]) != common["eligible_subjects"]:
        raise ValueError("Role manifest differs from the common contract")
    with tempfile.TemporaryDirectory(prefix="bpb-film-isolated-") as temp:
        Path(temp).chmod(0o755)
        stage = Path(temp) / "submission"
        frozen_hash = sha256(frozen) if frozen is not None else None
        hashes = stage_submission(submission, stage, frozen)
        predictions = {}
        groups = defaultdict(list)
        per_subject = {}
        window_scores = {}
        per_block_hits = defaultdict(list)
        strata = defaultdict(list)
        for record in manifest["subjects"]:
            subject_id = record["subject_id"]
            directory = (owner / "test" if role == "test" else derived / "public") / subject_id
            spec = record["files"]
            array_path = directory / spec["arrays"]["path"]
            labels_path = directory / spec["labels"]["path"]
            bound(array_path, spec["arrays"], 200_000_000)
            bound(labels_path, spec["labels"], 100_000)
            with np.load(array_path, allow_pickle=False) as data:
                if set(data.files) != {"x", "ids"}:
                    raise ValueError("Unexpected array fields")
                x, ids = data["x"], data["ids"].tolist()
            labels = strict_json(labels_path)
            mapping = lineage["subjects"][subject_id]["split_windows"][role]
            block_ids = set(json.loads((ROOT / "protocol.json").read_text())["block_assignment"][role])
            if (list(x.shape) != spec["arrays"]["shape"] or str(x.dtype) != "float32"
                    or set(ids) != set(labels) or set(ids) != set(mapping)
                    or len(ids) != len(set(ids)) or x.shape[2] != 512
                    or x.shape[1] > common["maximum_good_channels"]
                    or any(item["block"] not in block_ids for item in mapping.values())):
                raise ValueError("Array shape, IDs, or hidden mapping differs")
            worker = Worker(image, stage, common["maximum_good_channels"])
            try:
                for index, identifier in enumerate(ids):
                    probability = worker.predict(x[index], subject_id)
                    predictions[identifier] = probability
                    hidden = mapping[identifier]
                    if labels[identifier] != hidden["label"]:
                        raise ValueError("Label differs from hidden binding")
                    groups[(subject_id, hidden["block"])].append((probability, hidden["label"]))
            finally:
                worker.close()
            hits = {0: [], 1: []}
            window_hits = {0: [], 1: []}
            for block in block_ids:
                values = groups[(subject_id, block)]
                if not 12 <= len(values) <= 13 or len({label for _, label in values}) != 1:
                    raise ValueError("Missing or mixed hidden block")
                label = values[0][1]
                hit = int((sum(p for p, _ in values) / len(values) >= 0.5) == label)
                hits[label].append(hit)
                per_block_hits[block].append(hit)
                window_hits[label].extend(int((probability >= 0.5) == label)
                                          for probability, _ in values)
            required = 1 if role == "validation" else 2
            if len(hits[0]) != required or len(hits[1]) != required:
                raise ValueError("Wrong hidden class block counts")
            per_subject[subject_id] = (sum(hits[0]) / required + sum(hits[1]) / required) / 2
            window_scores[subject_id] = (
                sum(window_hits[0]) / len(window_hits[0]) +
                sum(window_hits[1]) / len(window_hits[1])) / 2
            metadata_path = derived / "public" / subject_id / "metadata.json"
            bound(metadata_path, train_metadata[subject_id], 100_000)
            metadata = strict_json(metadata_path)
            for electrode_type in set(metadata["channel_types"]) & {"ECOG", "SEEG"}:
                strata[electrode_type].append(per_subject[subject_id])
        for name in REQUIRED:
            if sha256(submission / name) != hashes[name] or sha256(stage / name) != hashes[name]:
                raise ValueError("Submission changed during scoring")
        if frozen is not None and sha256(frozen) != frozen_hash:
            raise ValueError("Frozen submission receipt changed during scoring")
    subject_values = np.array(list(per_subject.values()), dtype=np.float64)
    report = {"schema": "bpb-ieeg-film-score/2", "role": role,
            "metric": "participant_macro_block_balanced_accuracy",
            "value": sum(per_subject.values()) / len(per_subject),
            "participants": len(per_subject), "windows": len(predictions),
            "participant_balanced_accuracy_distribution": {
                "min": float(subject_values.min()), "p25": float(np.quantile(subject_values, 0.25)),
                "median": float(np.median(subject_values)),
                "p75": float(np.quantile(subject_values, 0.75)),
                "max": float(subject_values.max()),
                "population_std": float(subject_values.std(ddof=0))},
            "per_block_accuracy": {str(block): sum(values) / len(values)
                                   for block, values in sorted(per_block_hits.items())},
            "descriptive_electrode_strata": {
                kind: {"participants": len(values), "mean": sum(values) / len(values)}
                for kind, values in sorted(strata.items())},
            "secondary_window_balanced_accuracy": sum(window_scores.values()) / len(window_scores),
            "submission_sha256": hashes, "frozen_receipt_sha256": frozen_hash,
            "manifest_sha256": entry["sha256"], "image": image}
    return report, predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--role", choices=("validation", "test"), default="validation")
    parser.add_argument("--image")
    parser.add_argument("--frozen-submission-receipt", type=Path)
    parser.add_argument("--owner-test", action="store_true")
    parser.add_argument("--bpb-scores", action="store_true")
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--audit-out", type=Path)
    args = parser.parse_args()
    install_termination_handler()
    if args.bpb_scores and args.role != "validation":
        parser.error("Generic BPB score sentinel is for public validation only")
    if args.role == "test" and (args.report_out is None or args.audit_out is not None):
        parser.error("Owner Test requires a private report path and forbids per-window audit export")
    image = resolve_image(args.image)
    report, predictions = evaluate(args.data_root, args.submission, args.role, image,
                                   args.frozen_submission_receipt, args.owner_test)
    owner = args.data_root / "derived-v2" / "owner"
    if args.role == "test":
        report_hash = write_owner_json(args.report_out, report, owner)
        print(json.dumps({"status": "owner_test_report_written", "report_sha256": report_hash}))
        return
    if args.audit_out is not None:
        audit = {"schema": "bpb-ieeg-film-valid-predictions/1",
                 "contract_sha256": sha256(ROOT / "contract.json"),
                 "manifest_sha256": report["manifest_sha256"],
                 "submission_sha256": report["submission_sha256"],
                 "predictions": predictions}
        audit_hash = write_owner_json(args.audit_out, audit, owner)
        report["owner_audit_sha256"] = audit_hash
    if args.report_out is not None:
        report_hash = write_owner_json(args.report_out, report, owner)
        report["owner_report_sha256"] = report_hash
    print(json.dumps(report, indent=2))
    if args.bpb_scores:
        print(">>>>> BPB_SCORES")
        print(json.dumps({"balanced_accuracy": report["value"]}))
        print("<<<<< BPB_SCORES")


if __name__ == "__main__":
    main()
