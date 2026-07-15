# bciciv-2a — grader notes

## Why publishing `evaluate_external.py` is safe

The grader runs **offline**, against **agent-invisible** held-out payloads.
Even with the source in front of them, an agent cannot cheat because:

1. **Session-E labels never enter the workspace.** Evaluator setup writes
   `A0xE.mat` classlabel arrays into the explicitly configured
   `$BPB_BCI2A_PRIVATE_EVAL_DIR/true_labels/`, which must live **outside**
   the workspace root. The evaluator (running as the scorer, not the
   agent) reads them; the agent process has no file-system path to them.
2. **Session-E GDF files handed to the child process come from a
   scorer-side mount / bind path**, not from the workspace. The child
   process `train_and_infer.py` is only pointed at those paths via
   `--train-gdf` / `--test-gdf`; whatever the agent wrote into its own
   workspace `public_data/` (if anything) is ignored.
3. **The score is computed against labels the agent never had.**
   Overfitting to a leaked signal is the only cheat, and there is no
   such signal.

## Contract

```
run_dir/
  artifacts/
    EEG_MI/mi_agent_model.py       ← agent-submitted, torch nn.Module
    (report.md, other artifacts kept but not read by the scorer)
```

`checks/check.sh` (cwd = `run_dir`) locates the private eval dir in this
order:

1. `BPB_BCI2A_PRIVATE_EVAL_DIR` env var (set by the evaluator or CI).
2. `<run_dir>/private_eval/` (used **only** by the Oracle gate —
   `solution.sh` fabricates a dummy dataset there so the pipeline can
   be exercised in the 120 s validate sandbox).

If a `.bpb_oracle_mode` sentinel file exists in `run_dir`, the evaluator
skips GPU training entirely and emits chance-level scores. This is how the
Oracle gate walks the pipeline within its 120 s time budget.

Otherwise it calls `evaluate_external.py $PWD`, which:

- Locates the private dir (`$BPB_BCI2A_PRIVATE_EVAL_DIR` or fallback).
- Loads `manifests/subjects.json` for the fixed 230/58 stratified
  train/val split indices (seed=42) — the same indices the agent's
  `get_subject_data.py` returns.
- **For each of the 9 subjects**, launches a fresh isolated child
  process (`train_and_infer.py`) that:
  - Imports the submitted `MIAgentModel` from a scorer-controlled copy
    of `mi_agent_model.py` in a sandbox temp dir.
  - Loads that subject's session-T GDF, does the frozen preprocessing
    (22 EEG channels, 4-38 Hz bandpass, resample to 128 Hz, 4-second
    epochs starting at each 768 cue) → `(288, 22, 512)` features plus
    labels extracted from GDF annotations 769-772 (mapped to 1..4).
  - Splits by the manifest indices, trains with Adam lr=1e-3, batch 64,
    up to 100 epochs, early-stops on val loss with patience 20.
  - Loads that subject's session-E GDF, predicts on the 288 held-out
    trials, writes `sample_id,predicted_label` CSV back to the parent.
- Reads back predictions, loads the private `A0xE.mat` `classlabel`
  vector, computes per-subject accuracy + Cohen's kappa + macro F1,
  aggregates the means, and emits one flat JSON payload between
  `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES` sentinels.

## Isolation

- `BPB_SUBMISSION_ISOLATION=process` (default local): the child runs as
  `python3 -I --isolated` in a fresh cwd, with an empty HOME, no HF
  tokens, no `BPB_BCI2A_PRIVATE_EVAL_DIR` in env (so the agent's model
  code cannot look up the private path), and a 25 min per-subject
  timeout. The child does inherit the parent's PATH — that is how a
  system `python3` finds torch/mne.
- `BPB_SUBMISSION_ISOLATION=docker` (required for official scoring): the
  child runs in a no-network, non-root, read-only container mounted
  with the runner + submitted model + GDF files as read-only, and only
  the predictions dir as writable. `--gpus all` gives access to GPUs.
  Requires `BPB_INFERENCE_IMAGE=<image>@sha256:<digest>` under
  `BPB_OFFICIAL_SCORING=1`.

## Failure semantics

Missing artifacts, missing private data, bad forward shape, non-finite
predictions, or a child crash all cause the scorer to print a diagnostic
to stderr and **exit 0 without emitting the sentinel**. The BPB
`exec-script` scorer then reports a structured `private_data_missing` /
`private_access_denied` / `scoring_failed` state (never zero) — the
leaderboard coverage convention is preserved.

## Metric set

22 keys, aligned with `categories.yaml eeg-motor-imagery`:

- `score` — primary column, `mean_kappa` clipped to `[0,1]`.
- `mean_accuracy`, `mean_kappa`, `mean_macro_f1` — aggregate summaries.
- `subject_1_acc` … `subject_9_acc` — per-subject session-E accuracy.
- `subject_1_kappa` … `subject_9_kappa` — per-subject Cohen's kappa,
  may be negative.

## Oracle numbers are meaningless

`solution/solution.sh` synthesizes a minimal `MIAgentModel` and
`.bpb_oracle_mode` sentinel; the Oracle run's `score` is fixed at
`0.0` (chance-level kappa = 0). This is **only** to verify the scorer
pipeline; it says nothing about the real task difficulty.

## Local end-to-end sanity check

```bash
export XDG_CACHE_HOME=~/.cache
bp-bench fetch bciciv-2a --private
export BPB_BCI2A_PRIVATE_EVAL_DIR=/absolute/evaluator-only/path
bash <bpb-repo>/tasks/bciciv-2a/env/setup.sh --role evaluator
mkdir -p /tmp/bpb-bci2a-run/artifacts/EEG_MI
cd /tmp/bpb-bci2a-run
# ... put a real mi_agent_model.py into artifacts/EEG_MI/ ...
bash <bpb-repo>/tasks/bciciv-2a/checks/check.sh
```
