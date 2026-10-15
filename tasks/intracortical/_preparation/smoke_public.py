"""Run metric-interface smoke checks on selected real public Valid assets.

Predictions are deliberately trivial synthetic placeholders, never model output.
No numerical smoke score is printed or saved. Test assets are rejected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from pynwb import NWBHDF5IO
from edit_distance import SequenceMatcher

import prepare


SHARED = Path(__file__).resolve().parent.parent / "_shared"
sys.path.insert(0, str(SHARED))
from metrics import _distance, birdsong, handwriting, regression  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("falcon-h1-reach-grasp", "falcon-h2-handwriting", "falcon-b1-birdsong"), required=True)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare.load_manifest()
    assets = [a for a in prepare.select(manifest, args.task, "public", []) if a["role"] == "valid"]
    root = prepare.safe_destination(args.dest) / "public"
    if not assets:
        raise ValueError("No Valid assets")
    dates = {a["session_date"] for a in assets}
    if len(dates) != 1:
        raise ValueError("Smoke expects exactly one complete Valid date")
    date = dates.pop()
    n_trials = 0
    distance_checks = 0
    samples = []
    for asset in assets:
        path = prepare.file_path(root, asset)
        prepare.verify_one(path, asset)
        with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
            nwb = io.read()
            if asset["source_task_id"] == "h1":
                target = np.asarray(nwb.acquisition["OpenLoopKinematicsVelocity"].data[:])
                mask = np.asarray(nwb.acquisition["eval_mask"].data[:], dtype=bool)
                samples.append((np.zeros_like(target), target, mask))
            elif asset["source_task_id"] == "h2":
                targets = [str(text) for text in nwb.trials.to_dataframe()["cue"]]
                for target in targets:
                    for proposed in ("", target, target[:-1], target[::-1], target.replace(">", " ")):
                        for tokenize in (list, lambda text: text.replace(">", " ").split(" ")):
                            a, b = tokenize(proposed), tokenize(target)
                            if _distance(a, b) != SequenceMatcher(a, b).distance():
                                raise ValueError("Local edit distance differs from FALCON's dependency")
                            distance_checks += 1
                samples.extend(("", target) for target in targets)
                n_trials += len(targets)
            else:
                trials = nwb.trials.to_dataframe()
                for _, trial in trials.iterrows():
                    target = np.asarray(trial["spectrogram_values"]).T
                    mask = np.asarray(trial["spectrogram_eval_mask"], dtype=bool).T
                    # A fixed time ramp is independent of the recording and its target.
                    ramp = np.linspace(0.0, 1.0, target.shape[0], dtype=np.float64)
                    prediction = np.repeat(ramp[:, None], target.shape[1], axis=1)
                    samples.append((prediction, target, mask))
                    n_trials += 1
    if args.task == "falcon-h1-reach-grasp":
        result = regression({date: samples})
        n_valid = result["valid_timesteps"][date]
    elif args.task == "falcon-h2-handwriting":
        result = handwriting({date: samples})
        n_valid = result["trials_per_session"][date]
    else:
        result = birdsong({date: samples})
        n_valid = result["motifs_per_session"][date]
    # This confirms arithmetic and dimensions only. Placeholder scores would
    # have no research meaning, so no result values leave this process.
    print(json.dumps({"task": args.task, "role": "valid", "date": date,
                      "assets": len(assets), "complete_units": n_valid,
                      "official_edit_distance_comparisons": distance_checks,
                      "metric_interface_executed": True,
                      "predictions": "synthetic_placeholder_not_a_model"}, sort_keys=True))


if __name__ == "__main__":
    main()
