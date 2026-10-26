# CalMS21 classic classification

Which social behavior occurs in each frame of a two-mouse recording?
Learn from pose coordinates and tracking confidence to distinguish attack, investigation, mount and other.

## Task at a glance

| Field | Contract |
|---|---|
| Input | Two mice, seven 2D keypoints each, with tracking confidence |
| Output | Four class probabilities per frame; the highest probability selects the class |
| Split | 56 Train and 14 derived Valid sequences from official Train; 19 official Test sequences remain evaluator-only |
| Metric | Mean F1 for attack, investigation and mount; all other frames remain in scoring |
| Model | Frozen Python inference program and numeric weights; Docker-isolated execution |

The `other` class remains a training and prediction target. Only its own F1 is excluded from the behavior average.
A background frame predicted as attack is an attack false positive.
The derived validation split uses whole recordings and does not claim animal-disjoint generalization.

## Prepare and run

Use the [official source record](https://data.caltech.edu/records/s0vdx-0k302) and [preparation helpers](../_shared/calms_README.md).
The [mouse task guide](../../../docs/mouse-task-preparation.md) covers source materialization, public preparation and explicit private scoring.
The [protocol](protocol.json) and [contract](contract.json) pin labels, split rules, byte hashes and model inputs.
Submit `submission/model.py`, `submission/config.json` and numeric `submission/weights.npz`.
The model implements `load_model(config, weights_path).predict_proba(keypoints, scores, context)`.

## Verification status

The complete local CLI workflow passed with a fixed public-Train reference, including isolated owner Test scoring.
See the [acceptance record](../../../reports/mouse-closeout-20261026/calms21-classic-classification-cli-acceptance.json).
This is not an Agent benchmark result or an official CalMS21 score. No Test numbers are published here.
Source data remain locally prepared and have not been mirrored to Hugging Face.
