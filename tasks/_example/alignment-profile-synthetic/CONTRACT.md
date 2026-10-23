# Four-question answer contract

This contract covers **synthetic engineering fixtures only**. The analysis is
descriptive. Margin 0.02 and membership cutoff 0.75 are public fixture rules,
not calibrated neuroscience effect thresholds, confidence levels, or tests of
significance/equivalence. Layer scores are not independent observations.

Submit `answers.json` and nonempty `report.md`. JSON envelope:

```json
{
  "schema": "bpb-profile-answers/2",
  "protocol_id": "synthetic-profile-descriptive-v2",
  "packet_sha256": "<hash returned by the operator service>",
  "questions": {
    "q1": {"answer": {}, "evidence": ["run-0002"]},
    "q2": {"answer": {}, "evidence": ["run-0003"]},
    "q3": {"answer": {}, "evidence": ["run-0004"]},
    "q4": {"answer": {}, "evidence": ["run-0006"]}
  }
}
```

The example evidence IDs are placeholders; cite IDs from the actual session.
No question may be omitted. An explicit `not_evaluated` is appropriate for Q4
only when the operator packet has no confirmation data. Free report wording is
not exact-matched. Free prose is retained for human review and **not verified by
the current scorer**; passing structured answers does not certify arbitrary text.

## Q1: 整体形态是什么？

Fields: `dataset_id`, `layer_means` (layer → numeric mean), `highest_layers`,
`near_top_layers`, `range`, `shape`.

Use the declared development dataset. Average blocks within each subject, then
average subjects equally. `highest_layers` includes exact ties to 1e-12;
`near_top_layers` includes all layers within the packet margin of the maximum.
The declared layer list gives layer order, never lexicographic sorting.
Shape classes and rules are in `protocol.json`. An isolated high layer is not OOD.
Evidence must include a `profile` call for the development dataset.

## Q2: 差异有多大，证据有多强？

Fields: `dataset_id`, `compared_layer`, `baseline_layer`, `mean_difference`,
`subject_differences` (subject → paired difference), `evidence_state`,
`claim_strength`.

Compare the development maximum (ties resolved by declared layer order) with the
predeclared baseline, which must be the final layer in the declared order.
Differences are paired within subject; preserve their signs.
`evidence_state` is one of `consistent_advantage`, `mixed`,
`no_consistent_advantage` using the fixture rules. `claim_strength` must be
`descriptive_only`. A failure to meet the rule is not proof of equivalence or
absence of an effect. No confidence interval or p-value is computed in this phase.
Evidence must include `compare` with the matching ordered pair of layer IDs.

## Q3: 群体选层是否代表各受试者？

Fields: `dataset_id`, `compared_layer`, `subject_highest_layers`,
`subject_near_top`, `subject_gap_to_best`, `subject_agreement`,
`leave_one_subject_out`, `representativeness`, `influential_subjects`,
`leave_one_out_sensitive`, `scope`.

The compared layer is the development group maximum, resolving ties by declared
layer order. For every subject, average that subject's stimulus blocks and report
their highest layers, near-top layers, and the gap between their highest score
and their score for the group-selected layer. These are maps keyed by subject ID.
Do not assume small subject differences or require identical exact winners.

`subject_agreement` is the fraction of observed subjects whose near-top set
includes the group-selected layer. `representativeness` is
`broadly_representative` iff this fraction is at least 0.75, else `heterogeneous`.
This is a fixture threshold, not a population-level inference.

For each subject, omit that subject and re-average the remaining subjects equally
using the same cached scores. No model is refitted. `leave_one_subject_out` maps
the omitted subject ID to `highest_layers`, `near_top_layers`, and
`selected_layer_gap_to_best` (the gap for the original group-selected layer).
`influential_subjects` contains omissions whose gap exceeds margin + 1e-12;
`leave_one_out_sensitive` is true iff that list is nonempty. An exact winner
flip within a plateau does not suffice. A false value only means no single
removal triggered the rule; it does not rule out joint influence by several people.

`scope` is exactly `["observed_subjects"]`. These overlapping removals describe
selection sensitivity within the observed sample, not generalization to unseen
subjects or independent replications. No independent sample size is inferred.
Evidence must cite `stability` for the development maximum.

