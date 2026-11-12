# Brain-Score analysis contract v1

Implement `python submission/analyze.py --inputs DIR --output DIR`. Read only the supplied local inputs; write results to the output directory. No downloads or weights are needed for cached analysis. Public responses are visible: scientific held-out folds are not hidden labels.

`manifest.json` binds the instance and file hashes. `instance.json` supplies the template and the declared benchmark/candidate comparison order. `bundle.json` lists `case-NN` caches in their declared order. Each cache binds one benchmark and one candidate, with numerical arrays, metadata and provenance. Candidate rows use `candidate_presentation_ids`; target rows use `presentations[].presentation_id`. Align by these IDs. Preserve original typed stimulus IDs in `_upstream_stimulus_id`, source grouping coordinates, measurement identities and response masks. Do not impute, silently drop or relabel missing responses. Normalized scores are scientific results, not your task score.

## Methods

Every cache freezes `protocol.official_specification`, `protocol.folds` and `protocol.ceiling`. Use the pinned official packages available in the matching Vision or Language environment. The supplied features already include the committed model layer, image transform or text context. Do not perform layer search, feature selection or additional scaling.

| Source | Official calculation |
|---|---|
| MajajHong public | `brainscore_vision` PLS, stratification by `object_name` |
| FreemanZiemba public | `brainscore_vision` PLS, stratification by `texture_type` |
| Pereira / Fedorenko / Blank | `brainscore_language` ridge Pearson metric; group by story / sentence_id / story |
| Futrell | Direct model reading-time outputs; exclude `word_within_sentence_id == 1`, average responses across subjects with the official missing-value semantics, then official Pearson metric |

Vision uses upstream `PLSRegression(n_components=25, scale=False)`, with 10 stratified shuffle splits, train fraction .9 and seed 1. Language uses upstream `RidgeGCVTorch` with alphas 10^-3 through 10^3, not sklearn RidgeCV. GroupKFold uses shuffle and seed 1234; Blank has 8 folds and the other neural language sources have 10. The frozen split manifest is authoritative and must agree with the official splitter.

Neural aggregation is median neuroids within each fold, then mean folds. Vision normalization is raw r squared divided by the supplied ceiling without clipping. Language normalization divides raw by ceiling and clips to [0,1], retaining the unclipped value. Futrell's official raw metric is **absolute r**: also retain signed `rvalue` and `pvalue`; its model output is surprisal in bits, not measured milliseconds. Do not add a fitted readout or invented CV folds to Futrell.

## Required artifacts

- `results/summary.json`: schema `bpb-bs-analysis/1`; `instance_id`, `template`, `input_manifest_sha256`, `synthetic_only`, `cases`, `comparisons`, and `official_equivalence: "requires-live-reference-evidence"`.
- Each case: `id` (`case-NN`), `benchmark_id`, `candidate_id`, `cache_manifest_sha256`, `score`, and `decomposition`.
- Each score: `raw`, `ceiling`, `normalized`, `unclipped`, `normalization`, and `aggregation` copied from the frozen method semantics. Futrell additionally includes `signed_r`, `pvalue`, and source-order `included_ids`.
- `results/trace.json`: a list in case order. Each entry has `case_id`, `kind` (`neural` or `behavior`) and `folds`.
- Neural folds: `id`, `train_ids`, `test_ids`, `unit_ids`, `alpha` (null for PLS), `predictions_file`, `unit_scores_file`. Prediction arrays are test presentation × measurement; unit score arrays are one-dimensional. Fold and array identities are checked, not just the final scalar. Arrays must be floating-point `.npy` without pickle; IDs live in JSON.
- Behavior traces: `folds: []`, `presentation_ids`, `unit_ids`, `reading_times_file`, `response_valid_file`, `included_file`. These arrays contain all model outputs, the exact presentation × subject response-valid mask, and the sentence-first-word exclusion mask. Missing model outputs remain NaN. Masks are boolean `.npy`.
- `conclusion.json` and nonempty `report.md`; submitted source in `submission/`. Helper source files may be included. `runtime.json` is optional and never trusted as scoring authority.

