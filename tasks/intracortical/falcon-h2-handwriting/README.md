# H2: attempted handwriting

A BrainGate2 participant attempted to write prompted English sentences while intracortical arrays recorded spike counts. The task decodes one sentence after each complete trial.

> [!NOTE]
> Agent benchmark results: not yet available. The fixed reference is an interface check, not an official FALCON score.

## Task at a glance

| Field | Task contract |
|---|---|
| Input | One current mask-selected `float32[192]` neural bin per call. Bins are 20 ms apart and mark trial starts. |
| Output | One UTF-8 sentence string of at most 2,048 bytes after each complete trial. |
| Split | 20 earlier recording dates for Train, one later held-in date for Valid, and five calibration dates for evaluator-only Test. |
| Metric | Word error rate (WER) per date, then the equal-weight date mean. Lower is better. Character error rate (CER) is secondary. |

The active [task entry](task.yaml) and [acceptance record](acceptance.json) describe the locally checked version.
Read the [FALCON paper](https://proceedings.neurips.cc/paper_files/paper/2024/hash/8c2e6bb15be1894b8fb4e0f9bcad1739-Abstract-Datasets_and_Benchmarks_Track.html) and [native loader](https://github.com/snel-repo/falcon-challenge/blob/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/dataloaders.py#L102-L113).

## Data and split

The [protocol](protocol.json) fixes 20 earlier recording dates for Train and one later held-in date for Valid.
Five public held-out calibration dates form evaluator-only Test.
The native minival copies are excluded.
The source is published DANDI `000950` version `0.241029.1403`.
The [asset manifest](../_preparation/assets.manifest.json) binds exact NWB sources. [data.lock](data.lock) binds hosted public Train/Valid files by size and SHA-256.
The [contract](contract.json) binds every derived file and complete-trial count.
The source code is fixed at [FALCON commit 770c9b9](https://github.com/snel-repo/falcon-challenge/tree/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f).

Train and Valid use separate public manifests and arrays.
Test arrays stay in a separate evaluator directory.
The source Test recordings are public. The role separation controls this task's evaluation workflow.

| Role | Dates | Complete trials | Neural bins |
|---|---:|---:|---:|
| Train | 20 | 647 | 1,397,554 |
| Valid | 1 | 24 | 43,929 |
| Evaluator-only Test | 5 | 15 | 22,712 |

All 26 frozen NWB files passed source SHA and native trial-table checks.
The native mask selected every bin in these calibration files.

Each run contains `x.npy` (`float32[T,192]`), `mask.npy` (`bool[T]`), `trial_end.npy` (`bool[T]`), and `labels.json`.
The exporter derives trial ends from native timestamp gaps above 21 ms and checks the NWB trial table.
Each end marker maps to one complete sentence cue.
Train and Valid include sentence labels. The inference worker receives no labels or mask.
The trusted host calls the model only for bins selected by the native mask.

## Model interface

Submit three files in `submission/`: `model.py`, `config.json`, and `weights.safetensors`.
Implement `Model(config)` as a `torch.nn.Module` with these methods:

```python
reset() -> None
observe(x: torch.Tensor, trial_start: bool = False) -> None
finish_trial() -> str
```

The scorer calls `reset()` at each source file boundary.
It gives `observe()` one current mask-selected `float32[192]` bin at a time.
The first bin of each complete trial has `trial_start=True`.
At the native trial end, it calls `finish_trial()` once and accepts a UTF-8 string of at most 2,048 bytes.
The worker sees no future bins in the current call.
The scorer keeps registered parameters and buffers fixed during inference.
Use ordinary attributes for transient history.
The trusted host limits saved numeric state to 10 million elements.
The worker limits parameters and all registered tensors, including nonpersistent buffers, to 10 million elements.
The registered-state check cannot prove that arbitrary Python follows every model policy.

## Prepare and run

The hosted Train/Valid files use the [unified public layout](../../../docs/invasive-task-preparation.md#prepare-one-public-task).
The CLI copies verified files to the workspace and gives `BPB_PUBLIC_DATA_ROOT` to setup.
Preparation passed from a verified existing public cache.
The [delivery acceptance](delivery-acceptance.json) binds the revised lock and setup to the [public delivery report](../../../reports/unified-public-delivery-20261015.json).
This delivery check did not rerun the fixed reference or owner Test.
The original-source route below remains available for a local rebuild.

Install the pinned trusted host packages with Python 3.12:

```bash
python3.12 -m venv /path/to/h2-host
/path/to/h2-host/bin/python -m pip install -r tasks/intracortical/falcon-h2-handwriting/env/requirements.txt
```

Prepare one workspace from the hosted public files:

```bash
BPB_H2_PYTHON=/path/to/h2-host/bin/python \
  node dist/cli.js prepare falcon-h2-handwriting --fetch \
  --workspace /path/outside-git/h2-agent
```

The setup stages Train and Valid in `/path/outside-git/h2-agent/public_data`.
For a local source rebuild, use the [source preparation tool](../_preparation/prepare.py) to fill a separate source root.
Then export and stage outside a Git checkout:

```bash
BPB_H2_SOURCE_ROOT=/path/outside-git/h2-source \
BPB_H2_DERIVED_ROOT=/path/outside-git/h2-derived \
BPB_H2_STAGE_DIR=/path/outside-git/h2-agent/public_data \
BPB_H2_PYTHON=/path/to/h2-host/bin/python \
bash tasks/intracortical/falcon-h2-handwriting/env/setup.sh
```

The setup script stages Train and Valid only.
It does not stage raw NWB files, Test arrays, the full contract, or trusted receipts.
Provide only the staged public directory to the Agent.
Remove source, cache, and evaluator paths from its environment and disable network access.

Use the [manual collection workflow](../../../README.md#evaluate-your-agent) for a runnable task entry.
Set `BPB_H2_PYTHON` to the trusted host interpreter for Agent preparation.
Set `BPB_H2_DATA_DIR` to `/path/outside-git/h2-agent/public_data` for scoring.
Build an inference image from `checks/Dockerfile` and pass its immutable image ID to the scorer.
The local CPU image uses Python 3.12, NumPy 2.2.6, PyTorch 2.7.1, and safetensors 0.5.3.
The worker runs without network access and mounts only the three staged submission files.

For each date, the scorer sums edit distances and target lengths across its complete trials.
It computes WER and CER for that date, then gives dates equal weight.
The public check scores Valid only.

## Fixed reference and owner Test

The [reference builder](solution/make_reference.py) reads only the first real Train file.
It selects the most frequent Train sentence from that file and uses it for every trial.
This low-information model checks the input, submission, and scoring path.
It does not establish useful decoding performance.
The contract-bound Valid check used all 24 complete trials and 43,929 bins.
It returned WER `1.008695652173913` and CER `0.8312559923298178`.
These values are fixed-reference development results, not Agent benchmark results.

The owner can export Test with `_sequence_shared/export.py --task h2 --access evaluator --allow-test-export`.
This trusted conversion reads Test cues but does not run a model.
Before an owner Test run, freeze the exact three submission files with `checks/freeze_submission.py`.
Then call `checks/score.py` with `--role test --owner-test`, the evaluator Test manifest, and the frozen-artifact path.
Set `--report-output` to a new JSON path outside Git.
The owner Test command writes that separate report and emits no public score block.
Neither public Valid nor owner Test is an official FALCON evaluation.
One owner Test functional pass used the same frozen reference artifact.
Its separate report remains outside Git and outside the public score block.
