# Alignment expansion: executable experimental tasks A–F

All six tasks have executable experimental implementations staged outside the
canonical collection. A uses `incremental_cli.py`; B–F use `expansion_cli.py`.
Read [the Task A contract](INCREMENTAL_CONTRACT.md) before interpreting results.
Read the [B–F contract](EXPANSION_CONTRACT.md) for the remaining tasks.
See [expansion validation](EXPANSION_VALIDATION.md) for executed checks and limits.

## Environment

Use the existing Linux Python 3.11 server environment described in
[SERVER_RUNBOOK.md](SERVER_RUNBOOK.md). Task A preparation needs NumPy and xarray;
analysis/scoring need NumPy. Offline tests additionally use scikit-learn for an
independent numerical implementation. Task B uses the pinned Brain-Score and
Transformers environment and already downloaded local model weights.

Run from the repository root. Set paths for your deployment:

```bash
export BPB_ALIGNMENT_PYTHON=/path/to/python311/bin/python
export BPB_EXPANSION_ROOT=/data/bpb-alignment-expansion
export BPB_EXISTING_CACHE=/data/bpb-alignment/distilgpt2-cache
export BPB_INFERENCE_IMAGE=bpb-brainscore-server-draft
export OPENBLAS_NUM_THREADS=4
export OMP_NUM_THREADS=4
export BPB_ALIGNMENT_WORKER_CPUS=2
```

The image must be built locally with NumPy/SciPy available, NumPy matching the owner environment, and
`/opt/alignment/worker.py` installed. An existing server image works; the new
maintainer reference/grader package must not be copied into the Agent workspace
or image. The explicit reference-submission command below is only for testing.
There are no new model downloads for Task A or for the local-cache context pilot.

## Prepare and stage Task A

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/incremental_cli.py prepare \
  --cache "$BPB_EXISTING_CACHE" --output "$BPB_EXPANSION_ROOT/task-a-inputs"

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/incremental_cli.py stage \
  --inputs "$BPB_EXPANSION_ROOT/task-a-inputs" --output "$BPB_EXPANSION_ROOT/task-a"

node dist/cli.js validate alignment-incremental-explanation \
  --tasks "tasks,$BPB_EXPANSION_ROOT/task-a" --schema-only

node dist/cli.js run alignment-incremental-explanation \
  --tasks "tasks,$BPB_EXPANSION_ROOT/task-a" --adapter manual --agent YOUR_AGENT_ID \
  --workspace "$BPB_EXPANSION_ROOT/task-a-workspace" \
  --out "$BPB_EXPANSION_ROOT/runs" --run-id task-a-001
```

Use `tasks,<staged-root>` so CLI validation finds the repository's category
registry. The task's ID and evaluation profile distinguish it from Task1 even
though both use the existing `alignment-analysis` category.

The Agent workspace contains inputs, contract and the benchmark prompt, without
a solution. Configure the actual Agent's access separately: manual mode does not
launch or isolate an Agent. After it finishes, collect and grade:

```bash
node dist/cli.js run alignment-incremental-explanation \
  --tasks "tasks,$BPB_EXPANSION_ROOT/task-a" --adapter manual \
  --resume "$BPB_EXPANSION_ROOT/runs/task-a-001"

node dist/cli.js submit verify "$BPB_EXPANSION_ROOT/runs/task-a-001" \
  --tasks "tasks,$BPB_EXPANSION_ROOT/task-a"

node dist/cli.js score "$BPB_EXPANSION_ROOT/runs/task-a-001" \
  --tasks "tasks,$BPB_EXPANSION_ROOT/task-a" --isolation docker \
  --inference-image "$BPB_INFERENCE_IMAGE"
```

## Maintainer baseline and direct evaluation

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/incremental_cli.py reference-submission \
  --output "$BPB_EXPANSION_ROOT/reference-submission" --control-set word_count+position

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/incremental_cli.py reference \
  --inputs "$BPB_EXPANSION_ROOT/task-a-inputs" \
  --plan "$BPB_EXPANSION_ROOT/reference-submission/plan.json" \
  --output "$BPB_EXPANSION_ROOT/reference-results"

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/incremental_cli.py evaluate \
  --inputs "$BPB_EXPANSION_ROOT/task-a-inputs" \
  --submission "$BPB_EXPANSION_ROOT/reference-submission" \
  --saved-results "$BPB_EXPANSION_ROOT/reference-results" \
  --output "$BPB_EXPANSION_ROOT/grade" --image "$BPB_INFERENCE_IMAGE" --cpus 2
```

