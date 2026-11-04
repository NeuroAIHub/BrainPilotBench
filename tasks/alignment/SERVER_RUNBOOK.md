# Real Brain-Score server development runbook

Status on 2026-11-02: Linux CPU validation has exercised the real distilgpt2 /
Pereira384 path, including official live/cache and traced/untraced equivalence.
See [SERVER_VALIDATION.md](SERVER_VALIDATION.md) for exact results, environment,
fixes and remaining checks. This is not an accepted benchmark release or an
Agent result; the intended Llama model requires separate validation.

Keep the existing synthetic tasks as fixtures. The real candidate is still absent
from canonical `bp-bench list`. `stage-task1` and `stage-task2` generate temporary
task definitions outside Git for explicit `--tasks` runs, without promoting them.

## 1. Server environment and storage

Use a normal non-root user and Python 3.11,
Node >=22 and Git. Docker is needed only when evaluating submitted Task1 code.
Example paths below are placeholders; choose a writable data disk outside Git.

```bash
export BPB_REPO=/path/to/BrainPilotBench
export BPB_ALIGNMENT_RUN_ROOT=/data/brainpilot-alignment
export BPB_ALIGNMENT_VENV="$BPB_ALIGNMENT_RUN_ROOT/venv"
export HF_HOME="$BPB_ALIGNMENT_RUN_ROOT/huggingface"
export XDG_CACHE_HOME="$BPB_ALIGNMENT_RUN_ROOT/cache"
export BRAINIO_HOME="$BPB_ALIGNMENT_RUN_ROOT/brainio"
export BS_INSTALL_DEPENDENCIES=no
mkdir -p "$BPB_ALIGNMENT_RUN_ROOT"
cd "$BPB_REPO"
BPB_PYTHON=python3.11 bash tasks/alignment/_env/setup-server.sh --install
source "$BPB_ALIGNMENT_VENV/bin/activate"
python tasks/alignment/_shared/server.py doctor
python -c 'from brainscore_core.supported_data_standards.brainio.assemblies import NeuroidAssembly; from brainscore_language.benchmarks.pereira2018.benchmark import _Pereira2018Experiment; print("Brain-Score imports OK")'
python -B tasks/alignment/_shared/test_server.py
```

The bootstrap downloads Python dependencies only. Its requirements file is a
bootstrap constraint set, not a validated full lock. It records resolved versions
in `$BPB_ALIGNMENT_VENV/requirements.resolved.txt`; keep that with server results.
Core 2.5.0 supplies the `supported_data_standards` imports used by the pinned
Language source. Core 2.1 does not; metadata-only `doctor` output and `pip check`
cannot detect that incompatibility, so run the import check above as well.
Python 3.12+ is excluded because Core's pinned xarray version calls the legacy
`importlib.metadata.entry_points().get` API when opening real NetCDF data.
The upstream environment_lock.yml contains pandas 3.0.0 while pyproject.toml
requires pandas <3, so this draft does not blindly copy that environment file.
Resolve any platform-specific package conflict on the server, record the final
lock, and rebuild the worker image with the same numerical versions. No runtime
plugin is allowed to silently install missing dependencies.

For Llama, first obtain model access and authenticate on the preparation host via
the usual Hugging Face login/environment. Credentials do not belong in config
JSON, Git, Agent workspaces or scoring containers. Model files stay in HF_HOME;
brain downloads use the upstream cache under the configured runtime environment.

## 2. Resolve the model and prepare a cache

Start with the smaller distilgpt2 config to check the integration, then use
server-config.example.json for Llama-3.2-1B. These are separate runs and model
identities; the former never substitutes for a missing Llama run.

```bash
python tasks/alignment/_shared/server.py resolve-config \
  --config tasks/alignment/server-config.distilgpt2.json \
  --output "$BPB_ALIGNMENT_RUN_ROOT/distilgpt2.config.json" --allow-download

python tasks/alignment/_shared/server.py prepare \
  --config "$BPB_ALIGNMENT_RUN_ROOT/distilgpt2.config.json" \
  --output "$BPB_ALIGNMENT_RUN_ROOT/distilgpt2-cache" \
  --device cuda --allow-download
```

Use `--device cpu` instead when CUDA is unavailable; CUDA requests fail explicitly
rather than silently falling back. Preparation loads the pinned official
Pereira384 benchmark, its processed language-network assembly and ceiling, then
extracts all configured model layers using the official passage-prefix/last-token
path. The two config revisions are resolved to immutable commit hashes first.
Float32, unquantized model features are required in this draft. Module paths are
checked against the actual model. No model training or raw MRI preprocessing occurs.

