# Mouse behavior tasks and source preparation

## What is available

Five source-prepared mouse tasks join the v1 collection. Together with the existing tasks, the checkout contains 117 runnable tasks.
All five passed a local fixed-reference CLI workflow: public preparation, frozen submission, evaluator preparation and isolated scoring.
These are engineering acceptance checks, not Agent benchmark results or official source-leaderboard scores.

| Task | Input and submission | Metric and evaluation |
|---|---|---|
| [CalMS21 classification](../tasks/animal-behavior/calms21-classic-classification/README.md) | Two-mouse pose and confidence; four frame-class probabilities | Mean F1 for attack, investigation and mount; public Valid and owner Test |
| [CalMS21 annotation transfer](../tasks/animal-behavior/calms21-annotation-style-transfer/README.md) | Pose plus target annotator; four frame-class probabilities | F1 per annotator, then equal annotator average |
| [CalMS21 few-shot behavior](../tasks/animal-behavior/calms21-few-shot-behavior/README.md) | Pose plus target behavior; binary probabilities | Positive F1 per behavior, then equal average over seven targets; complete score is owner-Test-only |
| [MABe22 representation](../tasks/animal-behavior/mabe22-representation-classification/README.md) | 784 unlabeled UserTrain pose clips; a frozen embedding model | Six evaluator-trained linear probes; sequence-first F1; owner scoring only |
| [MABe22 supervised segmentation](../tasks/animal-behavior/mabe22-supervised-segmentation/README.md) | Re-estimated three-mouse pose; four independent behavior probabilities | macro-F1 on source-positive, pose-valid frames |

The current MABe supervised package supplies pose, not the large video archives.
Source video remains separately available from the original record; no multimodal paper-score reproduction is claimed.
Experiment-day/time-of-day regression, unsupervised segmentation, 3D, position regression and region classification are excluded.

## Source access

Dataset bodies are outside Git. These five tasks use original-source downloads and revisioned local packets, not new Hugging Face mirrors.
The existing hosted task collection is unchanged.
Keep the raw source and mixed preparation roots outside Agent workspaces.

