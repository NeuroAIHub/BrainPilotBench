# sleep-edf — 5-class Sleep Staging (Sleep-EDF Cassette)

Category: `eeg-sleep-staging` · Domain: `eeg-sleep-staging` · Version `0.1`

## Quick start (Agent user)

Only public subject 0-15 recordings are required:

```bash
npm ci && npm run build && npm link
bash tasks/sleep-edf/env/setup-python.sh
source .venv/bin/activate
bp-bench doctor sleep-edf
bp-bench fetch sleep-edf --public
bp-bench run sleep-edf --adapter manual --agent my-agent@1
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
bp-bench run sleep-edf \
  --adapter brainpilot \
  --base-url http://127.0.0.1:9001 \
  --workspace-root /absolute/path/to/BrainPilot/brainpilot/workspaces \
  --agent brainpilot@local
```

For an untrusted local command Agent, use Docker isolation:

```bash
bp-bench doctor sleep-edf --isolation docker
bp-bench run sleep-edf \
  --adapter command \
  --isolation docker \
  --image "your-agent@sha256:<64-hex-digest>" \
  --command 'your-agent --prompt "$BPB_TASK_PROMPT"' \
  --agent your-agent@1 \
  --official
```

Network access is disabled unless explicitly enabled with `--network bridge`.
Only public subject 0-15 recordings and the Agent workspace are mounted;
private subject 16-19 data and evaluator credentials remain outside the
container.

Private subject 16-19 data is not needed by Agent users and must never be
placed in the Agent workspace. The optional LOSO supplement (subject 16-19
mirror for cross-subject LOSO training) is off by default; opt in with
`BPB_SLEEP_EDF_INCLUDE_LOSO=1` before running `env/setup-agent.sh`.

## What the agent does

Design a PyTorch `nn.Module` **SleepAgentModel** that classifies a
`(B, 1, 3000)` tensor of preprocessed Fpz-Cz sleep EEG (30 s epoch at
100 Hz) into 5 sleep stages (Wake / N1 / N2 / N3 / REM). The submitted
file goes to:

- `EEG_sleep/sleep_agent_model.py` in the agent's workspace.

The class must:

- support `forward(torch.randn(2, 1, 3000))` returning `torch.Size([2, 5])`,
- not perform training, evaluation, data I/O, or file writes at import time,
- not directly reuse prebuilt sleep-staging models (DeepSleepNet, TinySleepNet,
  SleepStagerChambon2018, U-Time / U-Sleep, etc. from `braindecode.models`).

The scorer trains the class **once**, sharing across all subjects, on
subjects 0-13 with subjects 14-15 for early stopping (Adam lr=1e-3,
batch 64, class-weighted CE, up to 20 epochs, patience 5 on val loss),
then predicts every 30 s epoch on subjects 16-19. Agents are never given
subject 16-19 EDF or hypnogram — those recordings come from
`Tasks-Data-Private/sleep-edf/private.tar.zst`.

## What the grader does (`checks/check.sh`)

`evaluate_external.py`:

1. Locates the private eval dir (env var `BPB_SLEEP_EDF_PRIVATE_EVAL_DIR`,
   or the Oracle-only `./private_eval/` fallback).
2. Reads `manifests/subjects.json` for the subject → filename mapping.
3. Spawns an isolated child process (`train_and_infer.py`) with a
   150 min budget:
   - Imports the submitted `SleepAgentModel` from a scorer-controlled copy.
   - Loads all recordings for subjects 0-13 / 14-15 / 16-19, applying the
     frozen preprocessing (pick `EEG Fpz-Cz`, 0.3-35 Hz bandpass, resample
     to 100 Hz, head/tail Wake crop to 30 min each, 30 s non-overlapping
     epoching, `Sleep stage 3` and `Sleep stage 4` merged into label 3,
     `Movement time` / `Sleep stage ?` dropped).
   - Trains once with Adam lr=1e-3, batch 64, class-weighted CrossEntropyLoss,
     up to 20 epochs, early-stops on val loss (patience 5).
   - Predicts every 30 s epoch on subjects 16-19; writes
     `subject_id,epoch_id,predicted_label` CSV back.
4. Reads back predictions, re-loads the private hypnogram labels with
   the same load pipeline (ensuring N and epoch order match exactly),
   computes accuracy / balanced accuracy / macro F1 / Cohen's kappa /
   per-class recall on the concatenated subject-16..19 predictions.
5. Emits 10 keys between `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES` sentinels.

Subject 16-19 hypnograms never enter the agent workspace. See
`checks/README.md`.

## Data (`data.lock`)

Three content-addressed entries. Two are public (main + optional LOSO
supplement); one is private (evaluator-only, gated).

