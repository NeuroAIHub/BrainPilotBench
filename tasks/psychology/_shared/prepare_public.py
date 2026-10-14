#!/usr/bin/env python3
"""Stage one pinned Psych-101 public train/valid package; never access Test."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

from contract import displayed_options
from responses import parse_transcript


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checked_split(path: Path, spec: dict, split: str) -> None:
    expected = spec["splits"][split]
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or linked {split} file")
    if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
        raise ValueError(f"{split} file differs from published package")
    rows = responses = 0
    participants = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if set(row) != {"experiment", "participant", "text"} or row["experiment"] != spec["experiment_id"]:
                raise ValueError(f"Unexpected {split} row")
            participant = str(row["participant"])
            if participant in participants:
                raise ValueError(f"Duplicate {split} participant")
            participants.add(participant)
            transcript = parse_transcript(row["text"])
            if not transcript.responses:
                raise ValueError(f"Empty {split} transcript")
            for span in transcript.responses:
                if spec["response_space_profile"] == "byte_next_v1":
                    # Exact raw UTF-8 response strings, including numeric/text forms,
                    # are targets. No class set is inferred from valid or Test.
                    span.raw.encode("utf-8", errors="strict")
                else:
                    options = displayed_options(transcript.prefix_for(span.response_id), spec)
                    if len(options) != spec["response_space_size"] or span.raw not in options:
                        raise ValueError(f"Invalid {split} response space")
            rows += 1
            responses += len(transcript.responses)
    if (rows, responses) != (expected["rows"], expected["responses"]):
        raise ValueError(f"{split} participant/response count changed")


def participants_in_source(source: Path, spec: dict) -> set[str]:
    h = hashlib.sha256()
    size = 0
    participants = set()
    with source.open("rb") as stream:
        for raw in stream:
            h.update(raw)
            size += len(raw)
            row = json.loads(raw)
            if row.get("experiment") == spec["experiment_id"]:
                if set(row) != {"experiment", "participant", "text"}:
                    raise ValueError("Unexpected source row")
                participant = str(row["participant"])
                if participant in participants:
                    raise ValueError("Repeated source participant")
                participants.add(participant)
    if (size, h.hexdigest()) != (spec["source_public_bytes"], spec["source_public_sha256"]):
        raise ValueError("Pinned public source bytes/hash differ")
    if len(participants) != sum(spec["splits"][name]["rows"] for name in ("train", "valid")):
        raise ValueError("Published participant count changed")
    return participants


def stage_from_source(source: Path, target: Path, spec: dict) -> None:
    participants = participants_in_source(source, spec)
    ranked = sorted(participants, key=lambda participant: hashlib.sha256(
        (spec["experiment_id"] + ":" + spec["split_seed"] + ":" + participant).encode("utf-8")
    ).digest())
    valid = set(ranked[:max(1, math.ceil(len(ranked) * 0.2))])
    with (target / "train.jsonl").open("xb") as train, (target / "valid.jsonl").open("xb") as validation:
        with source.open("rb") as stream:
            for raw in stream:
                row = json.loads(raw)
                if row.get("experiment") != spec["experiment_id"]:
                    continue
                payload = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
                (validation if str(row["participant"]) in valid else train).write(payload)


def cached_published_splits(spec: dict) -> dict[str, Path] | None:
    """Use both content-addressed public splits, or the original source fallback.

    A half-fetched package is an error: silently reconstructing it from the
    historical source would hide a failed published-package fetch.
    """
    base = Path(os.environ.get("BPB_CACHE_ROOT") or
                Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "brainpilot-bench")
    paths = {split: base / spec["splits"][split]["sha256"] / "data"
             for split in ("train", "valid")}
    present = {split: path.exists() or path.is_symlink() for split, path in paths.items()}
    # resolve.ts writes .partial under a per-SHA .fetch.lock before renaming to
    # data. A failed transfer can leave .partial behind; it is not zero cache.
    attempted = {split: any(marker.exists() or marker.is_symlink()
                            for marker in (path.parent / ".partial", path.parent / ".fetch.lock"))
                 for split, path in paths.items()}
    if not any(present.values()) and not any(attempted.values()):
        return None
    if not all(present.values()):
        missing = ", ".join(f"{split}.jsonl" for split in paths if not present[split])
        raise ValueError(f"Incomplete cached public package: missing {missing}; fetch both published splits")
    for split, path in paths.items():
        checked_split(path, spec, split)
    return paths


def prepare(contract_path: Path, output: Path, source: Path | None, published_dir: Path | None) -> None:
    spec = json.loads(contract_path.read_text(encoding="utf-8"))
    if spec.get("schema") != "bpb-psych101-public-contract/1":
        raise ValueError("Unexpected public contract")
    if output.exists():
        checked_split(output / "train.jsonl", spec, "train")
        checked_split(output / "valid.jsonl", spec, "valid")
        print("Verified existing public package:", output)
        return
    if (source is None) == (published_dir is None):
        raise ValueError("Select exactly one pinned public source or published public task directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".psych101-", dir=output.parent) as tmp:
        target = Path(tmp)
        if published_dir is not None:
            for split in ("train", "valid"):
                shutil.copyfile(published_dir / f"{split}.jsonl", target / f"{split}.jsonl")
        else:
            cached = cached_published_splits(spec)
            if cached is not None:
                for split, path in cached.items():
                    shutil.copyfile(path, target / f"{split}.jsonl")
            else:
                if source.is_symlink() or not source.is_file():
                    raise ValueError("Missing or linked public source")
                stage_from_source(source, target, spec)
        for split in ("train", "valid"):
            checked_split(target / f"{split}.jsonl", spec, split)
        shutil.copyfile(contract_path, target / "spec.json")
        os.rename(target, output)
    print("Staged verified public package:", output)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--contract", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--source", type=Path)
    choice.add_argument("--published-dir", type=Path)
    a = p.parse_args()
    try:
        prepare(a.contract, a.output, a.source, a.published_dir)
    except Exception as error:
        print(f"Public package preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