The output cache has `features/layer-NNN.npy`, `stimuli.json`, `brain.nc`, config,
protocol, ceiling, runtime provenance and a SHA-256 manifest. It contains inputs,
not reference answers. Outputs must be new directories; after an interrupted
prepare, use a fresh path. No incomplete output without a valid manifest is accepted.

## 3. Validate the fixed-layer reference

```bash
python tasks/alignment/_shared/server.py score-fixed \
  --cache "$BPB_ALIGNMENT_RUN_ROOT/distilgpt2-cache" \
  --output "$BPB_ALIGNMENT_RUN_ROOT/distilgpt2-reference" \
  --device cpu --compare-live --allow-download
```

The default layer comes from `config.task1_layer`; use `--layer MODULE` for another
cached layer. Without `--compare-live`, scoring uses only the verified local
cache and preinstalled metric. With it, the original official benchmark entry
is called on the live model (weights must already be cached); its data loader may
fetch upstream data, hence the explicit download flag. Do not run that option
inside the offline submission worker.

Inspect:

- `results/summary.json`: raw, official normalized and unclipped scores.
- `results/folds.json`: actual stimulus train/test IDs and selected alpha per fold.
- `results/predictions.npz`, `results/fold_scores.csv`: recorded upstream outputs.
- `verification.json`: traced/untraced and live/cached scalar comparisons.
- `runtime.json`: package versions and actual device.

Scalar equivalence is a first server check, not complete acceptance. Also inspect
assembly coordinates, feature ordering, group separation, fold prediction values,
cross-device tolerances and peak memory/runtime. Atol=1e-6 and rtol=1e-5 are
provisional; they are not established scientific tolerance bounds.

Repeat the resolve/prepare/reference sequence with server-config.example.json and
distinct output paths for the intended Llama model. Its default Task1 layer is
model.layers.8; Task2 caches blocks 0..15, with block 15 as the last-layer baseline.

## 4. Run Task1 through the benchmark CLI

Build a development worker image explicitly on the server (this installs image
dependencies, but does not include model weights or brain data):

```bash
docker build -f tasks/alignment/_env/Dockerfile.server -t bpb-brainscore-server-draft .
python tasks/alignment/_shared/server.py stage-task1 \
  --input "$BPB_ALIGNMENT_RUN_ROOT/distilgpt2-cache" \
  --output "$BPB_ALIGNMENT_RUN_ROOT/task1"
npm ci
npm run build
node dist/cli.js run alignment-pereira2018-analysis \
  --tasks "$BPB_ALIGNMENT_RUN_ROOT/task1" --adapter manual --agent YOUR_AGENT_ID \
  --workspace "$BPB_ALIGNMENT_RUN_ROOT/task1-workspace" \
  --out "$BPB_ALIGNMENT_RUN_ROOT/runs" --run-id task1-001
```

Let the Agent operate in the printed workspace. This is a manual handoff; it does
not launch or isolate the Agent itself. The prepared input includes both X and Y
because this task asks for an analysis implementation. The parent reference and
other runs are outside the Agent's allowed filesystem.

For a maintainer-only smoke submission, copy `_shared/server_reference_analyze.py`
to `task1-workspace/submission/analyze.py`. On the host its import needs
`PYTHONPATH="$BPB_REPO/tasks/alignment/_shared"`. Generate saved results in a new
empty output directory, then copy those results into the task workspace. The
worker image already supplies that module on PYTHONPATH. Do not hand this
complete reference submission to an Agent being evaluated.

After the Agent finishes, run the printed resume command, then:

```bash
node dist/cli.js submit verify "$BPB_ALIGNMENT_RUN_ROOT/runs/task1-001" \
  --tasks "$BPB_ALIGNMENT_RUN_ROOT/task1"
# Choose a quota supported by `docker info --format '{{.NCPU}}'`.
export BPB_ALIGNMENT_WORKER_CPUS=2
node dist/cli.js score "$BPB_ALIGNMENT_RUN_ROOT/runs/task1-001" \
  --tasks "$BPB_ALIGNMENT_RUN_ROOT/task1" \
  --isolation docker --inference-image bpb-brainscore-server-draft
```

