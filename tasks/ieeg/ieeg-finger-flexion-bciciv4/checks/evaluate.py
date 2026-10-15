"""Trusted isolated offline BCI scorer. Public CLI scores Valid, never Test."""
import argparse
import io
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

import numpy as np

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "env"))
from common import PROFILE, read_role, sha256, validation, regular_unique
from score import score_subject


def freeze(artifacts, destination):
    with tempfile.TemporaryDirectory(prefix="bpb-bci-freeze-") as temp:
        staged = Path(temp) / "submission"
        validation.stage_submission(artifacts, staged, None, test=False)
        payload = {"schema": "bpb-bci-frozen-artifact/1", "profile": PROFILE,
                   "files": {name: {"sha256": sha256(staged / name), "bytes": (staged / name).stat().st_size}
                             for name in validation.REQUIRED}}
        with destination.open("x") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
        destination.chmod(0o600)


def predict(staged, source, subject, length, image, temp):
    if validation.IMAGE_RE.fullmatch(image) is None:
        raise ValueError("immutable inference image required")
    # Copy the verified input into a private staging directory. No source tree,
    # labels, manifest, or other participant's recording is mounted.
    local_input = temp / "input.npy"
    shutil.copyfile(source, local_input)
    local_input.chmod(0o444)
    name = "bpb-bci-" + uuid.uuid4().hex
    worker = Path(__file__).with_name("worker.py")
    command = ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--cpus", "2",
               "--memory", "4g", "--pids-limit", "128", "--user", "65534:65534",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
               "--mount", f"type=bind,src={staged},dst=/submission,readonly",
               "--mount", f"type=bind,src={local_input},dst=/input.npy,readonly",
               "--mount", f"type=bind,src={worker},dst=/worker.py,readonly",
               image, "python", "-u", "/worker.py", subject]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 300
    limit = length * 5 * 4 + 4096
    output = bytearray()
    try:
        os.set_blocking(process.stdout.fileno(), False)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("BCI container inference exceeded five minutes")
            if select.select([process.stdout], [], [], min(remaining, 1))[0]:
                block = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(output)))
                if not block:
                    break
                output.extend(block)
                if len(output) > limit:
                    raise ValueError("oversized prediction output")
        if process.wait(timeout=max(1, deadline - time.monotonic())) != 0:
            raise ValueError("BCI inference worker failed")
        stream = io.BytesIO(output)
        if np.lib.format.read_magic(stream) != (1, 0):
            raise ValueError("prediction requires NPY version 1")
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=4096)
        if shape != (length, 5) or fortran or dtype != np.dtype("float32"):
            raise ValueError("invalid prediction header")
        payload = stream.read()
        if len(payload) != length * 5 * 4:
            raise ValueError("invalid prediction byte count")
        prediction = np.frombuffer(payload, dtype=np.float32).reshape(length, 5)
        if not np.isfinite(prediction).all():
            raise ValueError("invalid prediction shape/dtype/bytes")
        return prediction
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=15)
        process.stdout.close()
        subprocess.run(["docker", "rm", "-f", name], timeout=15, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        local_input.unlink()


def evaluate(artifacts, data, image, role="valid", owner_test=False, frozen=None):
    if role == "test" and (not owner_test or frozen is None or "/evaluator/test" not in str(data.resolve())):
        raise ValueError("Test requires explicit evaluator data and owner-frozen submission")
    if role == "valid" and (owner_test or frozen):
        raise ValueError("Valid does not accept Test authority")
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1":
        raise ValueError("this profile is not an official competition submission")
    manifest, subjects = read_role(data, role)
    manifest_hash = sha256(data / "manifest.json")
    with tempfile.TemporaryDirectory(prefix="bpb-bci-isolated-") as folder:
        temp = Path(folder)
        temp.chmod(0o755)
        staged = temp / "submission"
        hashes = validation.stage_submission(artifacts, staged, None, test=False)
        if role == "test":
            regular_unique(frozen, max_bytes=100000)
            owner = validation.strict_json(frozen.read_bytes())
            expected = {name: {"sha256": hashes[name], "bytes": (staged / name).stat().st_size} for name in hashes}
            if (owner.get("schema") != "bpb-bci-frozen-artifact/1" or owner.get("profile") != PROFILE or
                    owner.get("files") != expected):
                raise ValueError("submission differs from the owner-frozen artifact")
        result = {}
        for record, arrays in subjects:
            prediction = predict(staged, data / record["files"]["x.npy"]["path"],
                                 record["subject"], len(arrays["x.npy"]), image, temp)
            result[record["subject"]] = score_subject(prediction, arrays["y.npy"])
        read_role(data, role)  # Detect changed evaluation inputs after scoring.
        if sha256(data / "manifest.json") != manifest_hash or any(
                sha256(staged / name) != digest or sha256(artifacts / "submission" / name) != digest
                for name, digest in hashes.items()):
            raise ValueError("input or artifact changed during evaluation")
    return {"schema": "bpb-bci-score-report/1", "profile": PROFILE, "role": role,
            "scope": "public-validation-only" if role == "valid" else "independent-evaluator-test",
            "official_competition": False, "pearson_r": float(np.mean(list(result.values()))),
            "subject_finger_pearson_r": result, "scored_finger_indices": [0, 1, 2, 4],
            "submission_sha256": hashes, "manifest_sha256": manifest_hash, "image": image}


def main():
    def stop(signum, frame):
        raise KeyboardInterrupt(f"interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, stop)
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--image", default=os.environ.get("BPB_INFERENCE_IMAGE"))
    parser.add_argument("--role", choices=("valid", "test"), default="valid")
    parser.add_argument("--owner-test", action="store_true")
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--freeze-to", type=Path)
    args = parser.parse_args()
    if args.freeze_to:
        if args.role != "valid" or args.owner_test or args.frozen or args.data:
            parser.error("freezing must not read evaluation data")
        freeze(args.artifacts, args.freeze_to)
        return
    if not args.data or not args.image:
        parser.error("data root and immutable Docker image required")
    report = evaluate(args.artifacts, args.data, args.image, args.role, args.owner_test, args.frozen)
    if args.role == "valid":
        print(">>>>> BPB_SCORES")
        print(json.dumps({"pearson_r": report["pearson_r"]}, allow_nan=False))
        print("<<<<< BPB_SCORES")
        print(json.dumps(report, allow_nan=False), file=sys.stderr)
    else:
        print(json.dumps(report, allow_nan=False))


if __name__ == "__main__":
    main()