| Name | Scope | Size | Where it lands |
|---|---|---:|---|
| `public-main.tar.zst`      | public  | 934 MB | `public_data/` (subjects 0-15; via `env/setup-agent.sh`) |
| `loso-supplement.tar.zst`  | public  | 235 MB | `public_data/sleep-cassette/` (subjects 16-19 mirror; opt-in with `BPB_SLEEP_EDF_INCLUDE_LOSO=1`) |
| `private.tar.zst`          | private | 195 MB | `$BPB_SLEEP_EDF_PRIVATE_EVAL_DIR/test_edf/` (subjects 16-19; scorer only) |

All three entries are pinned to HF commit shas
(`Tasks-Data-Public@acce5609…`, `Tasks-Data-Private@6e21f98a…`). The
private bundle lives in a **gated** HF dataset that requires `HF_TOKEN` —
set it in the scorer/runner environment; the BPB `hf://` fetcher forwards
it as a Bearer token and never persists it. Never fetch from `main`; a
moving branch would silently drift the data version.

### Data source and citations

The Sleep-EDF recordings are distributed through PhysioNet. Please cite both
the dataset study and the PhysioNet resource when using this task or its data:

> Kemp, B., Zwinderman, A. H., Tuk, B., Kamphuisen, H. A. C., & Oberye,
> J. J. L. (2000). Analysis of a sleep-dependent neuronal feedback loop: the
> slow-wave microcontinuity of the EEG. *IEEE Transactions on Biomedical
> Engineering, 47*(9), 1185–1194. https://doi.org/10.1109/10.867928

> Goldberger, A. L., Amaral, L. A. N., Glass, L., Hausdorff, J. M., Ivanov,
> P. Ch., Mark, R. G., Mietus, J. E., Moody, G. B., Peng, C.-K., & Stanley,
> H. E. (2000). PhysioBank, PhysioToolkit, and PhysioNet: Components of a new
> research resource for complex physiologic signals. *Circulation, 101*(23),
> e215–e220. https://doi.org/10.1161/01.CIR.101.23.E215

Agent workflow (no private access required):

```bash
bp-bench doctor sleep-edf
bp-bench fetch sleep-edf                 # public-only by default; both public tarballs
cd <agent-workspace>
bash <repo>/tasks/sleep-edf/env/setup.sh # defaults to --role agent
# (optional) BPB_SLEEP_EDF_INCLUDE_LOSO=1 bash .../setup.sh to include subjects 16-19 for LOSO
```

Maintainer/evaluator workflow, run only after the agent has exited:

```bash
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
hf auth login
export XDG_CACHE_HOME=/absolute/evaluator-only/cache
bp-bench fetch sleep-edf --private
export BPB_SLEEP_EDF_PRIVATE_EVAL_DIR=/absolute/evaluator-only/path
bash tasks/sleep-edf/env/setup.sh --role evaluator
bp-bench score /absolute/path/to/run-bundle \
  --isolation docker \
  --inference-image sleep-edf-inference:local
```

The evaluator directory must be outside the agent workspace. Setup no longer
writes a private path into the agent workspace or its parent directory.

## Oracle / NOP gate

- Oracle (`solution/solution.sh`): drops a minimal contract-valid
  `SleepAgentModel` at `artifacts/EEG_sleep/sleep_agent_model.py` and a
  `.bpb_oracle_mode` sentinel. `check.sh` sees the sentinel, calls
  `evaluate_external.py --oracle-mode`, and emits chance-level scores
  (score = 0.0, test_accuracy = 0.20). Verifies only the grader
  pipeline; the value doesn't matter.
- NOP: empty bundle → `sleep_agent_model.py` missing → `evaluate_external.py`
  bails with a stderr note and exit 0 → no sentinel → BPB scorer reports
  `unscored` (never `0`).

## Metric set

10 keys, aligned with `categories.yaml eeg-sleep-staging`. See
`checks/output_schema.json` for the full JSON schema.

- **score** = `test_kappa` clipped to `[0,1]` (primary leaderboard column).
- `test_kappa`, `test_accuracy`, `test_balanced_accuracy`, `test_macro_f1`
  (aggregates across subjects 16-19).
- `wake_recall`, `n1_recall`, `n2_recall`, `n3_recall`, `rem_recall`
  (per-class detail; N1 is typically the hardest).

## Follow-ups (not blocking merge)

- **Reference baseline**: `solution/solution.sh` is deliberately
  chance-level for the Oracle gate. Once real submissions land we can
  publish a modest baseline (e.g. a TinySleepNet-style architecture
  hitting `test_kappa ≈ 0.65`) as a leaderboard anchor.
- **20-fold LOSO sibling**: the task packages the fixed 0-15 / 16-19
  split as primary; a `sleep-edf-loso` sibling task could reuse the
  same data without re-uploading.
