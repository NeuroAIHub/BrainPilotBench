"""Trusted, isolated H2/B1 Valid scorer and separate owner Test entry.

Metric arithmetic uses _shared/metrics.py, adapted from the MIT-licensed
FALCON evaluator at 770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f.
"""

from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from io import BytesIO
import importlib.util
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import zlib

import numpy as np

from export import MANIFEST_SHA, PROFILE, ROOT, SOURCE_SHA, TASKS, digest, outside_git


METRICS_PATH = ROOT / "tasks/intracortical/_shared/metrics.py"
H1_BOUNDARIES = ROOT / "tasks/intracortical/falcon-h1-reach-grasp/checks/score.py"
for module_name, module_path in (("falcon_sequence_metrics", METRICS_PATH),
                                 ("falcon_h1_host_boundaries", H1_BOUNDARIES)):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Required trusted module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    globals()[module_name] = module


def parse_b1_prediction(raw: bytes) -> np.ndarray:
    """Read only the fixed NPY header and exact bounded float32 payload."""
    stream = BytesIO(raw)
    if np.lib.format.read_magic(stream) != (1, 0):
        raise ValueError("B1 prediction requires NPY version 1")
    shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=4096)
    if shape != (880, 158) or fortran or dtype.str != "<f4":
        raise ValueError("B1 prediction header differs from float32[880,158]")
    payload = stream.read()
    if len(payload) != 880 * 158 * 4:
        raise ValueError("B1 prediction payload length differs")
    array = np.frombuffer(payload, dtype="<f4").reshape(880, 158)
    if not np.isfinite(array).all():
        raise ValueError("B1 prediction is nonfinite")
    return array.copy()


def h2_schedule(mask: np.ndarray, trial_end: np.ndarray):
    """Select native evaluated bins and finish each complete trial in order."""
    trial_start = True
    for index in range(len(mask)):
        if bool(mask[index]):
            yield "observe", index, trial_start
            trial_start = False
        if bool(trial_end[index]):
            yield "finish", index, None
            trial_start = True


def verified_run_files(manifest_path: Path, task: str, role: str, contract: dict):
    binding = contract["evaluation_manifests"][role]
    falcon_h1_host_boundaries.bound_file(manifest_path, binding, max_bytes=500_000)
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema") != f"bpb-{task}-evaluation-data/1" or
            manifest.get("task_id") != TASKS[task] or manifest.get("profile") != PROFILE or
            manifest.get("role") != role or manifest.get("source_sha") != SOURCE_SHA or
            manifest.get("source_manifest_sha256") != MANIFEST_SHA or
            manifest.get("protocol_sha256") != contract["source"]["protocol_sha256"] or
            manifest.get("exporter_sha256") != contract["source"]["exporter_sha256"]):
        raise ValueError("Evaluation data provenance differs from contract")
    dates = []
    runs = []
    expected_files = {"h2": {"x.npy", "mask.npy", "trial_end.npy", "labels.json"},
                      "b1": {"x.npy", "y.npy", "mask.npy"}}[task]
    for run in manifest["runs"]:
        if run["role"] != role or set(run["files"]) != expected_files:
            raise ValueError("Evaluation run role/files differ")
        dates.append(run["session_id"])
        files = {}
        for name, metadata in run["files"].items():
            path = falcon_h1_host_boundaries.confined(manifest_path.parent, metadata["path"])
            falcon_h1_host_boundaries.bound_file(path, metadata, max_bytes=500_000_000)
            if name.endswith(".npy"):
                array = np.load(path, mmap_mode="r", allow_pickle=False)
                if list(array.shape) != metadata["shape"] or array.dtype.name != metadata["dtype"]:
                    raise ValueError("Evaluation array header differs from contract")
                files[name] = array
            else:
                labels = falcon_h1_host_boundaries.strict_json(path.read_bytes())
                if (not isinstance(labels, list) or len(labels) != metadata["count"] or
                        any(not isinstance(value, str) or not value for value in labels)):
                    raise ValueError("H2 labels differ from complete trials")
                files[name] = labels
        if task == "h2":
            x, mask, end = files["x.npy"], files["mask.npy"], files["trial_end.npy"]
            if (x.ndim != 2 or x.shape[1] != 192 or x.dtype != np.float32 or
                    mask.shape != (len(x),) or mask.dtype != bool or
                    end.shape != (len(x),) or end.dtype != bool or not end[-1] or
                    int(end.sum()) != len(files["labels.json"]) or
                    len(files["labels.json"]) != run["trials"] or not np.isfinite(x).all()):
                raise ValueError("H2 complete-trial structure differs")
        else:
            x, y, mask = files["x.npy"], files["y.npy"], files["mask.npy"]
            if (x.shape != (run["trials"], 27000, 85) or x.dtype != np.uint8 or
                    y.shape != (run["trials"], 880, 158) or y.dtype != np.float64 or
                    mask.shape != y.shape or mask.dtype != bool or
                    np.any(np.asarray(mask.sum(axis=(1, 2))) != 700 * 158) or
                    not np.isfinite(y).all()):
                raise ValueError("B1 native motif structure differs")
        runs.append((run, files))
    if (dates != contract["split"][f"{role}_dates"] or
            len(runs) != contract["derived_manifests"][role]["runs"] or
            sum(run["trials"] for run, _ in runs) != contract["derived_manifests"][role]["trials"]):
        raise ValueError("Evaluation date/trial inventory differs from contract")
    return runs


