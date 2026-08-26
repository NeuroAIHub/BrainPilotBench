# tops-fmri — grader notes

## Why publishing `evaluate_external.py` is safe

The grader runs **offline**, against **agent-invisible** held-out payloads.
Even with the source in front of them, an agent cannot cheat because:

1. **Labels never enter the workspace.** Evaluator setup writes
   `study4_labels.npz` / `study5_labels.npz` to the explicitly configured
   `$BPB_TOPS_PRIVATE_EVAL_DIR`, which must live **outside** the workspace root.
   The evaluator (running as the scorer, not the agent) reads them; the
   agent process has no file-system path to them.
2. **The features handed to the agent script come from a scorer-side temp
   dir**, not from the workspace. The agent's `apply_signature.py` is
   invoked with `--eval-features-dir <tmp>`; whatever the agent wrote into
   its workspace `features/` (if anything) is ignored.
3. **The score is computed against labels the agent never had.** Overfitting
   to a leaked signal is the only cheat, and there is no such signal.

## Contract

```
run_dir/
  artifacts/
    scripts/apply_signature.py       ← agent-submitted, numpy-only
    models/study3_signature_weights.npz
    models/signature_manifest.json
```

`checks/check.sh` (cwd = `run_dir`) locates the private dir in this order:

1. `BPB_TOPS_PRIVATE_EVAL_DIR` env var (set by the evaluator or CI).
2. `<run_dir>/private_eval/` (used **only** by the Oracle gate — `solution.sh`
   fabricates a dummy 3-sample dataset there so the pipeline can be
   exercised in the 120 s validate sandbox).
Then it calls `evaluate_external.py $PWD`, which:

- copies `features/*.npz` into a private tmp dir,
- copies the submitted inference script and models into a separate temporary
  execution root,
- runs the agent script with Python isolated mode in a non-root, no-network
  container with read-only code/models/features, no evaluator
  path/token/proxy variables, and a 120 s hard timeout,
- reads back the two prediction CSVs,
- loads private labels,
- computes 4 Pearson r + 2 raw AUC values, chance-centers the AUC subscores,
  and aggregates a 0-1 score, and
- emits a flat JSON payload between `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES`.

The BPB `exec-script` scorer captures that payload. Missing artifacts, bad
CSVs, non-finite responses, or an agent script that crashes all cause the
scorer to report a structured <code>private_data_missing</code> or
<code>scoring_failed</code> state (never zero) — the leaderboard coverage
convention is preserved.

Local development may explicitly use the legacy process mode. Official
evaluation requires `BPB_SUBMISSION_ISOLATION=docker` and an immutable
`BPB_INFERENCE_IMAGE`; it fails closed when either is unavailable.

## Metric set

The nine keys are the `fmri-analysis` category metric set in
`categories.yaml`. `score` is the primary leaderboard column; `study4_score`
is the mean positive Pearson r and `study5_score` is the mean of
`max(0, 2·AUC−1)`, aligning both subgroup chance baselines at zero. The last
six raw r / AUC keys are unchanged diagnostics.

This formula change defines task v0.2. Do not compare its headline score
directly with v0.1, which aggregated raw AUC. Historical raw diagnostic values
remain interpretable. `test_metrics.py` freezes the v0.2 re-aggregation of the
preserved reference raw metrics so the new formula baseline cannot drift.

## Oracle numbers are meaningless

`solution/solution.sh` synthesizes a **zero-weight** signature and three-row
label vectors. Constant responses produce zero Pearson r and chance AUC 0.5;
after chance alignment the Oracle headline `score` is 0. This is **only** to
verify the scorer pipeline; it says nothing about the real task difficulty.

## Local end-to-end sanity check

```bash
export XDG_CACHE_HOME=~/.cache
bp-bench fetch tops-fmri --private
export BPB_TOPS_PRIVATE_EVAL_DIR=/absolute/evaluator-only/path
bash <bpb-repo>/tasks/tops-fmri/env/setup.sh --role evaluator
mkdir -p /tmp/bpb-tops-run/artifacts
cd /tmp/bpb-tops-run
# ... put a real apply_signature.py + models/ into ./artifacts/ ...
bash <bpb-repo>/tasks/tops-fmri/checks/check.sh
```
