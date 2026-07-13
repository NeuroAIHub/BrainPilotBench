# tops-fmri — Tonic Pain Signature (linear FC, external validation)

Category: `fmri-analysis` · Domain: `fmri-analysis` · Version `0.1`

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
   Study4 Pearson r (per condition) + Study5 AUC (per site), aggregates to
   `score = 0.5·study4_score + 0.5·study5_score`.
5. Emits 9 keys between `>>>>> BPB_SCORES` / `<<<<< BPB_SCORES` sentinels.

The labels never enter the agent workspace. See `checks/README.md`.

## Data (`data.lock`)

Four content-addressed entries:

| Name | Size | Where it lands |
|---|---|---|
| `study3_train.mat` | 954 MB | `public_data/whole_participants/FC_and_pain/` (via `env/setup.sh` symlink) |
| `public_support.tar.zst` | 12 MB | `public_data/atlas/` + `public_data/example_participant/` (untarred) |
| `private_features.tar.zst` | 75 MB | `$BPB_TOPS_PRIVATE_EVAL_DIR/features/` (scorer only) |
| `private_labels.tar.zst` | 1.9 KB | `$BPB_TOPS_PRIVATE_EVAL_DIR/labels/` (scorer only) |

All four entries are pinned to HF commit shas
(`Tasks-Data-Public@5be1911c…`, `Tasks-Data-Private@03674af4…`). The private
bundle lives in a **gated** HF dataset that requires `HF_TOKEN` — set it in
the scorer/runner environment; the BPB `hf://` fetcher forwards it as a
Bearer token and never persists it. Never fetch from `main`; a moving branch
would silently drift the data version.

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

- **SUT adapter**: BPB runner doesn't yet auto-run `env/setup.sh`; today a
  wrapper needs to invoke it before spinning up the agent. When the SUT
  adapter lands, this task will benefit automatically (no changes here).
- **Automated calibration**: `checks/output_schema.json` describes the raw
  metric contract but there's no per-condition tolerance table baked into
  the grader — a real signature's `score` distribution should stabilize
  once the first few reference runs land.