All array filenames are simple names within `results/`, without path separators. Cache arrays are memory-mapped and bounded to 8 GiB per file; large pixel features may need more memory than the provisional worker default. Numerical outputs together must fit the provisional 512 MiB limit. Numerical comparison currently uses atol=1e-6 and rtol=1e-5; these are experimental tolerances awaiting real resource calibration. Ordering of trace prediction rows and units may vary if their IDs and values agree.

## Descriptive decomposition

Keep these summaries separate from the official score, including for T1 so T2 can compare the same evidence.

For neural cases, `decomposition` contains:

- `definition: "subject: median finite units per fold then mean defined folds; stimulus groups: pooled test-occurrence signed Pearson then median defined units"`.
- `repeated_test_occurrences_are_not_independent: true`.
- `subjects`: sorted subject IDs, each with `subject_id`, `mean_fold_median_r`, `fold_count`. Compute the median finite unit r for that subject within each fold, then the mean across defined folds. Report the number of defined folds; retain null when none are defined. No unrecorded subject identity is invented.
- `stimulus_groups`: for each available coordinate in order `story`, `texture_type`, `object_name`, iterate sorted string labels. Pool recorded held-out prediction/target pairs for that label, preserving repeated occurrences across shuffle splits. Compute ordinary signed Pearson per unit using finite pairs and at least 3 samples with nonzero variance, then median defined unit correlations. Each row has `coordinate`, `value`, `test_occurrences`, `valid_units`, `median_signed_r` (null if undefined).

For behavioral cases, `decomposition` contains `definition: "signed Pearson on finite pairs after official first-word exclusion; descriptive only"`, `subjects` and `stories`. Each subject row has `subject_id`, `signed_r`, `valid_words`. Each available story row has `story`, `signed_r_vs_subject_mean`, `valid_words`. Use source-order subjects and sorted story labels; retain null when fewer than 3 valid pairs or zero variance prevents correlation. No significance claim follows from these decompositions or the upstream p-value alone.

## Comparison and conclusions

T1 has `comparisons: []`. T2 compares two fixed candidates within each declared benchmark, retaining each brain region/experiment. The two caches must have identical target identities, responses, exclusions and protocols. In the registry's candidate order, each comparison has `benchmark_id`, `first`, `second`, `second_minus_first_normalized`, `ranking`, and `scope: "descriptive_within_supplied_stimuli_and_units"`. Ranking is the higher normalized score's candidate ID, or `numerical_tie` when the absolute difference is <=1e-6. Keep comparisons in declared benchmark order.

`conclusion.json` has schema `bpb-bs-conclusion/1`, the instance ID and template, `scope: "supplied_stimuli_and_measurement_units"`, and these fields: `causal_effect_established: false`, `new_subject_generalization_tested: false`, `cv_folds_are_independent_samples: false`, `model_quality_is_analysis_success: false`, and `rankings` equal to the comparisons list. Explain coverage, negative results and limitations in the report.

## Evaluation

The owner recomputes a reference and reruns submitted code in a container with no network, read-only source/inputs and no owner answers. The evaluator also changes supplied inputs: neural controls perturb only the first fold's held-out responses; behavioral controls rotate included model predictions. Recompute from the supplied packet each run. Fixed answers, altered masks, wrong splits, wrong aggregation and mismatched saved outputs fail. Submission stdout cannot assign a score.

`analysis_success=1` requires the saved artifacts (when supplied), rerun and functional control to pass. A correct negative result can pass. Missing datasets, images, dependencies or invalid owner inputs are infrastructure failures, with no task score. Prose quality and independent scientific/Agent acceptance remain separate reviews. Synthetic instances validate software only and never establish real-data equivalence.
