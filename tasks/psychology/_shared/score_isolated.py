#!/usr/bin/env python3
"""Public-valid controller: current targets stay outside the model container."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from contract import checked_probabilities, displayed_options
from prepare_public import checked_split
from responses import parse_transcript
from artifact_checks import digest, numeric_elements, strict_json


DEFAULT_IMAGE = "bpb-psych101-inference@sha256:e0bc28779515b7f9f6191d65d1fa5a36c6770ca134b9b076be00d7d71a3f2f21"
IMMUTABLE_IMAGE = re.compile(r"(?:sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64})\Z")
FILES = ("model.py", "config.json", "weights.json")
MAX_FILE_BYTES = {"model.py": 256 * 1024, "config.json": 64 * 1024,
                  "weights.json": 16 * 1024 * 1024}
PER_QUERY_SECONDS = 20
MAX_SCORING_SECONDS = 25 * 60  # Below the task scorer's 30-minute outer cap.
MAX_WORKER_MESSAGE = 1024 * 1024
MAX_QUERY_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 4096


def checked_byte_distribution(values) -> list[float]:
    """Require a complete probability distribution over 256 bytes plus EOS."""
    if type(values) is not list or len(values) != 257:
        raise ValueError("Byte model must return 257 probabilities including EOS")
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError("Invalid next-byte probability")
    if not math.isclose(math.fsum(values), 1.0, rel_tol=0, abs_tol=1e-8):
        raise ValueError("Next-byte probabilities are not normalized")
    return values


def stage_required(bundle: Path, target: Path, spec: dict) -> str:
    artifacts = bundle / "artifacts"
    for folder in (bundle, artifacts, artifacts / "submission"):
        metadata = folder.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("Submission parent directory must be a real directory")
    report = artifacts / "report.md"
    if report.is_symlink() or not report.is_file():
        raise ValueError("Missing report.md")
    model_hashes = []
    for seed in (0, 1, 2):
        source = artifacts / "submission" / f"seed-{seed}"
        if not stat.S_ISDIR(source.lstat().st_mode):
            raise ValueError(f"seed-{seed} must be a real directory")
        destination = target / f"seed-{seed}"
        destination.mkdir(mode=0o755)
        paths = {}
        for name in FILES:
            path = source / name
            meta = path.lstat()
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > MAX_FILE_BYTES[name]:
                raise ValueError(f"Unsafe or oversized seed-{seed}/{name}")
            paths[name] = path
        config = strict_json(paths["config.json"])
        weights = strict_json(paths["weights.json"])
        if type(config) is not dict or type(weights) is not dict or config.get("seed") != seed:
            raise ValueError("Invalid seed config or weights")
        if type(config.get("parameter_count")) is not int or not 0 <= config["parameter_count"] <= spec["max_parameters"]:
            raise ValueError("Invalid declared parameter count; source review is still needed")
        if numeric_elements(weights) > spec["max_saved_numeric_state"]:
            raise ValueError("Numeric state exceeds public contract")
        required = ("training_command", "seed_handling", "fit_determinism", "training_data", "saved_state_description")
        if any(type(config.get(key)) is not str or not config[key].strip() for key in required):
            raise ValueError("Missing training provenance declaration")
        if config["fit_determinism"] not in ("deterministic", "stochastic") or config.get("response_space_profile") != spec["response_space_profile"]:
            raise ValueError("Invalid fitting/profile declaration")
        model_hashes.append(digest(paths["model.py"]))
        for name, path in paths.items():
            copied = destination / name
            shutil.copyfile(path, copied)
            if digest(copied) != digest(path):
                raise ValueError("Staged model file changed")
            copied.chmod(0o444)
        destination.chmod(0o555)
    if len(set(model_hashes)) != 1:
        raise ValueError("Three seeds must share model.py")
    return model_hashes[0]


class Worker:
    def __init__(self, stage: Path, seed: int, image: str):
        self.name = "bpb-psych-public-" + uuid.uuid4().hex[:12]
        worker = Path(__file__).with_name("inference_worker.py").resolve()
        if worker.is_symlink() or not worker.is_file():
            raise ValueError("Trusted worker source missing")
        cmd = ["docker", "run", "-i", "--rm", "--name", self.name,
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "32",
               "--cpus", "2", "--memory", "4g", "--user", "65532:65532",
               "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
               "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
               "--mount", f"type=bind,source={stage.resolve()},target=/artifact,readonly",
               "--mount", f"type=bind,source={worker},target=/worker.py,readonly",
               "--entrypoint", "python3", image, "-I", "/worker.py", "--seed", str(seed)]
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        assert self.process.stdin is not None and self.process.stdout is not None
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def request(self, payload: dict, deadline: float) -> dict:
        process = self.process
        assert process.stdin is not None and process.stdout is not None
        encoded = (json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(encoded) > MAX_QUERY_BYTES:
            raise ValueError("Causal query exceeds bounded IPC size")
        pending = memoryview(encoded)
        received = bytearray()
        while pending:
            remaining = min(PER_QUERY_SECONDS, deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError("Model request exceeded scoring deadline")
            readable, writable, _ = select.select([process.stdout], [process.stdin], [], remaining)
            if readable:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError("Model worker exited before replying")
                received.extend(chunk)
                if len(received) > MAX_WORKER_MESSAGE or b"\n" in received:
                    raise ValueError("Unexpected early or oversized worker output")
            if writable:
                sent = os.write(process.stdin.fileno(), pending)
                pending = pending[sent:]
        while b"\n" not in received:
            remaining = min(PER_QUERY_SECONDS, deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError("Model worker did not answer within query deadline")
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                raise TimeoutError("Model worker query timed out")
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Model worker exited before replying")
            received.extend(chunk)
            if len(received) > MAX_WORKER_MESSAGE:
                raise ValueError("Model worker reply too large")
        line, extra = bytes(received).split(b"\n", 1)
        if extra:
            raise ValueError("Model worker emitted extra output")
        answer = json.loads(line)
        if type(answer) is not dict:
            raise ValueError("Invalid worker reply")
        return answer

    def close(self) -> None:
        process = self.process
        try:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        finally:
            subprocess.run(["docker", "rm", "-f", self.name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10, check=False)


def score_seed(stage: Path, seed: int, rows: list[dict], spec: dict, deadline: float, image: str) -> dict:
    worker = Worker(stage, seed, image)
    losses = []
    try:
        for row in rows:
            ready = worker.request({"op": "new_participant"}, deadline)
            if ready != {"ready": True}:
                raise ValueError("Model worker did not reset participant state")
            transcript = parse_transcript(row["text"])
            for span in transcript.responses:
                prefix = transcript.prefix_for(span.response_id)
                if spec["response_space_profile"] == "byte_next_v1":
                    target = span.raw.encode("utf-8", errors="strict")
                    if len(target) > MAX_RESPONSE_BYTES:
                        raise ValueError("Marked response exceeds bounded byte length")
                    prior = []
                    token_losses = []
                    for step, symbol in enumerate((*target, 256)):
                        reply = worker.request({"op": "predict_byte", "response_id": span.response_id,
                                                "step": step, "prefix": prefix,
                                                "response_prefix_bytes": list(prior)}, deadline)
                        if reply.get("response_id") != span.response_id or reply.get("step") != step:
                            raise ValueError("Byte worker response ID/step mismatch")
                        distribution = checked_byte_distribution(reply.get("probabilities"))
                        probability = distribution[symbol]
                        token_losses.append(-math.log(probability) if probability else math.inf)
                        if symbol != 256:
                            prior.append(symbol)
                    losses.append(math.fsum(token_losses) if all(math.isfinite(v) for v in token_losses) else math.inf)
                else:
                    options = displayed_options(prefix, spec)
                    if len(options) != spec["response_space_size"] or span.raw not in options:
                        raise ValueError("Public response differs from task contract")
                    reply = worker.request({"op": "predict", "response_id": span.response_id, "prefix": prefix}, deadline)
                    if reply.get("response_id") != span.response_id:
                        raise ValueError("Model worker response ID mismatch")
                    probabilities = checked_probabilities(reply.get("probabilities"), options)
                    probability = probabilities[span.raw]
                    losses.append(-math.log(probability) if probability else math.inf)
        if len(losses) != spec["splits"]["valid"]["responses"]:
            raise ValueError("Public validation response coverage changed")
        infinite = any(math.isinf(loss) for loss in losses)
        return {"seed": seed, "nll": None if infinite else math.fsum(losses) / len(losses),
                "infinite_nll": infinite, "responses": len(losses)}
    finally:
        worker.close()


def score(bundle: Path, public_dir: Path, spec: dict, image: str) -> tuple[dict, dict]:
    checked_split(public_dir / "valid.jsonl", spec, "valid")
    rows = [json.loads(line) for line in (public_dir / "valid.jsonl").open(encoding="utf-8")]
    if len(rows) != spec["splits"]["valid"]["rows"]:
        raise ValueError("Public participant count changed")
    scoring_minutes = spec.get("scoring_timeout_min", 30)
    if type(scoring_minutes) is not int or not 2 <= scoring_minutes <= 240:
        raise ValueError("Invalid finite scoring time budget")
    if spec["response_space_profile"] == "byte_next_v1":
        if scoring_minutes < 6:
            raise ValueError("Byte-sequence scoring needs at least six finite minutes")
        inner_seconds = (scoring_minutes - 5) * 60
    else:
        inner_seconds = min(MAX_SCORING_SECONDS, (scoring_minutes - 1) * 60)
    deadline = time.monotonic() + inner_seconds
    with tempfile.TemporaryDirectory(prefix="bpb-psych-stage-") as temp:
        stage = Path(temp)
        model_hash = stage_required(bundle, stage, spec)
        stage.chmod(0o755)
        results = [score_seed(stage, seed, rows, spec, deadline, image) for seed in (0, 1, 2)]
    infinite = any(item["infinite_nll"] for item in results)
    flat = {"nll_infinite": int(infinite),
            "responses": spec["splits"]["valid"]["responses"], "participants": len(rows)}
    if spec["response_space_profile"] != "byte_next_v1":
        flat["uniform_reference_nll"] = math.log(spec["response_space_size"])
    if not infinite:
        flat["mean_response_nll"] = math.fsum(item["nll"] for item in results) / 3
        flat.update({f"seed_{item['seed']}_nll": item["nll"] for item in results})
    detail = {"status": "valid_infinite_loss" if infinite else "scored_public_validation",
              "scope": "public_validation_only_not_blind_test", "task_id": spec["task_id"],
              "metric_direction": "minimize", "seeds": results,
              "seed_triplet_is_independent_agent_research": False,
              "model_py_sha256": model_hash, "inference_backend": "isolated_docker_causal_prefix_v1",
              "inference_image": image, "labels_mounted_into_worker": False,
              "inference_protocol": spec["response_space_profile"],
              "metric_version": spec.get("metric_version", "closed-categorical-v1")}
    return flat, detail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--public-dir", type=Path, required=True)
    args = parser.parse_args()
    sidecar = args.bundle / "psych101-public-validation.json"
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1":
        sidecar.write_text(json.dumps({"status": "official_scoring_rejected", "reason": "Public validation has no authorized private Test"}) + "\n")
        print("Psych-101 public validation refuses official private-Test scoring", file=sys.stderr)
        return 0
    try:
        image = os.environ.get("BPB_INFERENCE_IMAGE") or os.environ.get("BPB_PSYCH101_IMAGE") or DEFAULT_IMAGE
        if not IMMUTABLE_IMAGE.fullmatch(image):
            raise ValueError("Psych-101 inference image must be an immutable sha256 image ID or repository digest")
        spec = strict_json(args.contract)
        if spec.get("schema") != "bpb-psych101-public-contract/1":
            raise ValueError("Unexpected public contract")
        flat, detail = score(args.bundle, args.public_dir, spec, image)
    except Exception as error:
        sidecar.write_text(json.dumps({"status": "invalid_or_unscored", "reason": str(error)}) + "\n")
        print(f"Psych-101 public validation unscored: {error}", file=sys.stderr)
        return 0
    sidecar.write_text(json.dumps(detail, indent=2, allow_nan=False) + "\n")
    print(">>>>> BPB_SCORES")
    print(json.dumps(flat, allow_nan=False, sort_keys=True))
    print("<<<<< BPB_SCORES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