Use fresh directories; the tools refuse overwriting completed or interrupted
packets. The reference command writes into a fresh result directory. To run the
maintainer baseline through manual CLI collection, copy its submission and
generated artifacts into that manual workspace after the pending handoff. Label
the run `maintainer-reference-not-agent`; it is not an Agent evaluation.

The evaluator emits a `BPB_SCORES` marker only for a scored submission. It records
the pinned image ID, comparisons and worker limits in `<output>/grade.json`.
Infrastructure failure emits no success/zero metric. Process mode requires
`BPB_ALIGNMENT_TRUSTED_LOCAL=1`, is forbidden with `BPB_OFFICIAL_SCORING=1`, and is
only an offline maintainer test harness.

## Task B context pilot

Set `HF_HOME`, `XDG_CACHE_HOME` and `BRAINIO_HOME` to the existing server cache
locations. The pilot uses local files only; missing weights are an error.

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/context_pilot.py \
  --cache "$BPB_EXISTING_CACHE" --inputs "$BPB_EXPANSION_ROOT/task-a-inputs" \
  --output "$BPB_EXPANSION_ROOT/task-b-pilot" --device cpu
```

Sentence positions 3 and 4 provide 192 candidate targets from 96 four-sentence
passages. Each target is evaluated with its own sentence, a normal prior prefix,
and the same prior sentences in reverse order. Every condition preserves the
target and excludes future sentences; reversal has at least two prior sentences.
This manipulation changes the entire prior order, including which sentence is
most recent. It is not the proposed long-history control that preserves a recent
window. Token lengths and truncation checks are recorded. Only targets whose
normal/reversed prefixes have equal token counts are analyzed, using the same
retained subset for all three conditions (160 targets in the initial real cache).
This restriction uses input text/tokenization only. Excluded IDs are saved in
`analysis_selection.json`. Normal-prefix features
must reproduce the existing verified feature cache within tolerance.

The design is written before inference; final story splits and the token-matched
selection are written before readout fitting.
All three conditions use the same targets, dimensions, nested ridge protocol and
training-only tuning budget. Outputs include exact contexts, feature arrays,
OOF predictions, selected alphas, scores, two paired descriptive intervals and
provenance hashes. Human responses are unchanged: this pilot evaluates model
history dependence in brain prediction, not a human intervention or long-term
memory. It is an exploratory reuse of previously inspected data, not a new
confirmatory cohort. The pilot is now a feature source for the complete Task B
grader below; it is not itself the Agent task. There is no canonical registration.

To rerun the current analysis on already extracted and sealed context features:

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/context_pilot.py \
  --features-from "$BPB_EXPANSION_ROOT/task-b-pilot" \
  --output "$BPB_EXPANSION_ROOT/task-b-reanalysis"
```

The replay verifies every source artifact hash and records the original manifest
hash. `brain.npy`, `stimuli.json`, `contexts.json` and feature files retain all
192 candidates; `analysis_selection.json`, `splits.json` and result prediction
IDs describe the retained analysis subset. Reanalysis is exploratory development,
not an independent replication of a result.

## Offline tests

```bash
npm run test:alignment-incremental
npm run test:alignment-expansion
```

The suite checks independent scikit-learn agreement, grouped nested splits,
test-response perturbation, explicit constant-response QC, valid control choices,
negative increments, ID reordering, forged conclusions/predictions, unsafe array
rejection, worker failure classification, a real trusted-process replay and
past-only context design. It downloads nothing and does not require Docker.

## Prepare B–F

These commands use only the already cached distilgpt2 weights. Set `HF_HOME`,
`XDG_CACHE_HOME`, `BRAINIO_HOME` as in the context extraction above. Sources are
locked by size/SHA256 in [_shared/expansion/sources.json](_shared/expansion/sources.json).
Downloads occur only through an explicit `download` command, never during task
setup or scoring. The EEG source files total about 2.14 GB; no Llama is required.
Source data and derived packets remain outside Git. Check the source licenses
before redistribution; downloading public material does not grant publication rights.

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py prepare-b \
  --source "$BPB_EXPANSION_ROOT/task-b-pilot" --output "$BPB_EXPANSION_ROOT/b-inputs"

for task in F E C D; do
  "$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py download \
    --task "$task" --raw "$BPB_EXPANSION_ROOT/raw"
