# Age Prediction from Structural MRI

[BrainPilotBench v1](../../../README.md#task-suite) · [Data lock](data.lock) · [Task specification](task.yaml)

The agent develops a model that predicts chronological age from T1-weighted brain MRI.
Model development uses public images and age labels. Evaluation uses a separate
set of held-out subjects.

> [!NOTE]
> **Agent benchmark results: not yet available.**
> Public data and evaluation code are available. The reference implementation checks below are separate from agent benchmark results.

## Task at a glance

| Field | Details |
|---|---|
| Task ID | `brain-age-mri` |
| Task version | `0.1-candidate` |
| Public data | MRI scans and chronological ages for 449 subjects |
| Submission | A saved model, inference code, training code/configuration, public validation predictions, and a report |
| Primary metric | Mean absolute error in years (`test_mae`), lower is better |
| Evaluation | 112 held-out subjects with evaluator-controlled age labels |

Pearson *r*, R², and a derived 0–1 `score` are additional diagnostics.
They do not replace MAE as the primary metric.

## Data and roles

`data.lock` pins both complete ZIPs by bytes and SHA-256.
The public `agent_data.zip` uses an immutable Hugging Face download URL.
Only the private `evaluator_data.zip` retains a `local://` URI beneath `BPB_LOCAL_DATA_ROOT`.
The public ZIP contains images, `subjects.csv`, and `ages.csv`; the evaluator ZIP contains
images, `subjects.csv`, and `labels/true_ages.csv`.

From the repository root, fetch and prepare the public archive:

```sh
node dist/cli.js fetch brain-age-mri --public
node dist/cli.js prepare brain-age-mri --workspace /absolute/new-agent-workspace
bash tasks/mri/brain-age-mri/env/setup-python.sh
```

For private evaluation, use a separate trusted cache and process.
Set `BPB_LOCAL_DATA_ROOT` to the private archive directory before `bp-bench fetch brain-age-mri --private`.
Unset it before starting an Agent. Public preparation does not require the private archive.

`bp-bench fetch` uses the content-addressed cache. `env/setup.sh` stages an
archive from that cache by default. For local preparation, the explicit
`BPB_BRAIN_AGE_AGENT_ARCHIVE` or `BPB_BRAIN_AGE_EVALUATOR_ARCHIVE` environment
variable may point directly to the original ZIP. The setup script verifies the
whole-archive hash and size, rejects unsafe ZIP paths and links, checks subject
counts and the public/evaluator file shape, and writes a `PREPARED.json` receipt.
It does not repeat the prior full voxel-level audit.

The Agent role is the default and stages only public data into `public_data/`
in the Agent workspace. Run evaluator staging in a different trusted process:

```sh
bash tasks/mri/brain-age-mri/env/setup.sh --role evaluator \
  --destination /absolute/evaluator-only/brain-age-data
```

Keep the evaluator archive, extracted ages, prediction files, and score output
outside the Agent workspace. Never mount the full contribution ZIP into an
Agent container. Private evaluator distribution and inference-image publication remain separate release steps.

## Submission contract

Required outputs are `scripts/predict.py`, a frozen model and
`models/model_manifest.json`, training code/configuration, public validation
predictions, and `report.md`. `predict.py` accepts `--input-dir`,
`--input-manifest`, `--model-dir`, and `--output-csv`. Its CSV has exactly
`subject_id,predicted_age`, one finite age per input subject, with no duplicate
or missing ID. The Agent may choose its own public-only training and validation
method. A GPU is optional; the included low-cost reference uses CPU only.

The trusted scorer in `checks/evaluate_external.py` checks the submitted files,
copies only the script/model directories, and runs submitted inference in a
networkless, non-root, read-only Docker container. It mounts hidden images and
an ID/path manifest; hidden ages remain in the trusted parent. The scorer
computes all metrics from those ages after inference exits. A constant predictor
has undefined Pearson correlation: the flat payload uses
`pearson_r_defined=0` and a numeric placeholder of 0 for `test_pearson_r`;
`evaluation.json` records the explicit undefined status. Scorer errors emit no
`BPB_SCORES` sentinel and are unscored, never a scientific zero.

Official scoring requires an immutable `repo@sha256:<digest>` inference image.
Build the local CPU image from the repository root:

```sh
docker build -t bpb-brain-age-inference:local \
  -f tasks/mri/brain-age-mri/env/Dockerfile.inference tasks/mri/brain-age-mri
docker image inspect bpb-brain-age-inference:local --format '{{json .RepoDigests}}'
```

Use the immutable repository digest reported by Docker. If the local builder
does not expose one, prepare the image through the approved image-distribution
process; do not substitute a mutable tag. Image publication is a separate release
action. Then set
`BPB_INFERENCE_IMAGE`, `BPB_BRAIN_AGE_EVALUATOR_DIR`,
`BPB_BRAIN_AGE_SCORE_DIR`, and `BPB_BRAIN_AGE_PYTHON` in the evaluator process.
Score an evaluator-controlled copy of the frozen bundle with `bp-bench score
<bundle> --official --isolation docker --inference-image <repo@sha256:digest>`.
The generic CLI writes `scores.json` into the supplied bundle, so do not use
the public reference directory as the long-term score store. The research
timeout is 180 minutes; the submitted
inference limit is 30 minutes. Keep these limits separate.

<a id="maintainer-reference-and-current-evidence"></a>

## Reference implementation checks

`reference/generate_reference.py` trains a deliberately coarse voxel/Ridge
baseline on public subjects only. Its fixed low-cost configuration is an 8³
resampling grid, two shuffled subject folds, `alpha=100`, seed 42, and two CPU
threads. It writes a frozen submission plus public CV and provenance receipts;
it never loads hidden images or ages. Use a new output directory:

```sh
python tasks/mri/brain-age-mri/reference/generate_reference.py \
  --agent-data /absolute/public-data --output-dir /absolute/new-reference \
  --feature-shape 8 8 8 --folds 2 --alphas 100 --threads 2
```

The reference has no skull stripping or anatomical registration and is not a
state-of-the-art brain-age model. The local 2026-10-12 run used all 449 public
subjects for training, then scored the frozen model once on 112 hidden subjects
in Docker. Exact metrics, digests, timing, limitations, and private evaluator
receipts live only in `.cache/brain-age/evidence.json`; private labels and
results are not part of this task directory.

<details>
<summary>Source and integration record</summary>

This task is a candidate, not a published BrainPilotBench release. The
contributing colleagues' assurance about source, permission, subject mapping,
and split integrity was accepted by the owner. That assurance is recorded as
contributor evidence, not as independent provenance verification.
The task version remains `0.1-candidate`. Public data publication does not change
its scientific protocol or establish an agent benchmark result.

</details>
