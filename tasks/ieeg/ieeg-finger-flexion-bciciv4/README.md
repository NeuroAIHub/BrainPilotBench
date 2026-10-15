# BCI Competition IV Dataset 4: finger flexion

Predict continuous finger movements from real ECoG recordings in three participants. Task version `0.1-public-validation-offline` provides a chronological public-validation split and a container-isolated submission interface.

> [!IMPORTANT]
> No Agent benchmark result is available for this task. A fixed ridge reference passed local data preparation, container scoring, and CLI checks. These checks verify the workflow, not scientific performance or an official competition result.

The source has 400 seconds of labeled ECoG and 200 seconds of evaluation ECoG per subject. Subjects 1, 2, and 3 have 62, 48, and 64 ECoG channels, respectively. The output has five finger-flexion values at 1000 Hz. The fourth value is the ring finger.

## Source and citation

Read the [competition page](https://www.bbci.de/competition/iv/) and [Dataset 4 description](https://www.bbci.de/competition/iv/desc_4.pdf) before download. The download page requests attribution to the recording groups and a paper citation for publications that analyze the data. It also requests notification of those publications. The description asks users to cite Schalk et al., *Decoding Two-Dimensional Movement Trajectories Using Electrocorticographic Signals in Humans*, Journal of Neural Engineering 4:264–275 (2007). This repository does not assert redistribution permission.

## Download and inspect the source

Create an isolated Python environment and install the pinned dependencies:

```sh
python3 -m venv .cache/bciciv4-venv
.cache/bciciv4-venv/bin/python -m pip install -r tasks/ieeg/ieeg-finger-flexion-bciciv4/env/requirements.txt
```

Print the download and split plan without network access or file writes:

```sh
.cache/bciciv4-venv/bin/python tasks/ieeg/ieeg-finger-flexion-bciciv4/env/prepare.py \
  --plan --cache-dir .cache/invasive-preparation-20261014/bci
```

Then run the preparation script with an explicit source-terms acknowledgment:

```sh
.cache/bciciv4-venv/bin/python tasks/ieeg/ieeg-finger-flexion-bciciv4/env/prepare.py \
  --accept-source-terms --download-only \
  --cache-dir .cache/invasive-preparation-20261014/bci
```

The script downloads the official ZIP only when the acknowledgment flag is present. The official ZIP has 206,367,150 bytes and SHA-256 `cf734300ad415f81350b75d1606fea42d9e552543fb42b0a8c09754ea522cbc6`. Download-only mode reads the ZIP as opaque bytes for verification; it does not parse MATLAB variables or write arrays. Interrupted transfers retain a prefix-hash/ETag receipt and resume through exact byte ranges. Changed ETags or a bad final hash fail closed. Keep source archives and arrays outside Git.

The current public exporter below reads only `train_data` and `train_dg`. It does not parse `test_data` or fetch later-published evaluation labels. Do not use those labels for Agent model selection. The boundary isolates a public source; it does not make its original labels private.

The cache directory must be a named directory below this repository's `.cache` directory. The script rejects symlink paths and existing output directories. It does not overwrite local arrays.

## Split and score

The source's first 400,000 samples are labeled. Train uses `[0,319000)` and Valid uses `[321000,400000)`, leaving a 2,000-sample boundary guard. Split before filtering or feature extraction. Fit learned transformations on Train only, and process each role independently. This is offline inference: a decoder may read the full current participant interval. It cannot read another role or update fitted state. The guard removes immediate neighbors; it does not prove independence between recordings or participants.

The original final 200,000 samples remain the evaluation input in the source protocol. They are not part of this preparation output. The score uses Pearson `r` for thumb, index, middle, and little finger for each subject. It is the arithmetic mean of 12 correlations. Predictions still have five columns. The fourth column contains ring finger. A constant or nonfinite scored trajectory is invalid.

The original competition used all 400 labeled seconds for training. Our smaller Train split makes the protocols different. All three participants occur in every role; this task does not measure transfer to new people.

## Historical one-participant preparation check

The fixed reference reads only the prepared `sub1` train and validation arrays. It uses independent, nonoverlapping 100 ms ECoG windows. It calculates log power, standardizes features on training data, and fits ridge regression with `alpha=1`. The target for each training window is mean finger flexion. It repeats each window prediction across its 100 samples. This is an offline interface check, not a real-time decoder.

To reproduce this historical check, first run `env/prepare.py` without `--download-only` in a new cache directory. That legacy mode creates its own Train/Valid output. Then run:

```sh
.cache/bciciv4-venv/bin/python tasks/ieeg/ieeg-finger-flexion-bciciv4/examples/reference.py \
  --cache-dir .cache/invasive-preparation-20261014/bci
```

The script writes a model, 79,000-by-5 validation predictions, and a receipt below the ignored cache. The receipt records the source, protocol, scripts, packages, and four scored correlations. This result uses one subject and a local validation split. It is not the official three-subject score or an Agent result.

The pinned local reference run gave a four-finger mean Pearson `r` of 0.0833669 for `sub1` validation. The individual values were 0.0381250, 0.1124480, 0.0885496, and 0.0943450 for thumb, index, middle, and little finger. These weak values are an interface check only.

## Current model interface

Submit `submission/model.py`, `submission/config.json`, and `submission/weights.safetensors`.
`Model(config)` must return a `torch.nn.Module`.
Its `forward(x, subject_id)` receives `float32[T,C]` and `sub1`, `sub2`, or `sub3`.
Return finite `float32[T,5]` in thumb, index, middle, ring, and little-finger order.
Limit saved and registered tensor state to 10 million elements. Registered state must stay fixed during inference.

Each participant runs in a fresh, read-only, non-root Docker container with no network.
Only the three submission files and the current input array are mounted.
Labels, other recordings, source archives, and the repository remain outside the container.
The trusted host checks submitted state without importing submitted Python.
Each worker has two CPUs, 4 GB RAM, and a five-minute limit.
Registered-state checks do not prove compliance by arbitrary Python.

The `pearson_r` metric averages twelve equally weighted correlations.
It excludes the ring finger, but all five output columns must be finite.
Constant scored trajectories are invalid; negative correlations remain valid scores.
The public CLI scores Valid only.

## Export, run, and score

After the source download above, create the current manifest-bound export outside Git:

```sh
.cache/bciciv4-venv/bin/python tasks/ieeg/ieeg-finger-flexion-bciciv4/env/export_bci.py \
  --archive .cache/invasive-preparation-20261014/bci/BCICIV_4_mat.zip \
  --output /path/outside-git/bciciv4-derived
```

This command does not read original Test inputs or labels.
It widens native int16 inputs to int32 without loss and records the original dtypes.
The export builds in a sibling temporary directory and publishes only after completion.
A failed export leaves the final destination absent, so the same command can be retried.
`contract.json` binds the role manifests; `data.lock` binds their exact files.
Do not regenerate the contract to accept changed sources.

Start the normal manual workflow:

```sh
env BPB_BCI_DATA_DIR=/path/outside-git/bciciv4-derived/public \
  BPB_BCI_PYTHON=/absolute/path/to/.cache/bciciv4-venv/bin/python \
  node dist/cli.js run ieeg-finger-flexion-bciciv4 --adapter manual --agent my-agent@1 \
  --workspace /path/outside-git/bciciv4-workspace
```

Setup atomically stages 12 Train/Valid arrays and two manifests.
Run the Agent there, then use the printed resume command to collect its submission.
The external Agent environment must block network access and omit owner paths, credentials, and evaluator caches.
Inference isolation does not supply that separate training-environment boundary.

Build the pinned inference environment and score a completed bundle:

```sh
docker build -t bpb-bciciv4-inference:local tasks/ieeg/ieeg-finger-flexion-bciciv4/checks
IMAGE_ID=$(docker image inspect --format '{{.Id}}' bpb-bciciv4-inference:local)
node dist/cli.js submit verify /path/to/submission-bundle
env BPB_BCI_DATA_DIR=/path/outside-git/bciciv4-derived/public \
  BPB_BCI_PYTHON=/absolute/path/to/.cache/bciciv4-venv/bin/python \
  node dist/cli.js score /path/to/submission-bundle --isolation docker --inference-image "$IMAGE_ID"
```

For optional content-cache verification, set `BPB_LOCAL_DATA_ROOT` to the derived root and use a public-only `BPB_CACHE_ROOT`.
Run `bp-bench fetch ieeg-finger-flexion-bciciv4 --public`, then unset `BPB_LOCAL_DATA_ROOT` before Agent setup.
No new data package has been uploaded.

## Current reference and owner Test

`examples/train_reference.py` fits one fixed ridge head per participant using Train only.
It uses nonoverlapping 100 ms log-power windows, Train-only standardization, and `alpha=1`.
The three-participant public Valid score was **0.1202214104** on October 14, 2026.
The local check used Python 3.12, NumPy 2.2.6, PyTorch 2.7.1, and safetensors 0.5.3 on Linux/arm64 Docker.
It does not establish GPU or amd64 compatibility.

The official Test labels are linked from the [competition results](https://www.bbci.de/competition/iv/results/index.html).
An owner can download the pinned label ZIP and pass `--labels /owner/path/true_labels.zip` to `env/export_bci.py` with a new output directory.
That creates an owner-only `evaluator/test` tree, never part of Agent staging.

Freeze the completed artifact before Test, without reading evaluation data:

```sh
python tasks/ieeg/ieeg-finger-flexion-bciciv4/checks/evaluate.py \
  --artifacts /path/to/submission-bundle/artifacts --freeze-to /owner/path/frozen.json
python tasks/ieeg/ieeg-finger-flexion-bciciv4/checks/evaluate.py \
  --artifacts /path/to/submission-bundle/artifacts --data /owner/path/derived/evaluator/test \
  --role test --owner-test --frozen /owner/path/frozen.json --image "$IMAGE_ID"
```

The owner entry returns a separate JSON report, not public leaderboard metrics.
The fixed reference passed one such functional check, with no Test-based model or split selection.
Public-origin Test data are isolated at execution time; the source labels are not secret.
