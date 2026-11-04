# Experimental alignment tasks B–F

These are derived research-analysis tasks. They are not official Brain-Score
benchmarks. A has its own [contract](INCREMENTAL_CONTRACT.md). Read the active
`inputs/protocol.json` and `inputs/metadata.json`; the task letter is recorded in
`inputs/manifest.json`. All numerical inputs are finite, pickle-free `.npy`
arrays. The owner verifies the complete manifest. Never infer identity from row
number alone. Scientific review and independent Agent acceptance are pending.
B uses protocol `pereira384-context-v2`; C–F use their version-1 profiles. B v2
removes irrelevant A-only control/increment fields from the public specification
and declares the two actual context contrasts explicitly; its numerical procedure
and results are unchanged from B v1.

## Common submission and scoring

Implement `submission/analyze.py --inputs DIR --output DIR`, with all dependencies
included in `submission/` except installed NumPy/SciPy. It must run without network,
GPU, model weights, owner code or access outside its public inputs. Put its declared
plan in `submission/plan.json`. Write into the requested output directory, which
already exists and is empty during replay. Do not write to inputs/source.

Plan fields are exactly `protocol_id` and a nonempty `rationale` of at most 4,000
characters; E also requires integer `window` (20 or 40), and C/D require
`candidate_pair: [first, second]`, two distinct zero-based candidate indices.
Candidate order comes from metadata. The plan is an analysis declaration, not
evidence of prospective preregistration: B–E expose the analysis data.

Required outputs are `analysis_plan.json` (exact plan), `results/summary.json`,
the task's arrays below, `conclusion.json`, and a nonempty `report.md` under 2 MiB.
Every summary includes `protocol_id` and `input_manifest_sha256`, the SHA256 of
the input manifest file. Numerical result arrays use float64 unless explicitly
specified; ID arrays use Unicode strings and preserve the documented input order.
Use `.npy`, not pickled objects. Extra/missing numerical result arrays fail B–E.
Total submitted output must not exceed 512 MiB. Use finite JSON numbers, no NaN,
duplicate JSON keys, symlinks, or special files.

B–E receive `analysis_success=1` only if the saved artifacts and isolated source
replay agree with trusted recomputation, including the declared plan, every
required array, diagnostics, and structured interpretation. Numeric tolerance is
absolute 1e-7 plus relative 1e-5. Negative/inconclusive scientific results are valid.
The rationale/report's scientific prose is **not** automatically assessed; report
presence is checked. Fixed scripts can solve these tasks, so this score certifies
bounded analysis execution and explicit interpretation checks, not autonomous
scientific discovery. Infrastructure failures emit no score.

F has a separate decision metric and one-submission rule below. Source replay is
offline Docker with read-only inputs/source, a non-root user, dropped capabilities,
CPU/memory/time limits, and output-only writes. The operator must separately isolate
the Agent during development; CLI manual mode alone does not isolate an Agent.

## B: short-context dependence

Inputs contain `brain.npy` (target × neuroid) and the equally sized feature matrices
`sentence_only.npy`, `normal_prefix.npy`, `reversed_prefix.npy`. Metadata identifies
stimuli, neuroids/subjects, exact past-only contexts, token lengths, excluded IDs,
and frozen nested story splits. Targets are sentence positions 3/4 of four-sentence
passages. Normal/reversed contexts contain exactly the same preceding sentences;
all prior order is reversed, including recency. Future text is absent. Keep only
equal normal/reversed token-count targets, identically for every condition.

Use the same ridge/readout definitions as A: train-only feature mean/population
SD (zero SD→1), centered Y with unpenalized intercept, float64, alpha grid
0.1/1/10/100/1,000/10,000/100,000/1,000,000. Select a shared alpha per readout on
pooled inner-fold R² (baseline is each inner training mean), equal subject means
after averaging neuroids within subject. Exact ties select the smallest alpha.
Outer R² pools held-out squared errors and training-mean baseline errors over all
folds, then averages within and between subjects. Never clip or ceiling-normalize.
The 1,000-draw seed-73 paired story bootstrap resamples already fitted outer errors
and baselines. Its percentile interval is descriptive and conditional on these
predictions; it excludes refitting uncertainty. Splits group `story`, which here is
a topic category, not a continuously presented long story.