done

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py prepare-f \
  --csv "$BPB_EXPANSION_ROOT/raw/f-brain-lang-data_participant_20230728.csv" \
  --cache "$BPB_EXISTING_CACHE" --output "$BPB_EXPANSION_ROOT/f-inputs" \
  --hidden "$BPB_EXPANSION_ROOT/f-owner-responses"

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py prepare-e \
  --csv "$BPB_EXPANSION_ROOT/raw/e-data_participants_trial_df.csv" \
  --output "$BPB_EXPANSION_ROOT/e-inputs"

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py prepare-c \
  --raw "$BPB_EXPANSION_ROOT/raw" --cache "$BPB_EXISTING_CACHE" \
  --output "$BPB_EXPANSION_ROOT/c-inputs"

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py convert-eeg2 \
  --raw "$BPB_EXPANSION_ROOT/raw" --output "$BPB_EXPANSION_ROOT/eeg2-converted" \
  --image "$BPB_INFERENCE_IMAGE"

"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py prepare-d \
  --converted "$BPB_EXPANSION_ROOT/eeg2-converted" --cache "$BPB_EXISTING_CACHE" \
  --output "$BPB_EXPANSION_ROOT/d-inputs"
```

The owner converter verifies the locked author files and deserializes their NumPy
object dictionaries only inside a restricted, offline Docker container. Agent
packets/scorers read numerical arrays with `allow_pickle=False`. Image metadata
is checked against concept IDs; EEG directory-number prefixes are stripped before
creating semantic prompts. The complete source EEG time axis is preserved.

`verify-sources --task C --raw DIR` (likewise D/E/F) performs the locked source
checks and bounded archive extraction without downloading. A completed file that
differs is an error; interrupted downloads remain `.part` and can be resumed.
Preparation refuses to overwrite any completed or partial output directory.

## Stage and run B–F

For each analysis task, replace `b` with `c`, `d`, or `e` as needed:

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py stage \
  --inputs "$BPB_EXPANSION_ROOT/b-inputs" --output "$BPB_EXPANSION_ROOT/task-b"
```

F additionally needs owner-only responses and a persistent ledger assigned to
one Agent identity. The ledger must be reused across that Agent's runs; setup
copies neither it nor the hidden response packet into the workspace.

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py stage \
  --inputs "$BPB_EXPANSION_ROOT/f-inputs" --output "$BPB_EXPANSION_ROOT/task-f" \
  --hidden "$BPB_EXPANSION_ROOT/f-owner-responses" \
  --ledger "$BPB_EXPANSION_ROOT/owner-ledgers/AGENT_ID"
```

| Letter | Task ID |
|---|---|
| B | `alignment-context-dependence` |
| F | `alignment-stimulus-selection` |
| E | `alignment-learning-transfer` |
| C | `alignment-brain-behavior` |
| D | `alignment-temporal-correspondence` |

Use the same `validate → run --adapter manual → resume → submit verify → score`
commands as A, substituting the task ID and staged root. Always pass
`--tasks "tasks,<staged-root>"`. Manual mode does not launch or isolate an Agent;
provide a separate restricted Agent environment. F's scorer must remain on the
owner side. The scorer emits `selection_effect`/`selection_valid` for a valid F
decision; it emits no effect for invalid decisions, instead of treating zero as
a failure value on this signed scale.

## B–F maintainer checks

These commands deliberately create a solution for maintainer validation and must
not be included in Agent setup. Example for B:

```bash
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py reference-submission \
  --task B --output "$BPB_EXPANSION_ROOT/b-reference-source"
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py reference \
  --inputs "$BPB_EXPANSION_ROOT/b-inputs" --plan "$BPB_EXPANSION_ROOT/b-reference-source/plan.json" \
  --output "$BPB_EXPANSION_ROOT/b-reference-results"
"$BPB_ALIGNMENT_PYTHON" -B tasks/alignment/_shared/expansion_cli.py evaluate \
  --inputs "$BPB_EXPANSION_ROOT/b-inputs" --submission "$BPB_EXPANSION_ROOT/b-reference-source" \
  --saved-results "$BPB_EXPANSION_ROOT/b-reference-results" \
  --output "$BPB_EXPANSION_ROOT/b-grade" --image "$BPB_INFERENCE_IMAGE"
```

For F, also supply `--hidden` and `--ledger`; `--saved-results` is mandatory.
Its ledger accepts identical frozen retries and rejects changed source, choices,
predictions, plan or hidden-data version. A maintainer baseline should have a
separately named ledger from actual Agents. A script pass is not an Agent result.
