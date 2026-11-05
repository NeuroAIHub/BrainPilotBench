# CalMS21 few-shot behavior recognition

Can a model recognize new social behaviors from a small number of labeled recordings?
Each of seven targets is a separate binary classification problem using the same two-mouse pose format.

## Task at a glance

| Field | Contract |
|---|---|
| Input | Two-mouse pose, tracking confidence and target behavior |
| Output | Other/target probabilities per frame |
| Split | 11 Train sequences across seven targets; six derived Valid sequences; 109 official Test sequences |
| Metric | Positive-class F1 per behavior, then equal average over all seven targets |
| Complete score | Explicit owner Test route only |

The intromission target has only one official Train sequence.
It stays in Train, so no independent Valid sequence is invented for that target.
Public diagnostics cover six targets and do not produce a seven-target aggregate F1.
Official recordings can recur across different targets; same-target Train/Test overlap is rejected.

## Prepare and run

Install the environment in the [mouse task guide](../../../docs/mouse-task-preparation.md), then download the pinned public package:

```sh
node dist/cli.js fetch calms21-few-shot-behavior --public
node dist/cli.js prepare calms21-few-shot-behavior --workspace /absolute/agent-workspace
```

The [public HF directory](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/main/tasks/animal-behavior/calms21-few-shot-behavior/public) is for navigation. The data locks select fixed revisions.
The [official source](https://data.caltech.edu/records/s0vdx-0k302) and [shared helpers](../_shared/calms_README.md) remain available for regeneration.
The [data notice](NOTICE.md) records attribution, source permissions, and the CalMS license-metadata difference.
The [protocol](protocol.json) and [contract](contract.json) specify all seven groups and the missing validation target.
Submit a frozen model with `predict_proba(keypoints, scores, context)`; the context supplies the target behavior.
Use `score --private` for the complete score. Default public scoring remains unscored rather than reporting a partial aggregate.
The public-Train reference builder is `solution/reference.sh`; this task has no public Oracle script.

## Verification status

The frozen reference passed actual CLI preparation, submission verification and isolated owner scoring for all seven targets.
See the [acceptance record](../../../reports/mouse-closeout-20261026/calms21-few-shot-behavior-cli-acceptance.json).
This is not an Agent benchmark result. Test numbers remain private.
The [HF publication record](../../../reports/mouse-hf-20261027/publication.json) binds the mirrors to the accepted content.
This transport update does not rerun the scientific reference or change its score.