Arrays: `sentence_only.npy`, `normal_prefix.npy`, `reversed_prefix.npy` contain
outer-fold predictions, target × neuroid; `stimulus_ids.npy`, `neuroid_ids.npy` give
their order. Summary keys beyond the common keys:

- `scores`: condition → mean R².
- `comparisons`: `sentence_only` and `reversed_prefix` → `{delta_r2, interval}`;
  each difference is normal-prefix minus that condition, interval is `[low, high]`.
- `folds`: ordered records with `fold_id`, `train_ids`, `test_ids`, `readouts`;
  readouts maps each condition to `{alpha, inner_r2}` in alpha-grid order.
- `targets`, `excluded_token_mismatches`: integer counts.

Conclusion: `intervals` maps the two comparison names to `positive` if low>0,
`negative` if high<0, otherwise `includes_zero`; `scope` is
`observed_subjects_heldout_story_groups`; `uncertainty` is
`conditional_on_fitted_oof_predictions`. `human_context_intervention`,
`long_term_memory_tested`, and `causality_established` are false. Human measurements
were not recollected under the altered model contexts.

## C: neural–behavioral rankings

This first profile uses 100 THINGS IT test images (one exemplar per concept),
three measured fMRI subjects and real odd-one-out choices. Candidates are frozen
distilgpt2 first-block/final-block representations of `a photograph of <concept>`.
They are language representations of concept labels, **not visual-model features
of the displayed photographs**. Behavior is concept matched and comes from
different people. The author behavior `trainset.txt` already uses sorted,
zero-based `unique_id` indices with the chosen similar pair first. Do not apply
`sortind` a second time. These are new derived splits of that public source table.

Inputs: `features.npy` (candidate × concept × feature), `neural_rdms.npy`
(subject × concept × concept), `triplets.npy` (trial × 3 integer indices),
`triplet_partition.npy` (0=train, 1=discovery, 2=confirmation) and
`source_triplet_rows.npy`. Neural RDMs are correlation distances of each subject's
repetition-averaged IT responses. Metadata records image IDs and repeat counts.

Sort concept IDs, permute with `numpy.random.default_rng(41)`, partition into
40%/30%/remaining (integer floors), then preserve input order within partitions.
Retain only triplets wholly within one partition. Candidate RDMs are cosine
distance: `clip(1-normalize(X)@normalize(X).T,0,2)`. Neural score is Spearman
correlation on strict upper triangles within a partition, average ties in ranks,
equal mean across subjects. Undefined constant RDMs fail explicitly.

For each candidate, a triplet's pair logits are negative cosine distances divided
by temperature, in pair order (0,1), (0,2), (1,2). The observed pair is (0,1).
Fit temperature by minimum mean training NLL on [0.01,0.1,1,10,100], smallest exact
tie. Apply the frozen temperature to all partitions. Never fit on confirmation.

Summary: `candidates`, `partitions`, `temperatures`; `neural_rsa` and
`behavior_nll` (candidate × partition); `trial_counts`; verbatim metadata
`matching`, `candidate_scope`; and `contrasts` for discovery/confirmation.
Each contrast has `neural_first_minus_second`, `behavior_second_minus_first_nll`
(both positive favor first), `concept_jackknife_se` (neural, behavior), and
`descriptive_ranking` (`same_direction`, `opposite_direction`, or `tie` by the
product of the two signed differences). For jackknife, delete each concept once,
including all triplets containing it, keep temperatures fixed, recompute both
contrasts, and take `sqrt((n-1)/n * sum((delete_one-mean(delete_one))**2))`.
RDM pairs/triplets are not independent resampling units. This SE is descriptive.

Arrays: `concept_ids.npy`, `triplet_nll.npy` (candidate × retained trial),
`neural_rsa.npy` (candidate × subject × partition).
Conclusion: `confirmation_ranking` is the confirmation descriptive ranking;
`ranking_equivalence_established`, `population_dissociation_established`,
`same_person_correlation_tested`, `image_level_feature_matching` are false;
`scope` is `fixed_concept_label_representations_observed_cohorts`.

## D: temporal correspondence

This profile uses **THINGS-EEG2**, not MEG: original subjects 01 and 02, 200 test
images, 80 repeats, 17 posterior channels, and the complete released 100 Hz axis
starting at -200 ms. The owner averages repeats. Author preprocessing includes
-200..0 ms baseline correction and within-session multivariate noise normalization
whose covariance used both original train/test partitions. This is conditional
analysis of released derivatives, not a reprocessing of raw recordings. Candidate
concept-label representations are as in C; no layer is treated as a time point.

