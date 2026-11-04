# Task A — incremental brain prediction

Protocol: `pereira384-incremental-ridge-v2`; task: `alignment-incremental-explanation`,
version `0.2-server-draft`. Experimental derived analysis, scientific acceptance
pending. This is not the official Pereira2018 Brain-Score metric or a reproduction
of every method in Hadidi et al.

## Research question and choices

Does a fixed model representation add held-out brain prediction beyond the simple
stimulus attributes you declare? Choose exactly one `control_set`:

- `word_count`: whitespace-delimited sentence word count.
- `position`: four one-hot indicators for sentence position in its passage.
- `word_count+position`: both sets of variables.

Write `submission/plan.json` containing exactly `protocol_id`, `control_set`, and
a nonempty `rationale` of at most 4000 characters. Explain the selected alternative
explanation and the controls you have not evaluated. Multiple choices are valid;
the grader recomputes the declared analysis. It does not reward a positive increment
or infer that your chosen controls exhaust all explanations. Rationale quality and
free-form scientific reasoning need human review; the automated metric verifies
calculations and bounded structured statements.

The model layer is fixed in `inputs/provenance.json` before this task analysis.
All model features and brain responses are visible because your program must
perform nested cross-validation. This is an analysis task: the submitted source
and plan are replayed together, but there is no hidden prospective confirmation
phase. The existing data have already been inspected in other integration work.
Do not describe the plan as preregistered or the dataset as previously unseen.

## Inputs

`manifest.json` records the exact public inventory and SHA-256 hashes.

| File | Meaning |
|---|---|
| `features.npy` | Fixed model features, rows in `stimuli.json` order |
| `brain.npy` | Finite responses; rows in stimulus order, columns in `neuroids.json` order |
| `controls.npy` | Five float64 columns: word count, position 1, 2, 3, 4 |
| `stimuli.json` | IDs, text, story group, passage and original `stimulus_num` |
| `neuroids.json` | Unique `neuroid_id` and `subject_id` for every response column |
| `splits.json` | Outer train/test IDs and each outer fold's inner train/test IDs |
| `protocol.json` | Numerical rules, hyperparameters and inference scope |
| `provenance.json` | Original cache, model/tokenizer revisions and fixed layer |

Match by identities, not accidental sorting. Sentence position is the rank of
`stimulus_num` **within each passage**; `passage_index` identifies a passage and
is not sentence position. Each passage has four sentences. Word count is
`len(stimulus.split())`, not tokenizer length or measured speech rate.
In this Pereira cache, the upstream `story` coordinate is the experiment name
plus passage category (24 topical groups). A group is not a continuous long
narrative. Holding it out keeps all its passages together.

## Required analysis

Compare three separate readouts: `control` = C, `model` = X, and `joint` = [C, X].
The owner excludes response columns that are exactly constant across the supplied
dataset before any fitting, logging every excluded ID in `provenance.json`.
In the initial real packet, 18 all-zero columns are excluded, leaving 12,137.
This defines the target set using full-dataset quality control, not prediction
performance, and is not presented as a training-only selection procedure.
Use all retained supplied response columns. Keep the same samples and outer folds for all
readouts. The protocol is frozen as follows:

1. Outer folds: sort unique story names, permute with NumPy `default_rng(41)`,
   partition with `array_split(..., 5)`. Each partition is held out once.
2. Inner folds: within outer training stories use the same construction with
   three folds and seed `42 + outer_fold_index`. `splits.json` is authoritative.
3. Fit feature mean and population SD (`ddof=0`) only on the current training
   partition, replace zero SD with 1, and transform train and validation/test
   using these training statistics. Center Y by the training mean. The ridge
   intercept is unpenalized. Do not fit scalers on all outer training data before
   inner validation. Do not standardize Y, fit PCA, or normalize by a ceiling.
4. Candidate alphas are `[0.1, 1, 10, 100, 1000, 10000, 100000, 1000000]`. For each readout independently,
   select a single shared alpha by maximizing pooled inner held-out R², aggregated
   equally over subjects and equally over neuroids within subject. Use each inner
   training mean as its validation baseline. Pool sums of squared errors and
   baseline deviations across the inner validation folds **before** division.
   Select the smallest alpha in an exact tie. Refit on outer training data.
5. Save one outer held-out prediction for every stimulus and every neuroid, for
   each readout. Outer test Y must not enter fitting or alpha selection.

For neuroid j, the primary score is:

```text
R2_j = 1 - sum_i((Y_ij - prediction_ij)^2)
           / sum_i((Y_ij - mean(Y_outer_train_for_i,j))^2)
```

The sums pool all outer test observations. Average R² within each subject, then
average those subject means equally. `delta_R2 = R2_joint - R2_control`.
Negative scores and increments are retained. Nonpositive baseline denominators
are errors; never silently remove response columns. This is a predictive
increment under the specified readout/controls, not a causal contribution or
unique biological variance decomposition.

