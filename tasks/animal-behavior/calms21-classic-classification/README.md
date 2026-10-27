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

Install the environment in the [mouse task guide](../../../docs/mouse-task-preparation.md), then download the pinned public package:

```sh
node dist/cli.js fetch calms21-classic-classification --public
node dist/cli.js prepare calms21-classic-classification --workspace /absolute/agent-workspace
```

The [public HF directory](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/main/tasks/animal-behavior/calms21-classic-classification/public) is for navigation. The data locks select fixed revisions.
The [official source](https://data.caltech.edu/records/s0vdx-0k302) and [helpers](../_shared/calms_README.md) remain available for regeneration.
The [data notice](NOTICE.md) records attribution, source permissions, and the CalMS license-metadata difference.
The [protocol](protocol.json) and [contract](contract.json) pin labels, split rules, byte hashes and model inputs.
Submit `submission/model.py`, `submission/config.json` and numeric `submission/weights.npz`.
The model implements `load_model(config, weights_path).predict_proba(keypoints, scores, context)`.

## Verification status

The complete local CLI workflow passed with a fixed public-Train reference, including isolated owner Test scoring.
See the [acceptance record](../../../reports/mouse-closeout-20261026/calms21-classic-classification-cli-acceptance.json).
This is not an Agent benchmark result or an official CalMS21 score. No Test numbers are published here.
The [HF publication record](../../../reports/mouse-hf-20261027/publication.json) binds the mirrored public and private packages to the accepted content.
This transport update does not rerun the scientific reference or change its score.