Inputs: `eeg.npy` (subject × concept × channel × time), `times_ms.npy`,
`features.npy` (candidate × concept × feature). Split sorted concept IDs 50/50
using seed 41 as above. Use only metadata's discovery subjects for discovery
concepts and only its disjoint confirmation subjects for confirmation concepts
(in this packet subject 01 and 02 respectively). Do not select the window from
confirmation responses. This public-data analysis is not a prospective trial.

At every time point compute correlation-distance neural RDMs across channels,
and cosine-distance model RDMs; use upper-triangle Spearman RSA, averaging subjects
equally within the specified partition. Report the full axis including baseline.
Among 50 ms windows starting at 0,50,100,150,200,250,300 ms, choose the largest
signed discovery first-candidate minus second-candidate mean, earliest tie.
Windows are `[start,end)`. Carry this window unchanged to confirmation.

Use 499 seed-73 permutations of confirmation stimulus labels, with one common
permutation applied to all candidates, subjects, and times. For each permutation
retain the maximum absolute RSA across **all candidates and all times**, and the
signed difference averaged in the frozen window. Corrected per-time p values use
`(1+count(null_max>=abs(observed)))/500`; the selected-window label-null p value
uses the absolute contrast and the same +1 correction. This tests correspondence
under stimulus relabeling, **not equality of population model performance**.

Arrays: `times_ms.npy`, `concept_ids.npy`, `discovery_rsa.npy`,
`confirmation_rsa.npy`, `confirmation_max_stat_p.npy` (all candidate × time),
`null_max_abs_rsa.npy` and `null_window_contrast.npy` (499 values).
Summary: `candidates`, `candidate_pair`, `selected_window_ms`,
`discovery_window_differences` (seven windows), `confirmation_window_difference`,
`selected_window_label_permutation_p`, `permutations`,
`time_axis: {first_ms,last_ms,samples}`, verbatim metadata `confirmation_scope`,
`corrected_p_family: "all candidates and all released times"`, and
`null_hypothesis: "no correspondence under common stimulus relabeling; not equality of population model performance"`.

Conclusion: `selected_window_label_null_rejected` is p≤0.05;
`precise_effect_onset_established`, `layer_depth_is_brain_latency`,
`same_dynamic_mechanism_established`, `population_model_superiority_tested`,
`new_prospective_confirmation` are false;
`scope` is `observed_disjoint_subject_and_concept_partitions`.

## E: learning, transfer and interference

Inputs are real processed Holton human trials and two explicitly derived linear
12→50→4 network baselines, with 1 or 100 repetitions per phase. Select the first
three lexicographic participant IDs per study × mapping condition, exclude entire
participants with nonfinite required responses, and record exclusions. These are
a bounded convenience subset, not a new representative population sample.

The network uses one-hot source stimulus IDs, no biases/nonlinearity, independent
normal weights SD .001, SGD step .1 on MSE of the two probed sine/cosine coordinates,
and deterministic per-participant seed `2024 + int(SHA256(id)[:8],16)`. It predicts
before each update, updates only when real noisy feedback is present, preserves
weights across A1→B→A2, and repeats each phase's exact sequence. This is **not an
exact reproduction** of the author's simulations (including different feedback
targets and learning rate). Source targets/observed human answers do not train it.

`targets.npy`, `human_responses.npy` are participant × phase × feature-1 trial,
in radians. Include no-feedback feature-1 responses in the analysis, particularly
A2: feedback availability controls updates, not whether a response can be measured.
`model_0_responses.npy` and `model_1_responses.npy` have 1×/100× as many trials.
`stimulus.npy`, `probe.npy`, `feedback.npy`, `feedback_present.npy` preserve all
120 source events per phase, including feature 0, for the experience audit.
Absent feedback values are stored as zero with mask false. Metadata declares all
model repetitions, state preservation, feedback rules, IDs, conditions and phases.

