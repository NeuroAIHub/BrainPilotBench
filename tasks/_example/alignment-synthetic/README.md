# Alignment synthetic example

This **synthetic-only, offline engineering fixture** checks analysis correctness.
It is under `_example`, excluded from the canonical collection.
It is not Pereira data, a model benchmark, or official Brain-Score equivalence.
The real task remains a [candidate](../../alignment/alignment-pereira2018-analysis/README.md).

Use an existing Python 3.12 + NumPy 2.3.5 environment. `BPB_ALIGNMENT_PYTHON` selects
its executable. Nothing installs dependencies, fetches data or pulls images.
Protocol and JSON schemas are versioned here; `tasks/alignment/_shared/contract.py`
validates identity, hashes, axes, coverage, finite values and group partitions.
Every fixture contains independently shuffled X/Y rows, five neuroids from two
unequal-size subjects and three passage-group folds. Arrays are only generated
into temporary/workspace directories, never committed. Integer RNG draws and dyadic
values keep public-array bytes independent of BLAS rounding.

The synthetic math is explicitly different from the future official method:
training-only centering, fixed ridge alpha 0.7, unpenalized intercept; Pearson r
for each fold/neuroid (constant-vector correlations become zero); median neuroids
within each subject, mean subjects, mean folds; divide by synthetic ceiling 0.8,
without clipping. No alpha search, standardization or PCA. Inputs are float32 X
and float64 Y, computations/predictions float64. Comparison uses atol=1e-8,
rtol=1e-7. These are fixture tolerances, not calibrated biological-data tolerances.

The reference submission solves centered ridge normal equations. The maintainer
oracle independently solves augmented least squares with an unpenalized intercept.
A hand-computable ridge case and an unequal-subject aggregation case test both
against explicit numbers. `analysis_config.json` and `summary.json` bind the exact
manifest SHA-256. Predictions are matched by (fold_id, stimulus_id, neuroid_id),
fold scores by (fold_id, subject_id, neuroid_id); arbitrary output ordering is valid.

Run the complete offline demonstration after `npm run build`:

```bash
export BPB_ALIGNMENT_PYTHON=/absolute/path/to/existing/python
npm run test:alignment
```

This runs Python checks and `scripts/alignment-smoke.mjs`, which uses the real CLI:
prepare → manual run → reference execution → resume/artifact collection → submit
verify → score → leaderboard. It makes all generated files in a temporary directory,
prints the synthetic result, then removes them. It never creates formal results.
To run individual commands with an explicit workspace/bundle:

```bash
node dist/cli.js prepare alignment-synthetic --workspace /tmp/alignment-workspace
node dist/cli.js run alignment-synthetic --adapter manual --agent synthetic-reference \
  --workspace /tmp/alignment-workspace --out /tmp/alignment-runs --run-id example
# Put analyze.py and helpers in workspace/submission, then execute:
"$BPB_ALIGNMENT_PYTHON" /tmp/alignment-workspace/submission/analyze.py \
  --inputs /tmp/alignment-workspace/inputs --output /tmp/alignment-workspace
node dist/cli.js run alignment-synthetic --adapter manual --resume /tmp/alignment-runs/example
node dist/cli.js submit verify /tmp/alignment-runs/example
BPB_ALIGNMENT_TRUSTED_LOCAL=1 node dist/cli.js score /tmp/alignment-runs/example --isolation process
node dist/cli.js leaderboard /tmp/alignment-runs
```

The solution installer is `solution/solution.sh` (run in an empty bundle directory).
It generates X/Y and computes every saved result. `solution/analyze.py` requires
`tasks/alignment/_shared/contract.py` copied beside it as `alignment_contract.py`.
Setup exposes inputs, schemas and the contract, not this end-to-end solution.
`meta.json` must bind `taskId=alignment-synthetic`, `taskVersion=0.1`.

The trusted parent checks saved outputs, then reruns public, repeated, permuted,
freshly generated and test-Y-perturbed packets. Only that worker's X/Y, code and
empty output directory are mounted. No reference path or oracle flag reaches the
worker. Worker stdout/stderr are discarded; only the parent emits BPB_SCORES.
`alignment-score.json` records outcomes, numerical differences, matching rate and
elapsed time, runtime versions, evaluator hashes and fixture seeds; report interpretation remains an independent human review.

Missing submitted files are `submission_invalid` (no scores); missing/incorrect
runtime outputs, numerical mismatch or worker timeout yield `analysis_success=0`.
Damaged inputs/reference, missing image/dependency and parent failure yield
`scoring_failed` with no score. The outer scorer timeout is 120s; each of five
worker executions is limited to 8s. A low synthetic raw score is never a failure
if it agrees with the reference. The NOP gate emits no scoring sentinel.

Process execution requires `BPB_ALIGNMENT_TRUSTED_LOCAL=1`: it is only for trusted
local fixture tests and **does not isolate files or enforce network denial**.
No untrusted submission should run in that mode. Docker mode uses no network,
read-only root/input/source, dropped capabilities, no-new-privileges, 1 CPU, 512 MB,
64 PIDs, a bounded tmpfs, unique containers and cleanup on timeout. Output contents
and decompressed NPZ size are checked against 10 MiB; a host disk quota is still
an operator responsibility. Docker execution is a scaffold until exercised with
a prepared local image (`BPB_ALIGNMENT_TEST_IMAGE` opts into its integration test); command-structure tests are not container isolation proof.

`env/Dockerfile` expects a **locally available** Python/NumPy base passed as
`LOCAL_BASE` (use its immutable digest); there is no default image or install step.
A future offline build can use `docker build --pull=false --network=none` from the
repository root. Supply the built local image via CLI `--isolation docker
--inference-image <image>`. The worker uses `--pull=never`; it never builds or pulls
an image on demand. Do not claim formal acceptance from this example, even with
Docker. The official backend deliberately raises NotImplementedError.

Local Oracle/NOP validation uses the same calculation path (no oracle mode):

```bash
BPB_ALIGNMENT_TRUSTED_LOCAL=1 BPB_SUBMISSION_ISOLATION=process \
  node dist/cli.js validate alignment-synthetic
```

To replay a scored synthetic case, use the `case_seeds.novel` recorded in
`alignment-score.json` with the parent entry `tasks/alignment/_shared/evaluate.py
<bundle> --seed <number>` in the same recorded environment. The seed is selected
by the parent, never exposed as a worker option. See [validation record](VALIDATION.md)
for the exact checks and limitations of this change. CI reuses the repository's
preinstalled numerical stack (currently NumPy 2.1.3) for portability smoke tests;
the proposed offline worker environment is pinned separately in env/requirements.txt.
