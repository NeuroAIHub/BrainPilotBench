# B1: birdsong spectrogram

A zebra finch sang while a Neuropixels probe recorded 85 threshold-crossing channels.
The task predicts one vocalization spectrogram from each complete song motif.
It is not a human speech task.
The active [task entry](task.yaml) and [acceptance record](acceptance.json) describe the locally checked version.
Read the [FALCON paper](https://proceedings.neurips.cc/paper_files/paper/2024/hash/8c2e6bb15be1894b8fb4e0f9bcad1739-Abstract-Datasets_and_Benchmarks_Track.html), [native loader](https://github.com/snel-repo/falcon-challenge/blob/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/dataloaders.py#L159-L182), and [spectrogram scorer](https://github.com/snel-repo/falcon-challenge/blob/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/evaluator.py#L603-L668).

> [!NOTE]
> This is a BrainPilotBench public-data task profile, not an official FALCON score.
> Agent benchmark results are pending. The fixed reference is an interface check.

## Data and split

The [protocol](protocol.json) fixes two earlier recording dates for Train and the last held-in date for Valid.
Three public held-out calibration dates form evaluator-only Test.
The native minival copies are excluded.
DANDI `001046` is a draft asset snapshot.
The [asset manifest](../_preparation/assets.manifest.json) and [data.lock](data.lock) bind exact NWB assets by size and SHA-256.
The [contract](contract.json) binds every derived file and complete-motif count.
The source code is fixed at [FALCON commit 770c9b9](https://github.com/snel-repo/falcon-challenge/tree/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f).

Train and Valid use separate public manifests and arrays.
Test arrays stay in a separate evaluator directory.
The source Test recordings are public. The role separation controls this task's evaluation workflow.

| Role | Dates | Complete motifs | Neural samples |
|---|---:|---:|---:|
| Train | 2 | 40 | 1,080,000 |
| Valid | 1 | 8 | 216,000 |
| Evaluator-only Test | 3 | 9 | 243,000 |

All six frozen NWB files passed source SHA and native motif-table checks.
Each complete motif has a 700×158 native scoring mask.

Each run contains `x.npy` (`uint8[motifs,27000,85]`), `y.npy` (`float64[motifs,880,158]`), and `mask.npy`.
The neural input covers 900 ms at 30 kHz for each motif.
The exporter checks all neural sample boundaries against the NWB trial table.
Each native mask selects 700 time bins and 158 frequency bins.
Train and Valid include spectrogram targets. The inference worker receives no target or mask.

## Model interface

Submit three files in `submission/`: `model.py`, `config.json`, and `weights.safetensors`.
Implement `Model(config)` as a `torch.nn.Module` with this method:

```python
forward(neural: torch.Tensor) -> torch.Tensor
```

The scorer calls `forward()` once for each complete motif.
The argument has shape `float32[27000,85]`.
The result must be finite `float32[880,158]`.
The worker sees only the current motif's neural input.
It sees no future motifs, labels, masks, raw files, or task repository.
The scorer keeps registered parameters and buffers fixed during inference.
The trusted host limits saved numeric state to 10 million elements.
The worker limits parameters and all registered tensors, including nonpersistent buffers, to 10 million elements each.
The registered-state check cannot prove that arbitrary Python follows every model policy.

## Prepare and run

Install the pinned trusted host packages with Python 3.12:

```bash
python3.12 -m venv /path/to/b1-host
/path/to/b1-host/bin/python -m pip install -r tasks/intracortical/falcon-b1-birdsong/env/requirements.txt
```

Fetch the frozen public assets with the BrainPilotBench CLI:

```bash
BPB_CACHE_ROOT=/path/outside-git/b1-source-cache node dist/cli.js fetch falcon-b1-birdsong --public
```

Export and stage public data outside a Git checkout:

```bash
BPB_B1_CONTENT_CACHE_ROOT=/path/outside-git/b1-source-cache \
BPB_B1_DERIVED_ROOT=/path/outside-git/b1-derived \
BPB_B1_STAGE_DIR=/path/outside-git/b1-agent/public_data \
BPB_B1_PYTHON=/path/to/b1-host/bin/python \
bash tasks/intracortical/falcon-b1-birdsong/env/setup.sh
```

The setup script stages Train and Valid only.
It does not stage raw NWB files, Test arrays, the full contract, or trusted receipts.
Provide only the staged public directory to the Agent.
Remove source, cache, and evaluator paths from its environment and disable network access.

Use the [manual collection workflow](../../../README.md#evaluate-your-agent) for a runnable task entry.
Set `BPB_B1_DATA_DIR` to the staged public directory and `BPB_B1_PYTHON` to the trusted host interpreter.
Build an inference image from `checks/Dockerfile` and pass its immutable image ID to the scorer.
The local CPU image uses Python 3.12, NumPy 2.2.6, PyTorch 2.7.1, and safetensors 0.5.3.
The worker runs without network access and returns a bounded spectrogram response.

The scorer applies the native mask to each prediction and target.
It scales each masked prediction and target independently to `[0,1]`.
Constant masked predictions are invalid because min-max normalization is undefined.
It computes motif MSE, averages motifs within each date, and then gives dates equal weight.
The public check scores Valid only.

## Fixed reference and owner Test

The [reference builder](solution/make_reference.py) averages two spectrograms from the first real Train file.
It returns that fixed template for every motif.
This low-information model checks the input, submission, and scoring path.
It does not establish useful decoding performance.
The contract-bound Valid check used all eight complete motifs.
It returned normalized spectrogram MSE `0.0010954087590801266`.
This value is a fixed-reference development result, not an Agent benchmark result.

The owner can export Test with `_sequence_shared/export.py --task b1 --access evaluator --allow-test-export`.
This trusted conversion reads Test spectrograms but does not run a model.
Before an owner Test run, freeze the exact three submission files with `checks/freeze_submission.py`.
Then call `checks/score.py` with `--role test --owner-test`, the evaluator Test manifest, and the frozen-artifact path.
Set `--report-output` to a new JSON path outside Git.
The owner Test command writes that separate report and emits no public score block.
Neither public Valid nor owner Test is an official FALCON evaluation.
One owner Test functional pass used the same frozen reference artifact.
Its separate report remains outside Git and outside the public score block.
