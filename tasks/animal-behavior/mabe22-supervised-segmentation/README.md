# MABe22 supervised behavior segmentation

Can a supervised model identify social behaviors from the poses of three interacting mice?
Predict chases, huddles, oral contact and oral-genital contact at each frame using re-estimated pose tracks.

## Task at a glance

| Field | Contract |
|---|---|
| Input | Three mice, twelve 2D keypoints each, with likelihood and source missing observations |
| Output | Four independent probabilities per frame, thresholded at 0.5 |
| Split | 54 Train, 11 Valid and 43 evaluator-only Test clips |
| Metric | macro-F1 over four grouped labels, on source-positive and pose-valid frames |
| Input scope | Pose-only package; large original videos were not downloaded or included |

The current profile follows ResiFuse's supervised label grouping, not its unsupervised clustering task.
ResiFuse is a reference method, not a required model architecture.
The input windows are label-independent. Test labels and eligibility masks never enter the inference container.
The foreground-conditioned metric does not measure false alarms on background frames.
Excluded all-zero labels are not automatically described as unannotated.

## Prepare and run

Install the environment in the [mouse task guide](../../../docs/mouse-task-preparation.md), then download the pinned public package:

```sh
node dist/cli.js fetch mabe22-supervised-segmentation --public
node dist/cli.js prepare mabe22-supervised-segmentation --workspace /absolute/agent-workspace
```

The [public HF directory](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/main/tasks/animal-behavior/mabe22-supervised-segmentation/public) is for navigation. The data locks select fixed revisions.
The [original labels](https://data.caltech.edu/records/rdsa8-rde65), [re-estimated pose](https://huggingface.co/datasets/WeihanLikk/ResiFuse-MABe22), and [runbook](../_shared/mabe_README.md) remain available for regeneration.
The [data notice](NOTICE.md) preserves the distinct licenses for original labels, derived pose, and source split metadata.
The [protocol](protocol.json) records frame indexing, coordinate scale, valid-pose rules and source adaptations.
The [contract](contract.json) pins the final role packets. The [mouse task guide](../../../docs/mouse-task-preparation.md) gives the CLI workflow.
The model implements `load_model(config, weights_path).predict_proba(keypoints, scores, context)` and returns finite `[1800,4]` probabilities.

## Verification status

All 108 selected pose files were prepared; the slim public packet and owner packet passed isolated reference scoring.
The [CLI acceptance record](../../../reports/mouse-closeout-20261026/mabe22-supervised-segmentation-cli-acceptance.json) covers actual preparation, frozen submission and private scoring.
This is a BrainPilotBench adaptation, not an exact ResiFuse paper-score reproduction or an Agent benchmark result.
Test scores remain private. The [HF publication record](../../../reports/mouse-hf-20261027/publication.json) binds the mirrors to the accepted content.
This transport update does not rerun the scientific reference or change its score.