Uncertainty is a **descriptive conditional interval**: with `default_rng(73)`,
draw 1000 arrays of story indices with replacement, each of length the number
of stories (sorted story names define indices). Use the same draws for all
subjects/readouts. Pool the selected stories' fixed OOF squared errors and
baseline deviations, recalculate the aggregate increment, then use NumPy's
default linear percentiles 2.5 and 97.5. Do not resample CV folds as independent
participants. This calculation does not refit models or capture training-set
uncertainty/dependence; it is not a calibrated confirmatory significance test.

## Submission and output

Implement `submission/analyze.py --inputs DIR --output DIR`. Additional source
files under `submission/` are allowed. The evaluator provides the same immutable
inputs, a fresh output directory, NumPy and the installed scientific Python
environment. No reference answers, model weights or network are provided.

Save these artifacts in the workspace (and regenerate them in `--output`):

- `analysis_plan.json`: exactly the submitted `plan.json`.
- `results/predictions.npz`: five arrays: `control`, `model`, `joint` (float64,
  stimulus × neuroid), `stimulus_ids`, `neuroid_ids` (1D Unicode). Permuting rows
  or columns is valid if IDs move with predictions. Pickled/object arrays are forbidden.
- `results/folds.json`: list in frozen outer-fold order, each with `fold_id`,
  `train_ids`, `test_ids`, and `readouts`. Each readout has `alpha` and `inner_r2`
  (eight scores in the declared alpha order).
- `results/summary.json`: structure specified below.
- `conclusion.json`: bounded evidence statement specified below.
- `report.md`: chosen explanation, method, numerical evidence, interpretation and
  limitations. Presence is checked; prose quality is not automatically graded.

Summary structure (values shown as type placeholders, not expected results):

```json
{
  "schema": "bpb-incremental-summary/1",
  "protocol_id": "pereira384-incremental-ridge-v2",
  "synthetic_only": false,
  "input_manifest_sha256": "SHA256 of inputs/manifest.json",
  "control_set": "YOUR CONTROL SET",
  "coverage": {"stimuli": 384, "stories": 24, "subjects": 9, "neuroids": 12137, "outer_folds": 5},
  "scores": {
    "control": {"mean_r2": 0.0, "subjects": {"SUBJECT_ID": 0.0}},
    "model": {"mean_r2": 0.0, "subjects": {"SUBJECT_ID": 0.0}},
    "joint": {"mean_r2": 0.0, "subjects": {"SUBJECT_ID": 0.0}}
  },
  "increment": {"mean_delta_r2": 0.0, "subjects": {"SUBJECT_ID": 0.0}, "descriptive_interval": [0.0, 0.0]},
  "uncertainty": "COPY protocol.json uncertainty VALUE",
  "scope": "observed_subjects_heldout_story_groups",
  "official_benchmark_equivalence": false
}
```

All actual subjects must appear. Subject increments are joint-minus-control
subject scores. Read coverage from the supplied arrays rather than hard-coding
the example values.

`conclusion.json` contains exactly:

```json
{
  "protocol_id": "pereira384-incremental-ridge-v2",
  "control_set": "YOUR CONTROL SET",
  "interval_result": "positive_interval OR negative_interval OR interval_includes_zero",
  "scope": "observed_subjects_heldout_story_groups",
  "uncertainty": "conditional_on_fitted_oof_predictions",
  "causal_effect_established": false,
  "all_confounders_ruled_out": false,
  "new_subject_generalization_tested": false,
  "equivalence_established": false
}
```

Use `positive_interval` only if the lower bound is >0, `negative_interval` only
if the upper bound is <0; otherwise use `interval_includes_zero`. These labels
describe the conditional interval, not a proof of a scientific hypothesis.

## Evaluation boundary

The owner computes a reference for the submitted control choice, then replays
the submitted program in Docker. Inputs/source are read-only; the worker has no
network, no reference mounts, a non-root UID and bounded CPU/memory/time. Saved
and rerun outputs must both agree, with provisional atol 1e-7 and rtol 1e-5.
Predictions and alpha-selection diagnostics are verified, not just scalar scores.
This tests reproducible protocol execution and bounded evidence interpretation;
it does not prove that arbitrary submitted code never read a test response.

`analysis_success=1` means all required checks passed, regardless of the sign of
the scientific result. Invalid output or a started program failure gives 0.
Missing runtime, failed container launch or reference failure produces
`scoring_failed` and no Agent score. Output is bounded to 512 MiB; report to 2 MiB.
The default worker limits are 2 CPUs, 8 GiB and 900 seconds, subject to resource
calibration. Process mode is an explicitly trusted maintainer test harness only.

The fixed script baseline can satisfy the numerical contract completely.
Automated success alone is not evidence of autonomous confound discovery,
experimental-design quality or superiority over researchers.

Version 2 extends the alpha grid because every model/joint inner-validation
selection in the initial version-1 pilot hit the old maximum of 1000. The old
results are retained as development evidence. This change was motivated by
training-fold diagnostics; it is not an independent confirmation study.
