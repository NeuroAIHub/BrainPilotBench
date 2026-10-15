# M2: finger-group velocity

M2 predicts two finger-group velocities from 96 intracortical channels.
The [protocol](protocol.json) fixes three Train dates, one Valid date, and four evaluator-only Test dates.
The [asset manifest](../_preparation/assets.manifest.json) binds 13 assets from DANDI `000953` draft.
These files total 15,792,196,664 bytes.
The [native loader](https://github.com/snel-repo/falcon-challenge/blob/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/dataloaders.py#L140-L157) uses velocity timestamps as 20 ms bin starts.
It marks trials at `searchsorted(velocity_timestamps, trial.start_time)`.

Status: **locally accepted public-validation task**, version `0.1-public-validation-stream`.
The [task entry](task.yaml) is active. [Acceptance evidence](acceptance.json) binds its critical files and fixed-reference checks.
The [contract](contract.json) binds all 13 source assets, selected ranges, and derived arrays.
The [data lock](data.lock) lists 30 public derived files and 25 evaluator files through `local://` paths.
No Agent result is recorded. The owner Test reference report stays outside Git.

## Data preparation

Use Python 3.12 with [trusted preparation requirements](env/requirements.txt).
Keep raw and derived roots outside Git checkouts.
The [selected-range exporter](../_regression_shared/selective_m2.py) reads only the arrays used by the pinned native loader.
It checks versioned DANDI metadata, the frozen ETag, `If-Match`, and each exact HTTP byte range.
It keeps every selected source range with a local SHA-256 receipt.
It writes `x.npy`, `y.npy`, `mask.npy`, and `trial_start.npy` for each source run.
Its evaluator mode reads Test labels only for trusted conversion and never runs a model.
The published whole-file raw SHA-256 remains unverified when this range path is used.

    python3 tasks/intracortical/_regression_shared/selective_m2.py prepare \
      --access public --output-root /path/to/m2-derived

    python3 tasks/intracortical/_regression_shared/selective_m2.py prepare \
      --access evaluator --allow-test-export --output-root /path/to/m2-derived

    python3 tasks/intracortical/_regression_shared/selective_m2.py assemble \
      --access public --output-root /path/to/m2-derived

    python3 tasks/intracortical/_regression_shared/selective_m2.py assemble \
      --access evaluator --allow-test-export --output-root /path/to/m2-derived

The assembler reconstructs each native array from the saved source ranges.
The checked-in contract is the authority for an existing task version.
The shared [contract builder](../_regression_shared/build_contract.py) is a maintainer tool for freezing a new definition, not a way to accept changed sources.
The source contract records which raw SHA values are published but not locally recomputed.
The selected extraction read 20,696,120 bytes across all 13 files.
The published full raw files total 15,792,196,664 bytes.
Each selected source can reproduce its four arrays from its saved ranges without network access.
The selected-range exporter is the standard rebuild path for this task.
A full raw NWB download is an optional source audit.

The local fetcher reads [data.lock](data.lock) from the derived root.
Set `BPB_LOCAL_DATA_ROOT` to that root for the maintainer fetch only.
Unset it before the Agent starts.
The public fetcher copied and verified all 30 public files from the derived root.
It copied 13,234,392 bytes and no evaluator file.

## Submission and scoring

The Agent sees only copied Train and Valid arrays in `public_data/`.
The [setup script](env/setup.sh) copies those arrays after it checks the frozen contract.
It rejects a Git checkout as the stage destination.
It does not copy raw NWB files or Test data.

Submit `submission/model.py`, `submission/config.json`, and `submission/weights.safetensors`.
`Model(config)` is a `torch.nn.Module`.
At each run boundary, `reset()` clears transient state and returns `None`.
Each `forward(x, trial_start=False)` call gets the current `float32[96]` bin and returns finite `float32[2]`.
The scorer keeps labels and masks on the host.
Its local Docker worker receives one input bin and trial marker at a time.
It receives no full array, label, mask, or repository mount.

The primary metric is native-mask, variance-weighted R² per date, then the equal-weight date mean.
Runs on the same date combine before scoring.
Negative R² remains a valid result.
Public Valid is for development.
The separate owner Test path requires a frozen submission and prints a separate JSON report.
This score is a BrainPilotBench public-derived profile, not an official FALCON score.

Run the [manual collection workflow](../../../README.md#evaluate-your-agent) with the public root:

    env BPB_M2_DATA_DIR=/path/to/m2-derived/public BPB_M2_PYTHON=/path/to/venv/bin/python \
      node dist/cli.js run falcon-m2-finger-velocity --adapter manual --agent my-agent@1 \
      --workspace /path/outside-git/m2-workspace

Use the printed resume command after the Agent finishes.
Build the inference image from `checks/Dockerfile` and resolve its immutable ID.
Then verify and score the resulting bundle:

    docker build -t bpb-m2-inference:local tasks/intracortical/falcon-m2-finger-velocity/checks
    IMAGE_ID=$(docker image inspect --format '{{.Id}}' bpb-m2-inference:local)
    node dist/cli.js submit verify /path/to/submission-bundle
    env BPB_M2_DATA_DIR=/path/to/m2-derived/public BPB_M2_PYTHON=/path/to/venv/bin/python \
      node dist/cli.js score /path/to/submission-bundle --isolation docker --inference-image "$IMAGE_ID"

The Agent's separate training environment must omit raw sources, evaluator roots, credentials, and network access.
The inference container does not establish that external training boundary.
The local checks used Linux/arm64 CPU containers; amd64 and GPU execution are not yet checked.

## Fixed reference check

The [reference script](solution/solution.sh) fitted one Ridge model on `m2-train-0001` only.
It did not read Valid labels or Test data during fitting.
The isolated Docker scorer processed all 17,782 Valid bins on 2020-10-28.
Its variance-weighted R² was `0.07600794957020907`.
An independent NumPy prediction and scikit-learn calculation gave `0.07600794873243939`.
The difference is within float32 inference rounding.
This check is one fixed reference, not an Agent score or an official FALCON result.
One frozen owner Test reference ran through the separate evaluator path.
Its score is not part of the public Valid result or an Agent benchmark.