class Worker:
    def __init__(self, image: str, task: str, staged: Path, current_motif: Path | None = None):
        if falcon_h1_host_boundaries.IMAGE_RE.fullmatch(image) is None:
            raise ValueError("Docker image must use an immutable ID or digest")
        self.task = task
        self.name = f"bpb-{task}-" + uuid.uuid4().hex
        self.deadline = time.monotonic() + (900 if task == "h2" else 180)
        self.buffer = bytearray()
        command = ["docker", "run", "--rm", "-i", "--name", self.name,
                   "--network", "none", "--read-only", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges", "--cpus", "2", "--memory", "4g",
                   "--pids-limit", "128", "--user", "65534:65534",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                   "--mount", f"type=bind,src={staged},dst=/submission,readonly",
                   "--mount", f"type=bind,src={Path(__file__).with_name('worker.py')},dst=/worker.py,readonly"]
        if current_motif is not None:
            command += ["--mount", f"type=bind,src={current_motif},dst=/input.npy,readonly"]
        command += [image, "python", "-u", "/worker.py", task]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def exchange(self, kind: str, **fields):
        nonce = uuid.uuid4().hex
        packet = json.dumps({"nonce": nonce, "kind": kind, **fields}, allow_nan=False,
                            separators=(",", ":")).encode() + b"\n"
        if len(packet) > 16_384 or self.buffer or select.select([self.process.stdout], [], [], 0)[0]:
            raise ValueError("oversized request or unsolicited worker output")
        deadline = min(self.deadline, time.monotonic() + (120 if kind == "predict" else 30))
        sent = 0
        while sent < len(packet):
            left = deadline - time.monotonic()
            if left <= 0 or self.process.poll() is not None:
                raise TimeoutError("worker stopped before request")
            if select.select([], [self.process.stdin], [], left)[1]:
                sent += os.write(self.process.stdin.fileno(), packet[sent:])
        max_reply = 1_200_000 if kind == "predict" else (16_384 if kind == "finish" else 4096)
        while b"\n" not in self.buffer:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("worker reply timed out")
            if select.select([self.process.stdout], [], [], left)[0]:
                block = os.read(self.process.stdout.fileno(), max_reply + 1 - len(self.buffer))
                if not block:
                    raise ValueError("worker closed protocol output")
                self.buffer.extend(block)
                if len(self.buffer) > max_reply:
                    raise ValueError("worker reply exceeds limit")
        line, _, extra = self.buffer.partition(b"\n")
        self.buffer = bytearray(extra)
        if self.buffer:
            raise ValueError("worker sent unsolicited extra output")
        reply = falcon_h1_host_boundaries.strict_json(line)
        if not isinstance(reply, dict) or reply.get("nonce") != nonce or reply.get("kind") != kind:
            raise ValueError("worker nonce/kind mismatch")
        if kind == "finish":
            if set(reply) != {"nonce", "kind", "prediction"} or not isinstance(reply["prediction"], str) or len(reply["prediction"].encode()) > 2048:
                raise ValueError("H2 worker sentence reply differs")
            return reply["prediction"]
        if kind == "predict":
            if set(reply) != {"nonce", "kind", "prediction_zlib_npy_b64"}:
                raise ValueError("B1 worker reply fields differ")
            encoded = reply["prediction_zlib_npy_b64"]
            if not isinstance(encoded, str) or len(encoded) > 1_100_000:
                raise ValueError("B1 worker payload exceeds limit")
            compressed = base64.b64decode(encoded, validate=True)
            decompressor = zlib.decompressobj()
            raw = decompressor.decompress(compressed, 600_000)
            if (not decompressor.eof or decompressor.unconsumed_tail or
                    decompressor.unused_data or len(raw) > 600_000):
                raise ValueError("B1 worker decompressed payload exceeds limit")
            return parse_b1_prediction(raw)
        if set(reply) != {"nonce", "kind"}:
            raise ValueError("worker acknowledgment has extra fields")
        return None

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=15)
        finally:
            self.process.stdin.close()
            self.process.stdout.close()
            subprocess.run(["docker", "rm", "-f", self.name], check=False, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def score(task: str, task_dir: Path, artifacts: Path, manifest_path: Path, image: str,
          *, role: str = "valid", owner_test: bool = False,
          frozen_artifact_manifest: Path | None = None) -> dict:
    if os.environ.get("BPB_OFFICIAL_SCORING") == "1":
        raise ValueError("this public-derived profile is not official FALCON scoring")
    if role not in ("valid", "test") or task_dir.resolve() != (ROOT / "tasks/intracortical" / TASKS[task]).resolve():
        raise ValueError("wrong role or task directory")
    if role == "test":
        if (not owner_test or frozen_artifact_manifest is None or
                manifest_path.parent.name != "test" or manifest_path.parent.parent.name != "evaluator"):
            raise ValueError("Test requires owner flag, frozen artifact, and evaluator path")
    elif owner_test or frozen_artifact_manifest is not None or manifest_path.parent.name != "valid":
        raise ValueError("Public scoring accepts Valid only")
    contract = json.loads((task_dir / "contract.json").read_text())
    if (contract.get("schema") != "bpb-falcon-sequence-contract/1" or
            contract.get("task_id") != TASKS[task] or contract.get("science_profile") != PROFILE or
            contract.get("source", {}).get("source_manifest_sha256") != MANIFEST_SHA):
        raise ValueError("Task contract differs")
    runs = verified_run_files(manifest_path, task, role, contract)
    if role == "test":
        frozen = falcon_h1_host_boundaries.strict_json(frozen_artifact_manifest.read_bytes())
        if (frozen.get("schema") != f"bpb-{task}-frozen-artifact/1" or
                frozen.get("task_id") != TASKS[task] or frozen.get("profile") != PROFILE or
                set(frozen.get("files", {})) != set(falcon_h1_host_boundaries.REQUIRED)):
            raise ValueError("Owner-frozen submission differs")
    data_files = [(falcon_h1_host_boundaries.confined(manifest_path.parent, metadata["path"]), metadata["sha256"])
                  for run, _ in runs for metadata in run["files"].values()]
    manifest_hash = digest(manifest_path)
    with tempfile.TemporaryDirectory(prefix=f"bpb-{task}-isolated-") as temp:
        temporary = Path(temp)
        temporary.chmod(0o755)
        staged = temporary / "submission"
        hashes = falcon_h1_host_boundaries.stage_submission(artifacts, staged, None, test=False)
        if role == "test" and any(frozen["files"][name] != {"sha256": value, "bytes": (staged / name).stat().st_size}
                                  for name, value in hashes.items()):
            raise ValueError("Submission differs from owner-frozen artifact")
        grouped = defaultdict(list)
        counts = defaultdict(int)
        for run, files in runs:
            date = run["session_id"]
            if task == "h2":
                worker = Worker(image, task, staged)
                try:
                    worker.exchange("reset")
                    predictions = []
                    # Pinned upstream H2 predicts only for eval_mask=True.
                    # The mask stays on the host; masked bins never enter Docker.
                    for kind, index, trial_start in h2_schedule(files["mask.npy"], files["trial_end.npy"]):
                        if kind == "observe":
                            x = np.asarray(files["x.npy"][index], dtype=np.float32)
                            worker.exchange("observe", x=x.tolist(), trial_start=trial_start)
                        else:
                            predictions.append(worker.exchange("finish"))
                    worker.exchange("end")
                finally:
                    worker.close()
                if len(predictions) != len(files["labels.json"]):
                    raise ValueError("H2 prediction count differs from complete trials")
                grouped[date].extend(zip(predictions, files["labels.json"]))
                counts[date] += len(predictions)
            else:
                for index in range(run["trials"]):
                    current = temporary / f"motif-{uuid.uuid4().hex}.npy"
                    with current.open("xb") as output:
                        np.save(output, np.asarray(files["x.npy"][index]), allow_pickle=False)
                    current.chmod(0o444)
                    worker = Worker(image, task, staged, current)
                    try:
                        prediction = worker.exchange("predict")
                        worker.exchange("end")
                    finally:
                        worker.close()
                        current.unlink()
                    grouped[date].append((prediction, np.asarray(files["y.npy"][index]),
                                          np.asarray(files["mask.npy"][index])))
                    counts[date] += 1
        for name, expected in hashes.items():
            if digest(staged / name) != expected or digest(artifacts / "submission" / name) != expected:
                raise ValueError("Submission changed during isolated scoring")
        if digest(manifest_path) != manifest_hash or any(digest(path) != expected for path, expected in data_files):
            raise ValueError("Evaluation data changed during isolated scoring")
    metrics = falcon_sequence_metrics.handwriting(grouped) if task == "h2" else falcon_sequence_metrics.birdsong(grouped)
    return {"schema": f"bpb-{task}-score-report/1", "task_id": TASKS[task],
            "profile": PROFILE, "evaluation_profile": f"bpb-{task}-{'public-validation' if role == 'valid' else 'owner-independent-test'}-v1",
            "scope": "public-validation-only" if role == "valid" else "independent-evaluator-test",
            "official_falcon": False, "role": role, "metrics": metrics,
            "trials_per_date": dict(sorted(counts.items())), "submission_sha256": hashes,
            "manifest_sha256": manifest_hash, "image": image}


def main():
    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"scoring interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence-task", required=True, choices=TASKS)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--data-manifest", required=True, type=Path)
    parser.add_argument("--image", default=os.environ.get("BPB_INFERENCE_IMAGE"))
    parser.add_argument("--role", default="valid", choices=("valid", "test"))
    parser.add_argument("--owner-test", action="store_true")
    parser.add_argument("--frozen-artifact-manifest", type=Path)
    parser.add_argument("--report-output", type=Path,
                        help="External owner-only JSON destination for Test report")
    args = parser.parse_args()
    if not args.image:
        parser.error("immutable Docker image ID or digest required")
    if args.role == "test" and args.report_output is None:
        parser.error("owner Test requires --report-output outside Git")
    if args.role == "valid" and args.report_output is not None:
        parser.error("public Valid uses the normal score block, not an owner report")
    report = score(args.sequence_task, args.task, args.artifacts, args.data_manifest, args.image,
                   role=args.role, owner_test=args.owner_test,
                   frozen_artifact_manifest=args.frozen_artifact_manifest)
    if args.role == "valid":
        values = report["metrics"]
        shown = ({"WER": values["WER"]["mean"], "CER": values["CER"]["mean"]}
                 if args.sequence_task == "h2" else
                 {"normalized_spectrogram_MSE": values["mean"], "date_population_std": values["std_population"]})
        print(">>>>> BPB_SCORES")
        print(json.dumps(shown, allow_nan=False, sort_keys=True))
        print("<<<<< BPB_SCORES")
        print(json.dumps(report, allow_nan=False, sort_keys=True), file=sys.stderr)
    else:
        output = outside_git(args.report_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as saved:
            json.dump(report, saved, allow_nan=False, sort_keys=True, indent=2)
            saved.write("\n")
        print(json.dumps({"owner_report": str(output), "sha256": digest(output),
                          "role": "test", "scope": "independent-evaluator-test"}, sort_keys=True))


if __name__ == "__main__":
    main()