- CalMS21: [official source record](https://data.caltech.edu/records/s0vdx-0k302).
- MABe22: [original source record](https://data.caltech.edu/records/rdsa8-rde65), [re-estimated pose](https://huggingface.co/datasets/WeihanLikk/ResiFuse-MABe22).
- [CalMS preparation commands](../tasks/animal-behavior/_shared/calms_README.md).
- [MABe preparation commands](../tasks/animal-behavior/_shared/mabe_README.md).

The source terms remain separate from the repository's software license.
CalMS source-paper and platform license metadata differ; these checks do not grant new redistribution permission.
MABe pose and original data retain their respective attribution and use conditions.

### Build a revisioned source tree

Use the pinned requirements in the appropriate helper guide.
After source preparation, materialize the checked-in task bindings without rewriting them:

~~~sh
python tasks/animal-behavior/_shared/calms_task_package.py --materialize-only \
  --task-dir tasks/animal-behavior/calms21-classic-classification \
  --prepared /absolute/verified/calms-task1 \
  --local-root /absolute/local-source
~~~

Use the same command for Task 2/3 with their task IDs and prepared roots.
For MABe, use `mabe_task_package.py --materialize-only` with the corresponding task directory.
Existing metadata must match the regenerated plan. Partial metadata, changed bytes and incomplete delivery trees cause an error, not an overwrite.

## Prepare an Agent workspace

Set `BPB_CALMS_PYTHON` or `BPB_MABE_PYTHON` to the corresponding isolated Python environment.
Set `BPB_CACHE_ROOT` to a public-only cache.
Use the source-root variable only for fetching; do not retain it in the Agent environment.

~~~sh
BPB_LOCAL_DATA_ROOT=/absolute/local-source node dist/cli.js fetch calms21-classic-classification --public
node dist/cli.js prepare calms21-classic-classification --workspace /absolute/agent-workspace
~~~

Setup copies only the task's public whitelist.
The source ZIPs, source object arrays, evaluator inputs and evaluator labels are not copied.
MABe representation development receives only 784 keypoint-only UserTrain clips and public protocol metadata.
Its 1,830 evaluation clips and all six-target probe-training labels stay with the evaluator.

## Frozen models and scoring

Each task accepts exactly three model files: `submission/model.py`, `submission/config.json`, and numeric `submission/weights.npz`.
The model loader returns an object with `predict_proba` for classification or `embed` for the representation task.
The task prompt specifies dimensions, class order and context fields.

Submitted Python runs only in a nonroot, network-disabled Docker worker.
The worker receives numeric features, the frozen model and an output directory, never labels or source roots.
The scorer checks artifact hashes before and after inference.
Build the documented image and pass its immutable image ID; there is no host-process fallback.

Public scoring is available for CalMS21 Task 1/2 and MABe supervised segmentation:

~~~sh
node dist/cli.js score /absolute/completed-bundle \
  --isolation docker --inference-image sha256:IMAGE_ID --python /absolute/venv/bin/python
~~~

CalMS21 Task 3 has only one intromission training sequence, so it cannot provide an independent Valid sequence for that target.
Its public diagnostics cover six targets but never fabricate a seven-target aggregate.
The representation task deliberately keeps probe-training labels outside the public packet.
Both tasks use the explicit owner route for a complete score.

## Evaluator-only source packets

The new `bpb-evaluator-source/1` lock binds local prepared files by revision, size and SHA-256.
It does not claim Hugging Face publication or alter the 29 existing hosted evaluator locks.

~~~sh
BPB_LOCAL_DATA_ROOT=/absolute/local-source node dist/cli.js prepare-evaluator TASK_ID \
  --fetch --evaluator-root /absolute/owner/evaluator --cache-root /absolute/owner-cache
node dist/cli.js score /absolute/completed-bundle --private \
  --evaluator-root /absolute/owner/evaluator --isolation docker \
  --inference-image sha256:IMAGE_ID --python /absolute/venv/bin/python
~~~

Private results go to `scores.private.json`.
Do not mount the evaluator root, its cache, or source credentials in an Agent workspace.
Source-public Test labels remain evaluator-only in this workflow; they are not described as historically secret.

## Protocol distinctions

CalMS21 keeps `other` and every background frame. Only `F1_other` is excluded from the main behavior average.
Official Task 2/3 recordings can recur across different annotators or behavior targets.
The source roles are preserved and same-target overlap is rejected. No global animal-disjoint or near-duplicate-disjoint claim is made.

MABe representation scoring uses the approved BrainPilotBench paper-style adaptation.
It preserves source memberships but freezes three sequence-level 80% samples with seeds 0, 1 and 2.
The four manual behavior labels come from a separate source asset, not ResiFuse's oral-contact grouping.
The evaluator trains three balanced Ridge probes per target, combines their votes and averages positive-class F1 by sequence and task.
An all-negative sequence has F1 zero under the declared convention, including a correct all-negative prediction.
This is not exact official leaderboard reproduction.

MABe supervised scoring follows source-positive and pose-valid eligibility.
Excluded all-zero behavior frames are not automatically called unannotated.
This foreground-conditioned metric does not measure false alarms on background frames.
Test input windows are label-independent, and the eligibility mask stays evaluator-owned.

The representation source repeats one all-zero public pose object in seven evaluator files, and shares public protocol metadata.
Only those two audited hashes have explicit public-equivalent declarations. No label is shared.
All other private objects retain the normal Agent-cache rejection rule.

## Airscope remains separate

Three [Airscope candidates](../tasks/calcium-imaging/README.md) remain outside the 117 runnable tasks.
A deeper public-source inspection found and safely inspected 17 labeled social-competition validation examples in a processed PCA cache.
The published checkpoint was selected using validation; this cache does not establish the full planned source task or independent evaluation protocol.
A new small cache-derived task would need its own scope and split decision.
Public availability alone is not the reason for withholding it.

Forced-swim and tail-suspension paired signal/label releases were not found in the inspected public sources.
The selected forced-swim metric is AUC only, but its curve type and multiclass reduction remain unresolved.
No substitute recordings or guessed labels are used.
See the [deep audit](../reports/mouse-closeout-20261026/airscope-deep-audit.json) and [actual cache inspection](../reports/mouse-closeout-20261026/airscope-cache-inspection.json).

## Verification scope

Five `*-cli-acceptance.json` records in [the closeout directory](../reports/mouse-closeout-20261026/) bind the accepted task versions and data locks.
The public records include no Test numbers.
Small deterministic references exercised the interfaces; no research Agent or comparative Agent experiment was run.
Cold-clone materialization checks preserve the checked-in lock bytes.
Fixture and container-boundary tests use software fixtures, never synthetic benchmark data.
