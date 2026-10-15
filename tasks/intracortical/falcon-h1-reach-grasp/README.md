# H1: attempted reach and grasp

A human participant watched a virtual arm and attempted arm and grasp movements.
Utah arrays recorded threshold crossings in motor cortex.
The targets are seven commanded velocity components, not measured arm movement.
Read the [FALCON dataset description](https://snel-repo.github.io/falcon/datasets.html)
and the [native loader](https://github.com/snel-repo/falcon-challenge/blob/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/dataloaders.py#L93-L106).

> [!NOTE]
> H1 is runnable as task version <code>0.1-public-validation-stream</code>.
> A real CLI check scored public Valid successfully.
> Agent benchmark results are still pending.
> The reference score below is not an Agent result or an official FALCON score.

## Task at a glance

| Field | Value |
|---|---|
| Task ID | <code>falcon-h1-reach-grasp</code> |
| Task version | <code>0.1-public-validation-stream</code> |
| Task scoring profile | <code>bpb-h1-public-validation-stream-v1</code> |
| Scientific source profile | <code>bpb-falcon-public-derived-cross-session-zs-v1</code> |
| Primary metric | <code>R2_variance_weighted</code>, higher is better |
| Hardware | CPU. GPU is not required. |
| Agent network access | Disabled |

The scientific source profile and date split remain in [protocol.json](protocol.json).
The task version defines the streaming model interface and public Valid scorer.
DANDI <code>000954</code> is a draft snapshot.
The [asset manifest](../_preparation/assets.manifest.json) and [data.lock](data.lock) bind source assets.
The source code uses FALCON commit [770c9b9](https://github.com/snel-repo/falcon-challenge/tree/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f).

| Role | Source date IDs | Files |
|---|---|---:|
| Train | <code>19250101</code>, <code>19250108</code>, <code>19250113</code>, <code>19250115</code>, <code>19250119</code> | 11 |
| Valid | <code>19250120</code> | 2 |
| Evaluator-only Test | <code>19250126</code>, <code>19250127</code>, <code>19250129</code>, <code>19250202</code>, <code>19250203</code>, <code>19250206</code>, <code>19250209</code> | 14 |

These identifiers follow the released source files.
All files with one date ID stay in the same role: five Train dates, one Valid date, and seven Test dates.

The source supplies 13 public Train and Valid NWB files (69,754,804 bytes).
An owner-only evaluator set contains 14 more NWB files.
The DANDI record lists CC BY 4.0 and Open Access, but its description also prohibits redistribution under a Data Use Agreement.
BrainPilotBench does not mirror H1 source or derived data.
The task remains runnable after a maintainer downloads the source and builds the local arrays.
Before downloading, each user must read and comply with the agreement at the [DANDI source record](https://dandiarchive.org/dandiset/000954/draft).
Automated downloads do not waive the source terms.

## Input and submission

The task setup copies 54 files to <code>public_data/</code>: two manifests and 52 Train and Valid arrays.
It includes Train and Valid labels. It stages no raw NWB files, Test inputs or labels, or owner receipts.

| Item | Contract |
|---|---|
| Stored neural input | <code>uint8[T,176]</code>, one bin per 20 ms |
| Model input | <code>float32[176]</code>, one current bin per call |
| Targets | <code>float64[T,7]</code>. The trusted scorer keeps them from the model. |
| Scored bins | Bins selected by <code>mask.npy</code> |
| Trial marker | <code>trial_start: bool</code> marks a trial change before the current bin |
| First marker | <code>False</code> |
| Model output | Finite <code>float32[7]</code> |
| Submission files | <code>model.py</code>, <code>config.json</code>, <code>weights.safetensors</code> |
| Limits | 10M parameters and 10M saved numeric elements |

Implement <code>Model(config)</code> as a <code>torch.nn.Module</code>.
Implement <code>reset()</code> so that it clears history and returns <code>None</code> at each file boundary.
Implement <code>forward(x, trial_start=False)</code> for one current input bin.
Keep transient history in ordinary Python attributes.
Keep registered parameters and buffers fixed during inference.
The scorer ignores extra submission files.

## Prepare public data

H1 source and derived arrays are not part of a public data package.
Use the original DANDI source only after you read and comply with its Data Use Agreement.
The setup below downloads the original source for local preparation. It does not copy H1 data to a BrainPilotBench mirror.

The preparation tools require Python 3.12 and the pinned packages below.
Use a source checkout after <code>npm ci</code> and <code>npm run build</code>.
Replace the example paths with your own directories outside Git checkouts.

    BPB_CACHE_ROOT=/path/outside-git/h1-source-cache \
      node dist/cli.js fetch falcon-h1-reach-grasp --public

    python3.12 -m venv /path/to/h1-host
    /path/to/h1-host/bin/python -m pip install \
      -r tasks/intracortical/falcon-h1-reach-grasp/env/requirements.txt

The content cache root is <code>BPB_CACHE_ROOT</code> when set.
Otherwise, the CLI uses <code>$XDG_CACHE_HOME/brainpilot-bench</code> or <code>~/.cache/brainpilot-bench</code>.
Set <code>BPB_H1_CONTENT_CACHE_ROOT</code> to that same cache root.
Then export and stage the public arrays outside every Git checkout:

    env \
      BPB_H1_CONTENT_CACHE_ROOT=/path/outside-git/h1-source-cache \
      BPB_H1_DERIVED_ROOT=/path/outside-git/h1-derived \
      BPB_H1_STAGE_DIR=/path/outside-git/h1-public \
      BPB_H1_PYTHON=/path/to/h1-host/bin/python \
      bash tasks/intracortical/falcon-h1-reach-grasp/env/setup.sh

The stage path must be an ordinary directory outside every Git checkout.
The setup script copies only the 54 Train and Valid files.
The script clears its source variables in its child process.
It cannot clear variables from its calling shell.
Run an Agent in an allowlisted environment that omits source, cache, and evaluator paths.
Block network access during Agent research.

## Run and score

Use the [manual collection workflow](../../../README.md#evaluate-your-agent).
Pass the staged public root and host Python to the CLI setup and scoring commands:

    env \
      BPB_H1_DATA_DIR=/path/outside-git/h1-public \
      BPB_H1_PYTHON=/path/to/h1-host/bin/python \
      node dist/cli.js run falcon-h1-reach-grasp --adapter manual --agent my-agent@1 \
      --workspace /path/outside-git/h1-agent-workspace

Run the Agent in the workspace that the CLI prints.
Then run the printed resume command.
The bundle contains <code>meta.json</code> and <code>artifacts/submission/</code>.
The metadata must record <code>taskId: falcon-h1-reach-grasp</code> and the exact <code>taskVersion</code>.
The same workflow collects and verifies the versioned bundle after the Agent finishes.

Build the local inference image from the pinned task files:

    docker build -t bpb-h1-inference:local tasks/intracortical/falcon-h1-reach-grasp/checks
    IMAGE_ID=$(docker image inspect --format '{{.Id}}' bpb-h1-inference:local)

Verify the bundle after the Agent process stops.
Then score public Valid:

    env BPB_H1_DATA_DIR=/path/outside-git/h1-public \
      BPB_H1_PYTHON=/path/to/h1-host/bin/python \
      node dist/cli.js submit verify /path/to/submission-bundle

    env BPB_H1_DATA_DIR=/path/outside-git/h1-public \
      BPB_H1_PYTHON=/path/to/h1-host/bin/python \
      node dist/cli.js score /path/to/submission-bundle --isolation docker --inference-image "$IMAGE_ID"

The Docker image uses Python 3.12, NumPy 2.2.6, PyTorch 2.7.1, and safetensors 0.5.3.
Each file has a 10-minute worker limit.
Full Valid scoring has a 30-minute outer limit.
The local image passed checks on macOS arm64 and Linux arm64.
No amd64 or GPU validation is recorded.

The trusted host checks <code>config.json</code> and the safetensors state without importing <code>model.py</code>.
The worker receives one input vector and its <code>trial_start</code> value at a time.
It does not mount complete arrays, labels, masks, or the task repository.
The worker checks that registered state matches the saved weights and remains unchanged.
These checks do not prove that arbitrary Python follows every scientific rule.

## Reference result

The tracked [reference script](solution/solution.sh) builds a fixed Ridge model from one Train file.
It does not read Valid labels or Test data.
The real CLI reference check used both Valid runs.
It received 23,503 bins and scored 22,873 mask-selected bins.

The recorded <code>R2_variance_weighted</code> score is <code>-0.08090428869132338</code>.
It matches the independent float64 calculation within floating-point tolerance.
This result is a single fixed reference check.
It is not an Agent benchmark, a three-seed result, or an official FALCON score.
For each date, the scorer joins runs in recording order and computes variance-weighted R².
The final score gives equal weight to each date.

## Owner Test

The converted Test data passed trusted shape and hash checks.
The fixed reference later passed one owner Test interface check using its pre-frozen artifact.
That separate owner report is not a public Valid result or an Agent benchmark score.
No Test result selected a model, hyperparameter, or split.
The Test source is public.
This workflow separates scoring roles, not source access.

Use a separate maintainer workflow for Test.
First freeze the submission outside the Agent workspace:

    /path/to/h1-host/bin/python tasks/intracortical/falcon-h1-reach-grasp/checks/freeze_submission.py \
      --artifacts /path/to/submission-bundle/artifacts \
      --output /path/to/owner/h1-frozen-artifact.json

Then call the task scorer with the owner-only Test manifest:

    /path/to/h1-host/bin/python tasks/intracortical/falcon-h1-reach-grasp/checks/score.py \
      --task tasks/intracortical/falcon-h1-reach-grasp \
      --artifacts /path/to/submission-bundle/artifacts \
      --data-manifest /path/to/evaluator/test/manifest.json \
      --image "$IMAGE_ID" \
      --role test --owner-test \
      --frozen-artifact-manifest /path/to/owner/h1-frozen-artifact.json

This owner workflow prints a separate JSON report and emits no <code>BPB_SCORES</code> block.
The public check rejects official scoring and owner Test flags.
The generic CLI <code>--official</code> route does not apply to this derived profile.
