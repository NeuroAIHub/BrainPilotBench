# bciciv-2a — 4-class Motor Imagery decoding (BCI Competition IV 2a)

Category: `eeg-motor-imagery` · Domain: `eeg-motor-imagery` · Version `0.1`

## Quick start (Agent user)

Only public session-T data is required:

```bash
npm ci && npm run build && npm link
bash tasks/bciciv-2a/env/setup-python.sh
source .venv/bin/activate
bp-bench doctor bciciv-2a
bp-bench fetch bciciv-2a --public
bp-bench run bciciv-2a --adapter manual --agent my-agent@1
```

`env/setup-python.sh` supports CPython 3.10–3.13, creates the repository-local
`.venv`, and installs the exact numerical dependency versions tested for this
release. It never writes to global or user site-packages. Set
`BPB_PYTHON=/absolute/path/to/python` to select a base interpreter, or
`BPB_VENV_DIR=/absolute/path` to put the environment elsewhere. `doctor` uses
an active virtual environment automatically; it also accepts
`--python /absolute/path/to/python`.

BrainPilot users can replace the last command with:

```bash
bp-bench run bciciv-2a \
  --adapter brainpilot \
  --base-url http://127.0.0.1:9001 \
  --workspace-root /absolute/path/to/BrainPilot/brainpilot/workspaces \
  --agent brainpilot@local
```

For an untrusted local command Agent, use Docker isolation:

```bash
bp-bench doctor bciciv-2a --isolation docker
bp-bench run bciciv-2a \
  --adapter command \
  --isolation docker \
  --image "your-agent@sha256:<64-hex-digest>" \
  --command 'your-agent --prompt "$BPB_TASK_PROMPT"' \
  --agent your-agent@1 \
  --official
```

Network access is disabled unless explicitly enabled with `--network bridge`.
Only public session-T GDF and the Agent workspace are mounted; private
session-E data and evaluator credentials remain outside the container.

Private session-E data is not needed by Agent users and must never be placed
in the Agent workspace.

## What the agent does

Design a PyTorch `nn.Module` **MIAgentModel** that classifies a `(B, 22, 512)`
tensor of preprocessed motor-imagery EEG into 4 classes
(left hand / right hand / feet / tongue). The submitted file goes to:

- `EEG_MI/mi_agent_model.py` in the agent's workspace.

The class must:

- support `forward(torch.randn(2, 22, 512))` returning `torch.Size([2, 4])`,
- not perform training, evaluation, data I/O, or file writes at import time,
- not directly reuse `braindecode`'s prebuilt EEGNet / ShallowFBCSPNet /
  Deep4Net / EEGConformer.

The scorer trains the class **from scratch, one model per subject**, on
session T (230/58 stratified train/val split, seed=42), for up to 100 epochs
with Adam lr=1e-3 and early stopping on val loss (patience 20), then
predicts on the private session E (288 trials). Agents are never given
session-E GDF or labels — the exact 288 hidden labels come from
`Tasks-Data-Private/bciciv-2a/private.tar.zst`.

## What the grader does (`checks/check.sh`)

`evaluate_external.py`:

1. Locates the private eval dir (env var `BPB_BCI2A_PRIVATE_EVAL_DIR`, or
   the Oracle-only `./private_eval/` fallback).
2. Reads `manifests/subjects.json` for the fixed 230/58 stratified split
   indices — the same the agent's `get_subject_data.py` returns.
3. For each of the 9 subjects, spawns an isolated child process
   (`train_and_infer.py`) with a 25 min budget:
   - Imports the submitted `MIAgentModel` from a scorer-controlled copy.
   - Loads session-T GDF, preprocesses (22 EEG channels, 4-38 Hz
     bandpass, resample 250→128 Hz, 4 s window per 768 cue) → `(288, 22, 512)`.
   - Trains a fresh instance with Adam lr=1e-3, batch 64, ≤100 epochs,
     early stop on val loss (patience 20).
   - Loads session-E GDF, predicts 288 held-out labels, writes CSV back.
4. Reads back predictions, loads the private `A0xE.mat` classlabels,
   computes per-subject accuracy + Cohen's kappa + macro F1, aggregates
   the means.
