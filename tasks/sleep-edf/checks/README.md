# sleep-edf — grader notes

## Why publishing `evaluate_external.py` is safe

The grader runs **offline**, against **agent-invisible** held-out payloads.
Even with the source in front of them, an agent cannot cheat because:

1. **Subject 16-19 hypnograms never enter the workspace.** Evaluator setup
   writes those recordings under `$BPB_SLEEP_EDF_PRIVATE_EVAL_DIR/test_edf/`,
   which must live **outside** the workspace root. The evaluator (running
   as the scorer, not the agent) reads them; the agent process has no
   file-system path to them.
2. **The training + inference child process receives its EDF paths via
   `--train-edf-root` / `--test-edf-root` from a scorer-controlled mount /
   bind path**, not from the workspace. Whatever the agent wrote into its
   own workspace `public_data/` (if anything) is ignored by the scorer.
3. **The score is computed against hypnogram labels the agent never had.**
   The agent's `public_data/` only ships subjects 0-15; overfitting to a
   leaked signal is the only cheat, and there is no such signal.

## Contract

```
run_dir/
  artifacts/
    EEG_sleep/sleep_agent_model.py     ← agent-submitted, torch nn.Module
    (report.md, other artifacts kept but not read by the scorer)
```

`checks/check.sh` (cwd = `run_dir`) locates the private eval dir in this
order:

1. `BPB_SLEEP_EDF_PRIVATE_EVAL_DIR` env var (set by the evaluator or CI).
2. `<run_dir>/private_eval/` (used **only** by the Oracle gate —
   `solution.sh` fabricates a dummy dataset there so the pipeline can
   be exercised in the 120 s validate sandbox).

If a `.bpb_oracle_mode` sentinel file exists in `run_dir`, the evaluator
skips GPU training entirely and emits chance-level scores. This is how the
Oracle gate walks the pipeline within its 120 s time budget.

Otherwise it calls `evaluate_external.py $PWD`, which:

- Locates the private dir (`$BPB_SLEEP_EDF_PRIVATE_EVAL_DIR` or fallback).
- Loads `manifests/subjects.json` for subject → filename mapping.
- Launches a single isolated child process (`train_and_infer.py`) with a
  150 min budget. The child:
  - Imports the submitted `SleepAgentModel` from a scorer-controlled copy
    of `sleep_agent_model.py` in a sandbox temp dir.
  - Loads all recordings for subjects 0-13 (train), 14-15 (val), and
    16-19 (test), applying the frozen preprocessing (pick `EEG Fpz-Cz`,
    0.3-35 Hz bandpass, resample to 100 Hz, head/tail Wake crop to
    30 min each, 30 s non-overlapping epoching, `Sleep stage 3` and
    `Sleep stage 4` merged into label 3, `Movement time` / `Sleep stage ?`
    dropped).
  - Trains a fresh `SleepAgentModel()` with Adam lr=1e-3, batch 64,
    class-weighted CrossEntropyLoss (inverse-frequency weights over
    the train pool), up to 20 epochs, early-stops on val loss with
    patience 5.
  - Predicts every 30 s epoch for each subject 16-19 in the same
    recording / epoch order that the scorer reproduces when loading
    the true labels — writes CSV rows `subject_id,epoch_id,predicted_label`.
- Reads back predictions, re-loads the private hypnogram labels using
  the same load pipeline (ensuring `N` and epoch order match exactly),
  concatenates across subjects, computes accuracy / balanced accuracy /
  macro F1 / Cohen's kappa / per-class recall, and emits 10 keys
  between `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES` sentinels.

## Isolation

- `BPB_SUBMISSION_ISOLATION=process` (default local): the child runs as
  `python3 -I --isolated` in a fresh cwd, with an empty HOME, no HF
  tokens, no `BPB_SLEEP_EDF_PRIVATE_EVAL_DIR` in env, and a 150 min
  timeout. The child does inherit the parent's PATH — that is how a
  system `python3` finds torch/mne.
- `BPB_SUBMISSION_ISOLATION=docker` (required for official scoring): the
  child runs in a no-network, non-root, read-only container mounted
  with the runner + submitted model + EDF files as read-only, and only
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

10 keys, aligned with `categories.yaml eeg-sleep-staging`:

- `score` — primary column, `test_kappa` clipped to `[0,1]`.
- `test_kappa` — Cohen's kappa on the concatenated subject-16..19
  predictions; may be negative for very bad classifiers.
- `test_accuracy`, `test_balanced_accuracy`, `test_macro_f1` — aggregate
  summaries.
- `wake_recall`, `n1_recall`, `n2_recall`, `n3_recall`, `rem_recall` —
  per-class recall. N1 is typically the hardest class.

## Oracle numbers are meaningless

`solution/solution.sh` synthesizes a minimal `SleepAgentModel` and
`.bpb_oracle_mode` sentinel; the Oracle run's `score` is fixed at
`0.0` (chance-level kappa = 0). This is **only** to verify the scorer
pipeline; it says nothing about the real task difficulty.

## Local end-to-end sanity check

```bash
export XDG_CACHE_HOME=~/.cache
bp-bench fetch sleep-edf --private
export BPB_SLEEP_EDF_PRIVATE_EVAL_DIR=/absolute/evaluator-only/path
bash <bpb-repo>/tasks/sleep-edf/env/setup.sh --role evaluator
mkdir -p /tmp/bpb-sleep-run/artifacts/EEG_sleep
cd /tmp/bpb-sleep-run
# ... put a real sleep_agent_model.py into artifacts/EEG_sleep/ ...
bash <bpb-repo>/tasks/sleep-edf/checks/check.sh
```
