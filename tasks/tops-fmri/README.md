# tops-fmri — Tonic Pain Signature (linear FC, external validation)

Category: `fmri-analysis` · Domain: `fmri-analysis` · Version `0.2`

## Quick start (Agent user)

Only public Study3 data is required:

```bash
npm ci && npm run build && npm link
bash tasks/tops-fmri/env/setup-python.sh
source .venv/bin/activate
bp-bench doctor tops-fmri
bp-bench fetch tops-fmri --public
bp-bench run tops-fmri --adapter manual --agent my-agent@1
```

The environment script supports CPython 3.10–3.13, creates the repository-local
`.venv`, and installs the exact numerical dependency versions tested for this
release. It never writes to global or user site-packages. Set
`BPB_PYTHON=/absolute/path/to/python` to select a base interpreter, or
`BPB_VENV_DIR=/absolute/path` to put the environment elsewhere. `doctor` uses
an active virtual environment automatically; it also accepts
`--python /absolute/path/to/python`.

If installation reports `CERTIFICATE_VERIFY_FAILED`, repair the base Python's
CA certificates before retrying. On macOS the script safely uses the system
`/etc/ssl/cert.pem` bundle when Python's bundled CA file is absent; a durable
python.org repair is to run `Install Certificates.command` under
`/Applications/Python 3.x/`. On Ubuntu, reinstall `ca-certificates`. If PyPI requires a proxy, export
`https_proxy` and `http_proxy` as HTTP proxy URLs. Do not use `--trusted-host`
or disable TLS verification.

Run the Agent in the printed workspace without evaluator/Hugging Face
credentials, then execute the printed `--resume` command. BrainPilot users can
replace the last command with:

```bash
bp-bench run tops-fmri \
  --adapter brainpilot \
  --base-url http://127.0.0.1:9001 \
  --workspace-root /absolute/path/to/BrainPilot/brainpilot/workspaces \
  --agent brainpilot@local
```

For an untrusted local command Agent, use Docker isolation instead of the
manual handoff or local process mode:

```bash
bp-bench doctor tops-fmri --isolation docker
bp-bench run tops-fmri \
  --adapter command \
  --isolation docker \
  --image "your-agent@sha256:<64-hex-digest>" \
  --command 'your-agent --prompt "$BPB_TASK_PROMPT"' \
  --agent your-agent@1 \
  --official
```

Network access is disabled unless explicitly enabled with `--network bridge`.
Only public task data and the Agent workspace are mounted; private Study4/5
data and evaluator credentials remain outside the container.

Private Study4/Study5 data is not needed by Agent users and must never be placed
in the Agent workspace.

## What the agent does

Train a **linear** 279 ROI / 38781 edge functional-connectivity signature on
the public **Study3** fMRI dynamic-FC data (`dfc_5bin_dat` × `CAPS/REST` +
pain ratings), then submit:

- `models/study3_signature_weights.npz` — `w_raw: (38781,) float`, `b_raw: scalar`
- `models/signature_manifest.json` — metadata (edge_order, input_transform, …)
- `scripts/apply_signature.py` — numpy-only inference entry
- `report.md`, `results/edge_order_validation.json`, `results/model_card.json`

The mathematical form is fixed: `signature_response = transformed_x @ w_raw + b_raw`,
where `transformed_x` is either `x` or `arctanh(x)`. Non-linear / transductive
methods are explicitly disallowed for the final submission.

## What the grader does (`checks/check.sh`)

`evaluate_external.py`:

1. Locates the private eval dir (env var `BPB_TOPS_PRIVATE_EVAL_DIR`, or the
   Oracle-only `./private_eval/` fallback).