## Q4: 选层结论能否在未参与选择的新材料上复现？

Before viewing confirmation results, call `commit_selection(layer)`. This fixes
one layer for the session. Repeating the same selection is allowed; changing it
after commitment is rejected, including after server restart with `--resume`.

Fields: `status`, `selected_layer`, `baseline_layer`, `source_dataset_id`,
`target_dataset_id`, `declared_shift`, `source_difference`, `target_score`,
`target_baseline_score`, `target_difference`, `difference_change`,
`target_gap_to_best`, `advantage_conclusion`, `near_optimality`, `scope`.

Confirmation must use the same subject identities, model layers and synthetic
measurement protocol, with disjoint stimulus-block IDs. The validator rejects
changed subject cohorts, overlapping materials, and undeclared material changes.
This is a declared synthetic design, not proof of independence for real data.

`source_difference` is the frozen layer's development mean minus the baseline
mean. `target_difference` is its confirmation mean minus the confirmation baseline
mean; `difference_change = target_difference - source_difference`.
`target_gap_to_best` uses the confirmation **observed** maximum across layers.
All computations use the frozen layer, which need not equal Q2/Q3's development
maximum if the Agent deliberately selects another layer.

Apply the following ordered descriptive rules to `advantage_conclusion`:

| Condition | Label |
|---|---|
| No confirmation data | `not_evaluated` |
| Development difference <= margin + 1e-12 | `no_development_advantage` |
| Otherwise, confirmation difference > margin + 1e-12 | `advantage_retained` |
| Otherwise, confirmation difference < -margin - 1e-12 | `advantage_reversed` |
| Otherwise | `advantage_not_retained` |

Retention does not mean the effect size stayed unchanged; report the numerical
change as well. Failure to meet the threshold does not establish equivalence.
Separately, `near_optimality` is `retained_near_optimal` iff the confirmation gap
is <= margin + 1e-12, otherwise `not_retained`. A layer can remain better than the
baseline yet cease to be near-best, or be near-best with no baseline advantage.

With confirmation, `status=evaluated`, `declared_shift=new_material` and
`scope=same_subjects_new_material`. Without it, status, both conclusions and scope
are `not_evaluated`, shift is `none`, target dataset ID and all five confirmation
measurements are null. The development difference remains a measured number.
Evidence must cite `generalization`, which is callable only after commitment.
This describes replication on the declared materials, not OOD, unseen-subject
generalization or transfer of the same fitted brain readout. A no-confirmation
case tests recognition of missing evidence, not replication performance.

For a future real backend, retain full passage/story grouping and freeze the
selection and scoring protocol before opening confirmation results. Confirmation
test responses must not enter readout fitting or hyperparameter selection. If a
new readout is fitted on separate confirmation-training data, disclose that the
transferred object is the layer choice. No such fitting occurs in this scaffold.

## Version binding

Task version 0.2 uses profile `synthetic-profile-descriptive-v2` and answer schema
`bpb-profile-answers/2`. Earlier packets, answers and task metadata must not be
reused. Prepare rejects an existing workspace context with an incompatible
profile; use a fresh workspace and operator session. Packet field layout and
journal format remain at version 1, bound to the new profile and packet hash.

## Grading and evidence

The operator passes a separate evidence directory containing `packet.json` and
the server's `journal.jsonl`. The grader never takes an evidence path from answers.
It validates the hash chain, recomputes every tool result and commitment sequence,
then independently checks four structured answers and their cited tool/arguments.
Numerical tolerance is atol 1e-9, rtol 1e-7. Set-valued lists may be reordered.

`profile_analysis_success=1` iff all four pass. `four_question_score` is the fraction
passing; a wrong interpretation is a scored failure. Missing required artifacts or
questions is `submission_invalid`. Missing/corrupted operator evidence is
`scoring_failed`, not Agent zero. A valid empty operator journal represents no
recorded work and leads to a scored failure, not an infrastructure exemption.

The journal hash chain detects inconsistency; it does not authenticate an
operator. Production use must isolate the authoritative packet/journal from the
Agent and bind it to the task run. Current same-user local tests do not prove that
filesystem boundary. The grader executes no submitted code.
