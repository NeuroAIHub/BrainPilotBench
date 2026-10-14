#!/usr/bin/env python3
"""Fit and export a deterministic small reference from real public train data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys

from contract import CASINO_PROFILE, displayed_options
from prepare_public import checked_split
from reference_model import last_casino_choice
from responses import parse_transcript


def fit_once(spec: dict, train_path: Path) -> dict:
    """Execute a complete deterministic fit; call separately for each seed."""
    counts = [1] * spec["response_space_size"]  # Laplace smoothing; all outcomes finite.
    stay_counts = [1, 1]  # stay, switch, using only earlier same-casino choices.
    with train_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            transcript = parse_transcript(row["text"])
            for span in transcript.responses:
                prefix = transcript.prefix_for(span.response_id)
                options = displayed_options(prefix, spec)
                counts[options.index(span.raw)] += 1
                if spec["response_space_profile"] == CASINO_PROFILE:
                    previous = last_casino_choice(prefix)
                    if previous is not None:
                        stay_counts[0 if previous == span.raw else 1] += 1
    method = "casino_stay_prior" if spec["response_space_profile"] == CASINO_PROFILE else "option_position_prior"
    probabilities = ([stay_counts[0] / sum(stay_counts), 1 - stay_counts[0] / sum(stay_counts)]
                     if method == "casino_stay_prior" else [n / sum(counts) for n in counts])
    return {"reference_method": method, "option_counts_with_pseudocounts": counts,
            "stay_switch_counts_with_pseudocounts": stay_counts,
            "option_probabilities": probabilities}


def train(contract_path: Path, public_dir: Path, output: Path) -> dict:
    spec = json.loads(contract_path.read_text(encoding="utf-8"))
    checked_split(public_dir / "train.jsonl", spec, "train")
    checked_split(public_dir / "valid.jsonl", spec, "valid")
    output.mkdir(parents=True, exist_ok=False)
    artifacts = output / "artifacts"
    fitted = []
    for seed in (0, 1, 2):
        fit = fit_once(spec, public_dir / "train.jsonl")
        fitted.append(fit)
        target = artifacts / "submission" / f"seed-{seed}"
        target.mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name("reference_model.py"), target / "model.py")
        config = {
            "seed": seed,
            "parameter_count": len(fit["option_probabilities"]),
            "training_command": shlex.join([sys.executable, *sys.argv]),
            "seed_handling": "separate in-process fit_once call for this seed; deterministic count fit with no RNG",
            "fit_determinism": "deterministic",
            "training_data": "train.jsonl",
            "saved_state_description": "Laplace-smoothed casino stay probability or displayed option-position prior",
            "response_space_profile": spec["response_space_profile"],
            "reference_method": fit["reference_method"],
        }
        (target / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        (target / "weights.json").write_text(json.dumps({"option_probabilities": fit["option_probabilities"]}, indent=2) + "\n", encoding="utf-8")
    if not (fitted[0] == fitted[1] == fitted[2]):
        raise ValueError("Deterministic seed fits unexpectedly differ")
    report = (
        f"# Public reference for {spec['experiment_id']}\n\n"
        "This deterministic reference uses a Laplace-smoothed stay/switch probability after "
        "an earlier choice in the same casino, or an option-position prior for other profiles. "
        "It uses only causal visible history and public train, then refits the same "
        "method for seeds 0, 1, and 2, producing identical weights; these are not independent "
        "Agent research repetitions. The public valid split is used only for scoring and was "
        "not used for this fit. This small model is a pipeline reference, not a "
        "published cognitive model or a hidden-Test result.\n"
    )
    (artifacts / "report.md").write_text(report, encoding="utf-8")
    return {**fitted[0], "independent_final_fits": 3,
            "train_responses": spec["splits"]["train"]["responses"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--contract", required=True, type=Path)
    p.add_argument("--public-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    print(json.dumps(train(a.contract, a.public_dir, a.out), indent=2))
