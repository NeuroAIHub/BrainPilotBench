# MABe22 mouse representation classification

Do learned mouse representations retain information about experimental conditions and social behavior?
Train an embedding model on unlabeled pose clips, then let fixed linear probes evaluate six classification targets.

## Task at a glance

| Field | Contract |
|---|---|
| Agent input | 784 keypoint-only UserTrain clips, without source behavior labels |
| Model output | Finite `[1800,d]` embeddings with a common dimension `1 <= d <= 128` |
| Evaluator input | 1,830 submission pose clips; separate probe-training and Test labels |
| Targets | Strain, lights, chase, huddle, face sniff and anogenital sniff |
| Metric | Sequence-first positive F1, then equal average over six targets |
| Complete score | Three fixed Ridge probes per target; explicit owner scoring only |

The approved BrainPilotBench profile retains source memberships and freezes three sequence-level 80% samples with seeds 0, 1 and 2.
It follows the paper's linear-probe method but is not exact official leaderboard reproduction.
The four manual behavior labels come from a separate 400-clip source asset, not ResiFuse's oral-contact labels.
The original source split does not establish animal-disjoint generalization.
An all-negative sequence has F1 zero under the declared convention, even if every prediction is correct.
Experiment-day and time-of-day regression are excluded.

Only the evaluator passes submission poses to the frozen model, inside a network-disabled Docker worker.
Probe-training labels stay on the trusted host. Test labels remain evaluator-only.
The Agent development packet contains neither evaluation poses nor probe-training labels.
One all-zero UserTrain object is byte-identical to seven evaluator inputs, and protocol metadata are shared.
The [bounded audit](../../../reports/mouse-closeout-20261026/mabe-shared-public-content.json) declares these two already-public hashes. No label is shared.

## Prepare and run

Use the [preparation runbook](../_shared/mabe_README.md) and [mouse task guide](../../../docs/mouse-task-preparation.md).
The [protocol](protocol.json) and [contract](contract.json) pin sampling, probe fitting and role-separated files.
Submit `load_model(config, weights_path).embed(keypoints, scores, context)` in the three-file model bundle.
The public-Train reference builder is `solution/reference.sh`. There is no public Oracle label set; complete scoring uses `score --private`.

## Verification status

The [CLI acceptance record](../../../reports/mouse-closeout-20261026/mabe22-representation-classification-cli-acceptance.json) covers public preparation, a frozen PCA reference and isolated evaluator scoring.
All 1,830 evaluation clips were processed; Test numbers were kept private.
These checks do not report Agent performance. Data remain source-prepared, with no Hugging Face mirror.