Wrap errors to [-π,π), take absolute value and convert to degrees. For declared W,
compute six metrics per participant/system in this order: initial A1 minus initial
B error (descriptive initial-phase difference), initial B minus final A1 (switch
cost), initial A2 minus final A1 (interference), and initial minus final error for
each of A1/B/A2. Initial/final means use first/last W feature-1 responses. Windows
may overlap; do not treat them as independent samples. Model phase targets repeat
the original target sequence. Divide each system's full phase into ten consecutive
`numpy.array_split` bins and average errors; bins represent relative progress,
not equal numbers of learning experiences across systems.

Summary: `systems` (human then models), `window`, `participants`, `metrics` with
names `initial_phase_difference,switch_cost,interference,learning_A1,learning_B,learning_A2`,
`groups`, `exposure`. Each sorted mapping-condition group includes `participants`,
`means` (system × 6), `model_minus_human` (model × 6), and
`paired_participant_percentile_intervals` (model × 6 × [low,high]). Starting with
seed 73, draw 1,000 paired participant samples with replacement within each sorted
condition, reusing draws across systems/metrics; report 2.5/97.5 percentiles.
`exposure` maps model ID to `phase_repetitions`,
`feedback_updates_per_participant_phase`, `exposure_matched`, `state_preserved`,
`feedback_only_updates`. Matching here means equal source event/feedback counts,
not identical subjective experience or identical learning rules.

Arrays: `participant_ids.npy`, `metrics.npy` (system × participant × 6),
`curves.npy` (system × participant × phase × 10).
Conclusion: `exposure_matched` maps model IDs to their audit result;
`same_brain_mechanism_established` and `consolidation_tested` are false;
`scope` is `observed_paired_participants_and_derived_linear_baselines`;
`intervals` is `descriptive_paired_participant_bootstrap_no_population_claim`.

## F: constrained offline stimulus selection

The owner uses Tuckute's LH language network, author session-wise voxel z-scores
then ROI averages. Training subjects have only baseline sentences; candidate
sentences use the largest common held-out subject coverage group (ties: pool size,
then subject IDs). Training sentences lacking any training-subject response are
excluded explicitly. Training and candidate identities/texts and subjects are
disjoint. Candidate responses, author predictions, condition labels, and response-
derived metadata are absent from the public packet. Opaque candidate IDs are sorted
to remove author condition ordering. Data are public, so memorization/contamination
remains possible; this is an offline selection study, not new human acquisition.

Inputs: `train_features.npy`, `train_responses.npy` (sentence × training subject),
`candidate_features.npy`. Frozen features are local distilgpt2 final-token,
final-normalized representations of each sentence independently. Metadata gives
texts, opaque IDs, length bins and `quota_per_group`. Select exactly 10 unique drive
and 10 unique suppress IDs, no overlap, meeting every per-group bin quota. Word bins
are [0,10),[10,15),[15,20),[20,∞). Quotas are allocated round-robin by smallest
current quota then bin number, limited by floor(bin pool size/2). Fitting and
selection methods are open; sets need not match a reference predictor.

Summary beyond common fields is exactly `selection: {drive:[IDs],suppress:[IDs]}`.
Arrays: `candidate_ids.npy` (every candidate exactly once) and `predictions.npy`
(one finite float64 predicted response per candidate in that ID order). Predictions
and selection must reproduce; the grader does not require top/bottom sorting.
Conclusion: `new_human_experiment_performed` and `hidden_responses_used` false,
`public_label_contamination_possible` true,
`scope: "offline_candidate_pool_observed_heldout_subjects"`.

Before revealing any hidden effect, the owner persists a choice/prediction/plan/
source/hidden-version fingerprint in a ledger **assigned to the Agent identity**.
Identical retries are permitted; changed submissions against that packet are
rejected. The operator must reuse that ledger across all runs for the same Agent,
keep it outside Agent access, and not offer fresh ledgers for repeated querying.
Always supply the frozen saved results as well as source for replay.

Primary `selection_effect` is each hidden subject's mean drive response minus mean
suppress response, averaged equally across subjects. Also report `selection_valid`,
per-subject effects, a fixed ridge predictor baseline, and 1,000 matched-budget
random selections (seed 73, random disjoint choices within each bin). Fixed ridge
uses training mean/SD and intercept as in A, alpha=100, training-subject mean as Y,
then smallest/largest predictions within each bin (ties: opaque ID). Random
percentiles are a reference distribution, not a population significance test.
Invalid decisions emit **no effect score** (not a misleading zero on this signed
scale). Infrastructure failure is distinct from invalid submission.
