# BCI-IV-2a: native subject-grouped protocol

This entry shares AgentEEGBench's frozen `motor_imagery/tangermann2012` task data.
The source version is `full-autonomous-20260918-v1`; its original public contract
SHA-256 is in `contract.json`. The 2,880 train and 1,152 validation windows retain
the native subject grouping, 22 channels, 120 Hz and four-second windows.

This is a different protocol from `tasks/eeg/bciciv-2a`: that task fits each
subject's session T and scores session E. Keep the two task IDs and their results
separate. This candidate reports **public validation only**, not private Test or
independent research acceptance. AgentEEGBench remains a separate research project.

## Prepare

Obtain the frozen public `train.npz` and `val.npz` from the task maintainer.
No stable public mirror is published yet. Both hashes are checked before use.
Data bodies stay outside Git. From the repository root:

```bash
export BPB_LOCAL_DATA_ROOT=/path/to/frozen-public-package
node dist/cli.js fetch eeg-mi-bnci2014 --public
unset BPB_LOCAL_DATA_ROOT
export BPB_EEG_PUBLIC_DATA_DIR=/path/to/frozen-public-package
mkdir -p .cache/eeg/workspace
(cd .cache/eeg/workspace && bash ../../../tasks/eeg/eeg-mi-bnci2014/env/setup.sh --role agent)
docker build -t bpb-eeg-reference:local tasks/eeg/eeg-mi-bnci2014/env
export BPB_EEG_IMAGE=$(docker image inspect --format '{{.Id}}' bpb-eeg-reference:local)
bash tasks/eeg/eeg-mi-bnci2014/env/setup-python.sh
export BPB_EEG_PYTHON="$PWD/.cache/eeg/host-venv/bin/python"
```

The task uses Python 3.12, NumPy 2.2.6, PyTorch 2.7.1 and safetensors 0.5.3.
Use the resolved image ID for inference. `solution/reference.py` fits one fixed
CPU ridge model per seed using train only. Its deterministic states are equal;
three seeds are one submission, not three research episodes.

```bash
mkdir -p .cache/eeg/run/artifacts
docker run --rm --network none --cpus 2 --memory 4g \
  -v "$PWD/tasks/eeg/eeg-mi-bnci2014/solution:/solution:ro" \
  -v "$BPB_EEG_PUBLIC_DATA_DIR:/data:ro" \
  -v "$PWD/.cache/eeg/run:/run" "$BPB_EEG_IMAGE" \
  python /solution/reference.py --data /data --output /run/artifacts
cp tasks/eeg/eeg-mi-bnci2014/solution/meta.example.json .cache/eeg/run/meta.json
```

Run `checks/check.sh` from the run directory with `BPB_EEG_PYTHON` set to a
Python interpreter with NumPy. It starts isolated inference containers and
scores all validation labels outside them. It writes
`eeg-public-validation.json` beside `artifacts/`, including hashes and per-seed
balanced accuracy. Empty, malformed or oversized submissions fail without a
score. Required files are copied; extra submitted files are not executed.

For an existing BPB submission bundle, use:

```bash
bp-bench score <run-dir> --isolation docker --inference-image "$BPB_EEG_IMAGE"
```

The host scorer environment supports Python 3.11–3.13 and NumPy 2.2.6; submitted
Python runs in the container, not that host environment. `--official` is rejected
because this entry has no private Test binding.
Research time and token budgets are unset; each inference container has a
two-minute cap, 2 CPUs, 4 GiB memory, no network and read-only inputs.
