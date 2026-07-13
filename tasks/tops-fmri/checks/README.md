# tops-fmri — grader notes

## Why publishing `evaluate_external.py` is safe

The grader runs **offline**, against **agent-invisible** held-out payloads.
Even with the source in front of them, an agent cannot cheat because:

1. **Labels never enter the workspace.** `env/setup.sh` writes
   `study4_labels.npz` / `study5_labels.npz` to
   `$BPB_TOPS_PRIVATE_EVAL_DIR`, which lives **outside** the workspace root.
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

1. `BPB_TOPS_PRIVATE_EVAL_DIR` env var (set by `env/setup.sh` or CI).
2. `<run_dir>/private_eval/` (used **only** by the Oracle gate — `solution.sh`
   fabricates a dummy 3-sample dataset there so the pipeline can be
   exercised in the 120 s validate sandbox).
3. `../.tops-fmri.env` (a source-able env file left by setup.sh).

Then it calls `evaluate_external.py $PWD`, which:

- copies `features/*.npz` into a private tmp dir,
- runs the agent script with a 120 s hard timeout,
- reads back the two prediction CSVs,
- loads private labels,
- computes 4 Pearson r + 2 AUC + aggregate 0-1 score, and
- emits a flat JSON payload between `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES`.

The BPB `exec-script` scorer captures that payload. Missing artifacts, bad
CSVs, non-finite responses, or an agent script that crashes all cause the
scorer to report **unscored** (never zero) — the leaderboard three-state
convention is preserved.

## Metric set

The nine keys are the `fmri-analysis` category metric set in
`categories.yaml`. `score` is the primary leaderboard column; `study4_score`
and `study5_score` are subgroup summaries; the last six raw r / AUC keys are
diagnostic (they can be negative for r, so are not clipped in the raw output).

## Oracle numbers are meaningless

`solution/solution.sh` synthesizes a **zero-weight** signature and three-row
label vectors; the Oracle run's `score` will be around 0.5 (chance-level AUC,
zero r → clipped to 0, averaged 0.5×0 + 0.5×0.5 ≈ 0.25 depending on which
condition ties). This is **only** to verify the scorer pipeline; it says
nothing about the real task difficulty.

## Local end-to-end sanity check

```bash
export XDG_CACHE_HOME=~/.cache
bp-bench fetch tops-fmri
mkdir -p /tmp/bpb-tops-run/artifacts
cd /tmp/bpb-tops-run
# ... put a real apply_signature.py + models/ into ./artifacts/ ...
bash <bpb-repo>/tasks/tops-fmri/checks/check.sh
```
