#!/usr/bin/env python3
"""Export a train-only byte-unigram reference; never use Test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys

from prepare_public import checked_split
from responses import parse_transcript


def fit_once(train_path: Path) -> list[float]:
    counts = [1] * 257
    with train_path.open(encoding="utf-8") as stream:
        for line in stream:
            transcript = parse_transcript(json.loads(line)["text"])
            for span in transcript.responses:
                for value in span.raw.encode("utf-8", errors="strict"):
                    counts[value] += 1
                counts[256] += 1
    total = sum(counts)
    return [count / total for count in counts]


def train(contract_path: Path, public_dir: Path, output: Path) -> dict:
    spec = json.loads(contract_path.read_text(encoding="utf-8"))
    if spec.get("response_space_profile") != "byte_next_v1":
        raise ValueError("This reference requires byte_next_v1")
    checked_split(public_dir / "train.jsonl", spec, "train")
    checked_split(public_dir / "valid.jsonl", spec, "valid")
    output.mkdir(parents=True, exist_ok=False)
    artifacts = output / "artifacts"
    fitted = []
    for seed in (0, 1, 2):
        probabilities = fit_once(public_dir / "train.jsonl")
        fitted.append(probabilities)
        target = artifacts / "submission" / f"seed-{seed}"
        target.mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name("byte_reference_model.py"), target / "model.py")
        config = {
            "seed": seed, "parameter_count": 257,
            "training_command": shlex.join([sys.executable, *sys.argv]),
            "seed_handling": "separate deterministic fit_once call per seed; no RNG",
            "fit_determinism": "deterministic", "training_data": "train.jsonl",
            "saved_state_description": "Laplace-smoothed 256 UTF-8 byte probabilities plus EOS",
            "response_space_profile": "byte_next_v1",
        }
        (target / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        (target / "weights.json").write_text(json.dumps({"byte_probabilities": probabilities}, indent=2) + "\n", encoding="utf-8")
    if not (fitted[0] == fitted[1] == fitted[2]):
        raise ValueError("Deterministic seed fits unexpectedly differ")
    (artifacts / "report.md").write_text(
        "# Public byte-unigram pipeline reference\n\n"
        "Each of seeds 0, 1 and 2 independently counts UTF-8 bytes and response endings in public train, "
        "with one pseudocount per symbol. The deterministic weights coincide. The model ignores context, "
        "so it is a protocol check rather than a cognitive model. Public valid is not fitted here; no "
        "official Test was accessed. This byte+EOS metric is a new interface version and is not a "
        "historical Psych-101 categorical score.\n", encoding="utf-8")
    return {"independent_final_fits": 3, "vocabulary_size": 257,
            "train_responses": spec["splits"]["train"]["responses"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--public-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(train(args.contract, args.public_dir, args.out), indent=2))
