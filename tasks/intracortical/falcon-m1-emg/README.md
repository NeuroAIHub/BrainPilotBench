# M1-A: upper-limb EMG

M1-A predicts 16 preprocessed EMG signals from 64 intracortical channels.
The [protocol](protocol.json) fixes three Train dates, one Valid date, and three later evaluator-only Test dates.
The source is DANDI `000941` version `0.241029.1405`.
The [asset manifest](../_preparation/assets.manifest.json) binds its seven NWB files and source commit.
The [native loader](https://github.com/snel-repo/falcon-challenge/blob/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/dataloaders.py#L114-L139) uses EMG timestamps as 20 ms bin ends.
It marks trials at `searchsorted(emg_timestamps, trial.start_time)`.

Status: **locally accepted public-validation task**, version `0.1-public-validation-stream`.
The [task entry](task.yaml) is active. [Acceptance evidence](acceptance.json) binds its critical files and fixed-reference checks.
The [contract](contract.json) and [data lock](data.lock) bind all seven full-SHA-verified NWB sources and their derived arrays.
No Agent result is recorded. The owner Test reference report stays outside Git.

## Data preparation

Use Python 3.12 with [trusted preparation requirements](env/requirements.txt).
Keep raw and derived roots outside Git checkouts.
Download the four public source files through the pinned source tool:

    python3 tasks/intracortical/_preparation/prepare.py fetch \
      --task falcon-m1-emg --access public --all-selected \
      --dest /path/to/raw --limit-bytes 320000000

The shared [exporter](../_regression_shared/export.py) checks each raw SHA before it opens an NWB file.
It writes `x.npy`, `y.npy`, `mask.npy`, and `trial_start.npy` for each source run.
Its evaluator mode reads Test labels only for trusted conversion and never runs a model.

    python3 tasks/intracortical/_regression_shared/export.py \
      --task-id falcon-m1-emg --access public \
      --source-root /path/to/raw --output-root /path/to/m1-derived

Only the evaluator owner needs the three Test sources and their separate export:

    python3 tasks/intracortical/_preparation/prepare.py fetch \
      --task falcon-m1-emg --access evaluator --all-selected \
      --dest /path/to/raw --limit-bytes 20000000

    python3 tasks/intracortical/_regression_shared/export.py \
      --task-id falcon-m1-emg --access evaluator --allow-test-export \
      --source-root /path/to/raw --output-root /path/to/m1-derived

The checked-in contract is the authority for an existing task version.
The shared [contract builder](../_regression_shared/build_contract.py) is a maintainer tool for freezing a new definition, not a way to accept changed sources.
The seven source NWB files total 309,258,566 bytes.
The full byte count and SHA-256 were checked for every file.
The final export contains three Train runs, one Valid run, and three evaluator Test runs.

## Submission and scoring

The Agent sees only copied Train and Valid arrays in `public_data/`.
The [setup script](env/setup.sh) copies those arrays after it checks the frozen contract.
It rejects a Git checkout as the stage destination.
It does not copy raw NWB files or Test data.

Submit `submission/model.py`, `submission/config.json`, and `submission/weights.safetensors`.
`Model(config)` is a `torch.nn.Module`.
At each run boundary, `reset()` clears transient state and returns `None`.
Each `forward(x, trial_start=False)` call gets the current `float32[64]` bin and returns finite `float32[16]`.
The scorer keeps labels and masks on the host.
Its local Docker worker receives one input bin and trial marker at a time.
It receives no full array, label, mask, or repository mount.

The primary metric is native-mask, variance-weighted R² per date, then the equal-weight date mean.
Negative R² remains a valid result.
Public Valid is for development.
The separate owner Test path requires a frozen submission and prints a separate JSON report.
This score is a BrainPilotBench public-derived profile, not an official FALCON score.

Run the [manual collection workflow](../../../README.md#evaluate-your-agent) with the public root:

    env BPB_M1_DATA_DIR=/path/to/m1-derived/public BPB_M1_PYTHON=/path/to/venv/bin/python \
      node dist/cli.js run falcon-m1-emg --adapter manual --agent my-agent@1 \
      --workspace /path/outside-git/m1-workspace

Use the printed resume command after the Agent finishes.
Build the inference image from `checks/Dockerfile` and resolve its immutable ID.
Then verify and score the resulting bundle:

    docker build -t bpb-m1-inference:local tasks/intracortical/falcon-m1-emg/checks
    IMAGE_ID=$(docker image inspect --format '{{.Id}}' bpb-m1-inference:local)
    node dist/cli.js submit verify /path/to/submission-bundle
    env BPB_M1_DATA_DIR=/path/to/m1-derived/public BPB_M1_PYTHON=/path/to/venv/bin/python \
      node dist/cli.js score /path/to/submission-bundle --isolation docker --inference-image "$IMAGE_ID"

The Agent's separate training environment must omit raw sources, evaluator roots, credentials, and network access.
The inference container does not establish that external training boundary.
The local checks used Linux/arm64 CPU containers; amd64 and GPU execution are not yet checked.

## Fixed reference check

The [reference script](solution/solution.sh) fitted one Ridge model on `m1-train-0001` only.
It did not read Valid labels or Test data during fitting.
The isolated Docker scorer processed all 160,436 Valid bins on 2012-09-28.
The native mask selected 54,783 of those bins.
Its variance-weighted R² was `0.24162054935594146`.
An independent NumPy prediction and scikit-learn calculation gave `0.2416205530756615`.
The difference is within float32 inference rounding.
The exported Valid arrays also matched the pinned native loader exactly.
This check is one fixed reference, not an Agent score or an official FALCON result.
The same frozen reference passed one owner Test interface check.
Its negative Test result remains in the separate owner report; it did not trigger model or split selection.