The trusted parent uses the server Python environment; only submitted code runs
inside the no-network worker. Inputs/source are read-only; /output is writable.
No reference answers, evaluator directory or model weights are mounted. The
image tag is resolved to a local immutable ID before execution and never pulled
on demand. Before submitted code runs, the parent compares the image's numerical
package versions and adapter source hashes with its own environment; a mismatch
is an infrastructure failure, not an Agent zero. Docker creation/start failures
also produce no score; a program that starts and then fails receives zero.
Rebuild with the resolved server
versions if the bootstrap ranges resolved differently. Draft limits are 4 CPUs,
8 GiB, 900 seconds and 512 MiB result files. Set `BPB_ALIGNMENT_WORKER_CPUS`
for staged CLI runs, or `evaluate --cpus` for direct runs, when the daemon has
fewer CPUs; the grade records the selected limit. Calibrate these limits on the
server. Docker disk quotas and full isolation acceptance
remain operator responsibilities. This path checks saved outputs and one rerun;
do not claim the synthetic suite's extra metamorphic checks ran on real data.

## 5. Build Task2 results with a genuine outer holdout

```bash
python tasks/alignment/_shared/server.py build-profile \
  --cache "$BPB_ALIGNMENT_RUN_ROOT/distilgpt2-cache" \
  --output "$BPB_ALIGNMENT_RUN_ROOT/profile" \
  --device cpu --seed 17 --fraction 0.2 --folds 5 --margin 0.02
python tasks/alignment/_shared/server.py stage-task2 \
  --input "$BPB_ALIGNMENT_RUN_ROOT/profile/packet.json" \
  --output "$BPB_ALIGNMENT_RUN_ROOT/task2"
```

The material split is written before any regression. Development uses inner
grouped CV; confirmation is predicted by a readout fitted exclusively on all
development data. Test responses never enter fitting or alpha selection. All
layer results may be precomputed by the trusted operator, but the MCP withholds
confirmation until selection is frozen. Do not expose profile/packet.json or
traces to the Agent. Do not re-run different seeds to select a favorable outcome.

This protocol computes per-subject Pearson over pooled held-out predictions,
then median neuroids within subject and equal mean subjects. It does NOT reuse
Task1's full-data CV scores or its official ceiling as though the split were
unchanged. The real analysis profile has a distinct ID and no claimed equivalence
to the official benchmark total. The 0.02 and 75% descriptive thresholds are
engineering defaults that require later scientific review.

## 6. Connect Task2 MCP and grade answers

Create an operator-owned session outside the Agent workspace:

```bash
install -d -m 700 "$BPB_ALIGNMENT_RUN_ROOT/sessions/task2-001"
cp "$BPB_ALIGNMENT_RUN_ROOT/profile/packet.json" "$BPB_ALIGNMENT_RUN_ROOT/sessions/task2-001/packet.json"
```

Configure the Agent host to launch this stdio MCP command, using absolute paths:

```bash
python tasks/_example/alignment-profile-synthetic/lib/service.py \
  --packet "$BPB_ALIGNMENT_RUN_ROOT/sessions/task2-001/packet.json" \
  --journal "$BPB_ALIGNMENT_RUN_ROOT/sessions/task2-001/journal.jsonl" --allow-real
```

Use a fresh journal for each new session; only resume the same packet with
`--resume`. The generic benchmark launcher does not automatically configure MCP.
Use separate users/permissions or a supervised service to enforce ownership:
different directory names alone do not isolate a same-user Agent.

Run `alignment-pereira2018-profile` with `--tasks "$BPB_ALIGNMENT_RUN_ROOT/task2"`
and manual/your Agent adapter, then resume to collect answers.json/report.md.
Only during scoring set the operator evidence variable:

```bash
BPB_ALIGNMENT_PROFILE_EVIDENCE_DIR="$BPB_ALIGNMENT_RUN_ROOT/sessions/task2-001" \
  node dist/cli.js score "$BPB_ALIGNMENT_RUN_ROOT/runs/task2-001" \
  --tasks "$BPB_ALIGNMENT_RUN_ROOT/task2"
```

For a separate maintainer smoke session, `solution/reference_report.py` accepts
`--packet`, `--journal`, `--output`, and `--allow-real`; it launches the service
itself. Do not start another service using that journal. This scripted baseline
is not a real Agent result. Free-form reports remain ungraded.

## 7. Server acceptance checklist

Record actual outcomes, not just successful installation:

- Dependency resolution and pinned upstream commit verified; final lock retained.
- Official dataset identity/coordinate export and model revision verified.
- Live/cached and traced/untraced scores plus per-fold outputs compared.
- Development/confirmation story and stimulus IDs disjoint before fitting.
- CPU/GPU tolerances, time and memory calibrated; no silent device fallback.
- Task1 positive/negative submissions exercised in the real Docker image.
- Task2 all four answers and the pre-commit confirmation restriction exercised.
- Operator data/logs demonstrably inaccessible to the Agent process.

Only after these checks should the canonical task definitions, final data.lock,
immutable images and scientific acceptance records be published. No automatic
upload, push, task promotion or claim of acceptance is performed by these tools.