5. Emits 22 keys between `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES` sentinels.

Session-E labels never enter the agent workspace. See `checks/README.md`.

## Data (`data.lock`)

Two content-addressed entries. Public is the default fetch scope; private is
evaluator-only and must be requested explicitly.

| Name | Scope | Size | Where it lands |
|---|---|---:|---|
| `public.tar.zst` | public | 194 MB | `public_data/` (via `env/setup-agent.sh`) |
| `private.tar.zst` | private | 195 MB | `$BPB_BCI2A_PRIVATE_EVAL_DIR/{test_gdf,true_labels,manifests}/` |

Both entries are pinned to HF commit shas
(`Tasks-Data-Public@acce5609…`, `Tasks-Data-Private@6e21f98a…`). The private
bundle lives in a **gated** HF dataset that requires `HF_TOKEN` — set it in
the scorer/runner environment; the BPB `hf://` fetcher forwards it as a
Bearer token and never persists it. Never fetch from `main`; a moving branch
would silently drift the data version.

### Data source and citation

The recordings are from BCI Competition IV data set 2a. Please cite the
competition review when using this task or its data:

> Tangermann, M., Müller, K.-R., Aertsen, A., Birbaumer, N., Braun, C.,
> Brunner, C., Leeb, R., Mehring, C., Miller, K. J., Müller-Putz, G. R., et al.
> (2012). Review of the BCI Competition IV. *Frontiers in Neuroscience, 6*, 55.
> https://doi.org/10.3389/fnins.2012.00055

Agent workflow (no private access required):

```bash
bp-bench doctor bciciv-2a
bp-bench fetch bciciv-2a                  # public-only by default
cd <agent-workspace>
bash <repo>/tasks/bciciv-2a/env/setup.sh  # defaults to --role agent
```

Maintainer/evaluator workflow, run only after the agent has exited:

```bash
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
hf auth login
export XDG_CACHE_HOME=/absolute/evaluator-only/cache
bp-bench fetch bciciv-2a --private
export BPB_BCI2A_PRIVATE_EVAL_DIR=/absolute/evaluator-only/path
bash tasks/bciciv-2a/env/setup.sh --role evaluator
bp-bench score /absolute/path/to/run-bundle \
  --isolation docker \
  --inference-image bciciv-2a-inference:local
```

The evaluator directory must be outside the agent workspace. Setup no longer
writes a private path into the agent workspace or its parent directory.

## Oracle / NOP gate

- Oracle (`solution/solution.sh`): drops a minimal contract-valid
  `MIAgentModel` at `artifacts/EEG_MI/mi_agent_model.py` and a
  `.bpb_oracle_mode` sentinel. `check.sh` sees the sentinel, calls
  `evaluate_external.py --oracle-mode`, and emits chance-level scores
  (score = 0.0, mean_accuracy = 0.25). Verifies only the grader
  pipeline; the value doesn't matter.
- NOP: empty bundle → `mi_agent_model.py` missing → `evaluate_external.py`
  bails with a stderr note and exit 0 → no sentinel → BPB scorer reports
  `unscored` (never `0`).

## Metric set

22 keys, aligned with `categories.yaml eeg-motor-imagery`. See
`checks/output_schema.json` for the full JSON schema.

- **score** = `mean_kappa` clipped to `[0,1]` (primary leaderboard column).
- `mean_accuracy`, `mean_kappa`, `mean_macro_f1` (aggregates across 9 subjects).
- `subject_[1-9]_acc`, `subject_[1-9]_kappa` (per-subject detail; kappa may be negative).

## Follow-ups (not blocking merge)

- **Reference baseline**: `solution/solution.sh` is deliberately chance-level
  for the Oracle gate. Once the first real submissions land we can publish
  a modest baseline (e.g. EEGNet-style ~ 0.55 mean_kappa on the official
  hold-out) as a leaderboard anchor.
- **20-fold LOSO or Study 2 additions**: the task packages within-subject
  cross-session as the official primary — LOSO / cross-subject could be
  added as a `bciciv-2a-loso` sibling task without re-uploading data.
