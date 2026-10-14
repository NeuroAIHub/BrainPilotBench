#!/usr/bin/env python3
"""Fail-closed launcher for one pinned, data-only native EEG export recipe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from paths import canonical_new_path, disjoint

PIN = "a8092dc10956038e445ff0e07f9c0c7e03a10d36"
ROOT = Path(__file__).resolve().parent
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            value.update(block)
    return value.hexdigest()


def load_recipe(task_dir: Path) -> dict:
    recipe = json.loads((task_dir / "preparation.json").read_text(encoding="utf-8"))
    if recipe.get("schema") != "bpb-eeg-native-data-preparation/1":
        raise ValueError("unknown preparation schema")
    if recipe.get("task_id") != task_dir.name or recipe.get("source_sha") != PIN:
        raise ValueError("task ID or pinned scientific source mismatch")
    if recipe.get("status") not in ("preparation_ready_data_pending", "frozen_public_task_rebuild_recipe"):
        raise ValueError("recipe is not in the declared preparation state")
    if recipe.get("target_kind") not in ("classification", "regression"):
        raise ValueError("unsupported native target kind")
    if not isinstance(recipe.get("expected_subjects"), int) or recipe["expected_subjects"] < 1:
        raise ValueError("expected_subjects must be a positive source-declared count")
    for rel, expected in recipe["vendor_files"].items():
        if not SHA_RE.fullmatch(expected) or Path(rel).name != rel:
            raise ValueError(f"invalid vendored file pin: {rel}")
        candidate = ROOT / rel
        if not candidate.is_file() or candidate.is_symlink() or digest(candidate) != expected:
            raise ValueError(f"vendored preparation file mismatch: {rel}")
    return recipe


def git_result(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def required_path(value: Path, label: str) -> Path:
    try:
        return value.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing: {value}") from error


def preflight(recipe: dict, source: Path, manifest: Path, data: Path, out: Path,
              python: Path, task_dir: Path) -> dict:
    if manifest.is_symlink():
        raise ValueError("calibration manifest must not be a symlink")
    source = required_path(source, "pinned scientific source")
    manifest = required_path(manifest, "calibration manifest")
    data = required_path(data, "raw data root")
    python = required_path(python, "isolated Python")
    out = canonical_new_path(out, "export output")
    if not source.is_dir() or not data.is_dir() or not python.is_file():
        raise ValueError("source, data, and Python interpreter must exist")
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError("calibrated manifest must be a regular file")
    disjoint(out, {"pinned source": source, "raw data": data, "task directory": task_dir},
             "export output")
    if git_result(source, "rev-parse", "HEAD") != PIN:
        raise ValueError("native scientific source is not at the pinned SHA")
    if git_result(source, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("native scientific source has tracked edits")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("source_sha") != PIN or not isinstance(metadata.get("resolved_config"), dict):
        raise ValueError("calibration manifest is not bound to the pinned source/config")
    source_block = (((metadata["resolved_config"].get("data") or {}).get("study") or {})
                    .get("steps") or {}).get("source") or {}
    if source_block.get("name") != recipe["source_dataset"]:
        raise ValueError("calibrated config source does not match the task's pinned study")
    return {
        "source": str(source), "source_sha": PIN,
        "calibration_manifest": str(manifest), "calibration_manifest_sha256": digest(manifest),
        "raw_data_root": str(data), "output": str(out), "python": str(python),
        "vendor_files": recipe["vendor_files"],
    }


def launch(recipe: dict, paths: dict) -> None:
    if platform.system() != "Linux":
        raise ValueError("native export requires Linux user+network namespaces; no unenforced fallback")
    if not shutil.which("unshare"):
        raise ValueError("unshare is unavailable")
    origin = os.readlink("/proc/self/ns/net")
    if not re.fullmatch(r"net:\[[0-9]+\]", origin):
        raise ValueError("cannot bind the launcher network namespace")
    cmd = ["unshare", "--user", "--map-current-user", "--net", paths["python"],
           str(ROOT / recipe["exporter"]),
           "--source", paths["source"], "--manifest", paths["calibration_manifest"],
           "--data", paths["raw_data_root"], "--out", paths["output"],
           "--task-id", recipe["source_task_id"],
           "--expected-source-name", recipe["source_dataset"],
           "--expected-subjects", str(recipe["expected_subjects"])]
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    env["NEURALBENCH_PREP_ORIGIN_NETNS"] = origin
    env["PYTHONNOUSERSITE"] = "1"
    subprocess.run(cmd, env=env, check=True)


def main(task_dir: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="show pinned recipe and unmet inputs; never export")
    parser.add_argument("--check-inputs", action="store_true", help="verify inputs without export")
    parser.add_argument("--run", action="store_true", help="run data-only exporter under a private network namespace")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--receipt", type=Path, help="new local JSON receipt outside task/source/export roots")
    args = parser.parse_args()
    if sum((args.plan, args.check_inputs, args.run)) != 1:
        parser.error("select exactly one of --plan, --check-inputs, --run")
    if args.run and args.receipt is None:
        parser.error("--run requires a new --receipt outside the export directory")
    task_dir = task_dir.resolve()
    recipe = load_recipe(task_dir)
    receipt = canonical_new_path(args.receipt, "preparation receipt") if args.receipt else None
    if receipt:
        disjoint(receipt, {"task directory": task_dir, "vendored exporter": ROOT},
                 "preparation receipt")
    if args.plan:
        report = {
            "task_id": recipe["task_id"], "status": recipe["status"],
            "source_task_id": recipe["source_task_id"], "source_dataset": recipe["source_dataset"],
            "source_sha": recipe["source_sha"], "exporter": recipe["exporter"],
            "vendor_files_checked": len(recipe["vendor_files"]),
            "remaining_inputs": recipe["remaining_inputs"],
            "data_exported": False, "agent_run_started": False, "private_test_consumed": False,
        }
    else:
        required = (args.source, args.manifest, args.data, args.out, args.python)
        if any(value is None for value in required):
            parser.error("--source --manifest --data --out --python are all required")
        paths = preflight(recipe, args.source, args.manifest, args.data, args.out, args.python,
                          task_dir)
        if receipt:
            disjoint(receipt, {"pinned source": Path(paths["source"]),
                               "raw data": Path(paths["raw_data_root"]),
                               "export output": Path(paths["output"])}, "preparation receipt")
            if args.run:
                receipt.parent.mkdir(parents=True, exist_ok=True)
                if not os.access(receipt.parent, os.W_OK):
                    raise ValueError("preparation receipt parent is not writable")
                if os.path.lexists(receipt):
                    raise ValueError("preparation receipt was created by another process")
        report = {"task_id": recipe["task_id"], "status": "inputs_checked", **paths,
                  "data_exported": False, "private_test_consumed": False}
        if args.run:
            launch(recipe, paths)
            from verify_export import verify_export
            verification = verify_export(recipe, Path(paths["output"]), hash_files=True)
            report.update(status="native_data_exported_and_checked", data_exported=True,
                          verification=verification,
                          schema="bpb-eeg-native-export-run-receipt/1",
                          export_complete_sha256=digest(Path(paths["output"]) / "complete.json"),
                          trusted_preparation_receipt=True)
    if receipt:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(receipt, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(Path(__file__).resolve().parent))
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"EEG data preparation stopped: {error}", file=sys.stderr)
        raise SystemExit(2) from error
