# Brain age from structural MRI — candidate task 0.1-candidate

Predict chronological age from anonymized T1-weighted structural MRI. The Agent
receives 449 public images and ages. A separate evaluator holds 112 images and
ages. `test_mae` (years, lower is better) is the primary metric. The scorer also
reports Pearson *r*, R², and a derived 0–1 `score`; the derived value does not
replace MAE in task ranking.

This task is a candidate, not a published BrainPilotBench release. The
contributing colleagues' assurance about source, permission, subject mapping,
and split integrity was accepted by the owner. That assurance is recorded as
contributor evidence, not as independent provenance verification.

## Data and roles

`data.lock` pins both complete ZIPs by bytes and SHA-256. Its `local://` URIs
resolve below `BPB_LOCAL_DATA_ROOT`, which must contain `agent_data.zip` and
`evaluator_data.zip`. There is no public distribution URL yet. The public ZIP
contains images, `subjects.csv`, and `ages.csv`; the evaluator ZIP contains
images, `subjects.csv`, and `labels/true_ages.csv`.

In a trusted preparation environment, set `BPB_LOCAL_DATA_ROOT` to the folder
holding the original, unchanged archives. Then run:

```sh
bp-bench fetch brain-age-mri --public
bp-bench fetch brain-age-mri --private   # evaluator only, in a separate cache/identity
bash tasks/mri/brain-age-mri/env/setup-python.sh
unset BPB_LOCAL_DATA_ROOT   # before starting an Agent; archives may include evaluator data
```

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
Agent container. The current local data URI and local Docker image must be
replaced or separately distributed before public release.

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

## Maintainer reference and current evidence

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
