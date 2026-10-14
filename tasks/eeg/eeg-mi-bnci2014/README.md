# BCI-IV-2a native motor-imagery classification

[Task collection](../../../README.md#task-suite) · [EEG tasks](../README.md) · [Data lock](data.lock)

This task classifies four-second BCI-IV-2a EEG windows into four source-defined motor-imagery classes. It retains the native subject grouping from the frozen AgentEEGBench protocol. It is not the legacy `bciciv-2a` task, which fits session T and scores session E per subject.

> [!NOTE]
> **Agent benchmark results: not yet available.**

## Task at a glance

| Field | Details |
| --- | --- |
| Task ID | `eeg-mi-bnci2014` |
| Scientific data | `motor_imagery/tangermann2012` · BCI-IV-2a |
| EEG input | 22 channels · 120 Hz · 4 s · `[22, 480]` samples |
| Public windows | 2,880 train · 1,152 validation |
| Native split | Subject-grouped · distinct from the legacy session T/E protocol |
| Output | 4 native classes · normalized probabilities `[B, 4]` |
| Metric | Public balanced accuracy (maximize) · task-specific scorer |

## Run this task

From the repository root, fetch and prepare the public data:

```sh
node dist/cli.js fetch eeg-mi-bnci2014 --public
node dist/cli.js prepare eeg-mi-bnci2014 --workspace /absolute/new-workspace
```

`data.lock` pins the two public arrays to an immutable Hugging Face revision. The fetch command checks their size and SHA-256. Data bodies stay outside Git.

For public scoring, use the host NumPy environment and the pinned inference image. The [reference workflow](#reference-workflow) below gives the exact setup commands.

## Submission and evaluation

Submit `report.md` and one chosen method in `submission/seed-0`, `seed-1`, and `seed-2`. Each seed directory must contain `model.py`, `config.json`, and `weights.safetensors`. The three seeds form one submission, not three research episodes.

Each model reloads its own saved weights and returns normalized class probabilities. The task limits parameters and saved numerical state to 10 million elements each. The scorer keeps validation labels outside isolated inference containers. It copies only required files and ignores extra submitted files.

The scorer writes `eeg-public-validation.json` with hashes and per-seed balanced accuracy. Empty, malformed, or oversized submissions fail without a score. This entry has no private Test binding, and `--official` is rejected. Research time and token budgets are unset. Each inference container has a two-minute cap, 2 CPUs, 4 GiB of memory, no network, and read-only inputs.

## Reference workflow

The included `solution/reference.py` fits one fixed CPU ridge model per seed on train data only. Its deterministic states are equal. This implementation checks the public path. It is not an Agent benchmark result.

The task environment uses Python 3.12, NumPy 2.2.6, PyTorch 2.7.1, and safetensors 0.5.3. The trusted host scorer supports Python 3.11–3.13 with NumPy 2.2.6. Submitted Python runs in the container, not in the host scorer environment.

<details>
<summary>Reference setup and execution commands</summary>

```sh
export BPB_EEG_PUBLIC_DATA_DIR="/absolute/new-workspace/public_data"
docker build -t bpb-eeg-reference:local tasks/eeg/eeg-mi-bnci2014/env
export BPB_EEG_IMAGE=$(docker image inspect --format '{{.Id}}' bpb-eeg-reference:local)
bash tasks/eeg/eeg-mi-bnci2014/env/setup-python.sh
export BPB_EEG_PYTHON="$PWD/.cache/eeg/host-venv/bin/python"

mkdir -p .cache/eeg/run/artifacts
docker run --rm --network none --cpus 2 --memory 4g \
  -v "$PWD/tasks/eeg/eeg-mi-bnci2014/solution:/solution:ro" \
  -v "$BPB_EEG_PUBLIC_DATA_DIR:/data:ro" \
  -v "$PWD/.cache/eeg/run:/run" "$BPB_EEG_IMAGE" \
  python /solution/reference.py --data /data --output /run/artifacts
cp tasks/eeg/eeg-mi-bnci2014/solution/meta.example.json .cache/eeg/run/meta.json

bp-bench score <run-dir> --isolation docker --inference-image "$BPB_EEG_IMAGE"
```

Run `checks/check.sh` from the run directory with `BPB_EEG_PYTHON` set.

</details>

## Provenance and scope

The frozen source task version is `full-autonomous-20260918-v1`. Its original public task-spec SHA-256 is `dadff50d8a6dbaf4569ec1248383045bb1b4782411df29bdf4e06d26da9e58da`. The pinned scientific source checkout is `a8092dc10956038e445ff0e07f9c0c7e03a10d36`. `contract.json` retains the native label mapping and both public array hashes.

AgentEEGBench remains a separate research project. Its source records do not become BrainPilotBench Agent results or private Test acceptance.