2. Copies `features/study{4,5}_features.npz` into a scorer-side temp dir.
3. Invokes the agent's `apply_signature.py --eval-features-dir <tmp>
   --model-dir artifacts/models --out-dir <tmp>` with a 120 s hard timeout.
4. Reads `study{4,5}_predictions.csv`, loads the **private** labels, computes
   Study4 Pearson r (per condition) + raw Study5 AUC (per site), then maps each
   AUC to `max(0, 2·AUC−1)` so chance is zero before aggregating
   `score = 0.5·study4_score + 0.5·study5_score`.
5. Emits 9 keys between `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES` sentinels.

The labels never enter the agent workspace. See `checks/README.md`.

### Score compatibility

Task v0.2 chance-centers Study5 AUC before aggregation. Scores produced by
v0.1 used raw AUC in the subgroup score and must not be mixed with v0.2
scores. Historical v0.1 results remain unchanged; a fresh v0.2 reference
formula baseline is re-aggregated from the preserved raw diagnostics and
frozen in `checks/test_metrics.py`. Raw Pearson r and AUC diagnostics keep
their original definitions; an end-to-end evaluator rerun can confirm the
same baseline before release without rewriting v0.1 history.

## Data (`data.lock`)

Four content-addressed entries. Public entries are the default fetch scope;
private entries are evaluator-only and must be requested explicitly.

| Name | Scope | Size | Where it lands |
|---|---|---:|---|
| `study3_train.mat` | public | 954 MB | `public_data/whole_participants/FC_and_pain/` (via `env/setup.sh` symlink) |
| `public_support.tar.zst` | public | 12 MB | `public_data/atlas/` + `public_data/example_participant/` (untarred) |
| `private_features.tar.zst` | private | 75 MB | `$BPB_TOPS_PRIVATE_EVAL_DIR/features/` (evaluator only) |
| `private_labels.tar.zst` | private | 1.9 KB | `$BPB_TOPS_PRIVATE_EVAL_DIR/labels/` (evaluator only) |

All four entries are pinned to HF commit shas
(`Tasks-Data-Public@5be1911c…`, `Tasks-Data-Private@03674af4…`). The private
bundle lives in a **gated** HF dataset that requires `HF_TOKEN` — set it in
the scorer/runner environment; the BPB `hf://` fetcher forwards it as a
Bearer token and never persists it. Never fetch from `main`; a moving branch
would silently drift the data version.

### Data source and citation

The tonic-pain functional-connectivity data and external validation cohorts
originate from the study below. Please cite it when using this task or its
data:

> Lee, J.-J., Kim, H. J., Čeko, M., Park, B.-y., Lee, S. A., Park, H., Roy, M.,
> Kim, S.-G., Wager, T. D., & Woo, C.-W. (2021). A neuroimaging biomarker for
> sustained experimental and clinical pain. *Nature Medicine, 27*(1), 174–182.
> https://doi.org/10.1038/s41591-020-1142-7

Agent workflow (no private access required):

```bash
bp-bench doctor tops-fmri
bp-bench fetch tops-fmri                 # public-only by default
cd <agent-workspace>
bash <repo>/tasks/tops-fmri/env/setup.sh # defaults to --role agent
```

Maintainer/evaluator workflow, run only after the agent has exited:

```bash
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
hf auth login
export XDG_CACHE_HOME=/absolute/evaluator-only/cache
bp-bench fetch tops-fmri --private
export BPB_TOPS_PRIVATE_EVAL_DIR=/absolute/evaluator-only/path
bash tasks/tops-fmri/env/setup.sh --role evaluator
docker build -t brainpilot-bench-inference:local \
  -f docker/inference/Dockerfile .
bp-bench score /absolute/path/to/run-bundle \
  --isolation docker \
  --inference-image brainpilot-bench-inference:local
```

The evaluator directory must be outside the agent workspace. Setup no longer
writes a private path into the agent workspace or its parent directory.
The submitted `apply_signature.py` runs in a no-network, non-root container
that receives read-only models/features and a writable predictions directory;
private labels remain available only to the trusted evaluator process.

## Oracle / NOP gate

- Oracle (`solution/solution.sh`): synthesizes a zero-weight signature, a
  numpy-only `apply_signature.py`, and a 3-sample-per-group dummy dataset in
  `./private_eval/`. `check.sh` runs end-to-end and emits real numbers
  (chance-level; the value doesn't matter — the gate only checks that the
  scorer produced a payload).
- NOP: empty bundle → `apply_signature.py` missing → `evaluate_external.py`
  bails with a stderr note and exit 0 → no sentinel → BPB scorer reports
  `unscored` (never `0`).

## Follow-ups (not blocking merge)

- **Additional adapters**: the built-in BrainPilot, command, and manual
  adapters all run public setup before the agent starts. Specialized remote
  runtimes can implement the same `AgentAdapter` contract.
- **Automated calibration**: `checks/output_schema.json` describes the raw
  metric contract but there's no per-condition tolerance table baked into
  the grader — a real signature's `score` distribution should stabilize
  once the first few reference runs land.
