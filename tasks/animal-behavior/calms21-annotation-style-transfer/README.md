# CalMS21 annotation-style transfer

Can a behavior model adapt to another annotator's definitions of the same social actions?
Use limited labeled recordings to reproduce each of five annotators' framewise decisions.

## Task at a glance

| Field | Contract |
|---|---|
| Input | Two-mouse pose, tracking confidence and target annotator |
| Output | Attack, investigation, mount and other probabilities per frame |
| Split | 20 Train and 10 derived Valid sequences; 47 official Test sequences remain evaluator-only |
| Metric | Three-behavior mean F1 within each annotator, then equal average across five annotators |
| Model | One frozen model can condition predictions on the annotator context |

Official roles contain some identical pose recordings across different annotators.
These source roles are preserved; the task does not claim globally unseen recordings across annotator groups.
Same-target Train/Test overlap is rejected. Derived Train/Valid grouping uses exact pose fingerprints, not frame-level random splitting.
Background frames remain in evaluation.

## Prepare and run

Use the [official source record](https://data.caltech.edu/records/s0vdx-0k302), [shared helpers](../_shared/calms_README.md) and [mouse task guide](../../../docs/mouse-task-preparation.md).
The [protocol](protocol.json) defines the annotation groups; the [contract](contract.json) binds source and prepared files.
The inference API is `load_model(config, weights_path).predict_proba(keypoints, scores, context)`.
The context identifies the target annotator. Submitted code runs only in a network-disabled Docker worker.

## Verification status

A fixed public-Train reference passed the complete local CLI workflow and isolated owner scoring.
The [acceptance record](../../../reports/mouse-closeout-20261026/calms21-annotation-style-transfer-cli-acceptance.json) is engineering evidence, not an Agent or official source score.
No Test numbers are published, and the data have not been mirrored.
