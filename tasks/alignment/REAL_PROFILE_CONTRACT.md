# Real Task2 server draft

Task ID `alignment-pereira2018-profile`, version `0.1-server-draft`.
Protocol `pereira-subject-material-descriptive-v1`, answer schema
`bpb-profile-answers/2`. This is a **derived, unaccepted real-data analysis**,
not the original full-data Brain-Score total or a significance/OOD test.

The operator reserves confirmation story groups before fitting. Development
scores use inner grouped-CV predictions: concatenate out-of-fold predictions,
compute Pearson per neuroid over all development stimuli, then take the median
within each subject. Confirmation uses a readout fitted only on development data
(including training-only alpha selection) and scores held-out materials. Both
roles use the same subjects. The group profile equally averages subject scores.
This aggregation differs from the official pooled-neuroid, per-fold aggregate.
No per-sentence or short-passage correlation is averaged into these scores.

Read PROFILE_CONTEXT.json and use `describe`, `profile`, `compare`, `stability`,
`commit_selection`, and `generalization`. Only the operator may access the full
packet and journal. The six tools and run-ID evidence convention are shared with
the fixture, but the server requires explicit `--allow-real`.

Submit answers.json with exactly `schema`, `protocol_id`, `packet_sha256` and
`questions` containing q1...q4. Each question has `answer` and a nonempty `evidence`
list of actual service run IDs. Also submit a nonempty report.md. The generated
answers.schema.json describes the envelope and detailed Q3/Q4 fields.

- Q1: `dataset_id`, `layer_means`, `highest_layers`, `near_top_layers`, `range`,
  `shape`. Use development; highest ties tolerate 1e-12. Near-top means within
  the packet's margin + 1e-12 of the maximum. Shape is flat if range <= margin;
  otherwise single_peak for one near-top layer, plateau for contiguous multiple
  near-top layers in declared order, or multiple_high_regions. Cite `profile`.
- Q2: `dataset_id`, `compared_layer`, `baseline_layer`, `mean_difference`,
  `subject_differences`, `evidence_state`, `claim_strength=descriptive_only`.
  Compare the first declared development maximum with the final layer. Consistent
  advantage means every subject difference > margin; mixed means both a difference
  < -margin and one > margin; otherwise no_consistent_advantage. Cite `compare`.
- Q3: `dataset_id`, `compared_layer`, `subject_highest_layers`, `subject_near_top`,
  `subject_gap_to_best`, `subject_agreement`, `leave_one_subject_out`,
  `representativeness`, `influential_subjects`, `leave_one_out_sensitive`, `scope`.
  Use the Q2 layer. Each omission maps to highest_layers, near_top_layers and
  selected_layer_gap_to_best after re-averaging the remaining subjects. Flag
  influential subjects only when that gap exceeds margin + 1e-12. Representative
  means near-top in >=75% of observed subjects; labels are broadly_representative
  or heterogeneous. Scope is exactly [observed_subjects]. This does not establish
  unseen-subject generalization or exclude joint influence by several people.
  Cite `stability`.
- Q4: freeze a layer before `generalization`. Report `status`, `selected_layer`,
  `baseline_layer`, `source_dataset_id`, `target_dataset_id`, `declared_shift`,
  `source_difference`, `target_score`, `target_baseline_score`, `target_difference`,
  `difference_change`, `target_gap_to_best`, `advantage_conclusion`, `near_optimality`,
  `scope`. Difference is selected minus baseline; change is confirmation minus
  development difference. With development difference <= margin + 1e-12, label
  no_development_advantage. Otherwise label advantage_retained when confirmation
  difference > margin + 1e-12, advantage_reversed when < -margin - 1e-12, or
  advantage_not_retained. Independently label retained_near_optimal when the gap
  to the confirmation observed maximum <= margin + 1e-12, otherwise not_retained.
  Scope is same_subjects_new_material and shift is new_material. Cite generalization.

The real server draft currently requires confirmation data; the synthetic fixture
still supports explicit not_evaluated cases. The 0.02 default margin and 75%
agreement cutoff are engineering rules, not scientifically calibrated criteria.
Correct structured analysis can score fully even when alignment is low or an
advantage reverses. Passing this draft scorer does not certify free prose or
scientific acceptance. Hash-chain replay checks consistency, not authorship;
the operator must enforce filesystem/process separation in a real Agent run.
