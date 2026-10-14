# Wang2017 SSVEP classification

[Task collection](../../../README.md#task-suite) · [EEG tasks](../README.md) · [Data lock](data.lock)

This Wang2017 SSVEP task classifies four-second EEG windows into 40 native classes. The native split evaluates the chosen method on different subjects.

> [!NOTE]
> **Agent benchmark results: not yet available.**

## Task at a glance

| Field | Details |
| --- | --- |
| Task ID | `eeg-ssvep-wang2017` |
| Scientific data | `ssvep/default` (`wang2017`) |
| EEG input | 64 channels · 120 Hz · 4 s · `[64, 480]` samples |
| Public windows | 4,800 train · 1,680 validation |
| Native split | Subject-disjoint native SklearnSplit. |
| Output | 40 native classes · normalized probabilities `[B, 40]` |
| Metric | Balanced accuracy (maximize). Complete-class per-class recall. |

## Run this task

From the repository root, fetch and prepare the public data:

```sh
node dist/cli.js fetch eeg-ssvep-wang2017 --public
node dist/cli.js prepare eeg-ssvep-wang2017 --workspace /absolute/new-workspace
```

The fetch command checks file sizes and SHA-256 hashes against `data.lock`. The data files stay outside Git.

For a public-only local package, set `BPB_EEG_PUBLIC_PACKAGE_DIR` to its directory. The setup script checks the original `task_spec.json` SHA-256 and all four public file hashes and sizes. Never place private Test files or source-private bindings in that package or the Agent workspace.

Before public scoring, run `bash tasks/eeg/_shared/setup-python.sh`. Set `BPB_EEG_PYTHON` to the printed interpreter with NumPy 2.2.6. The inference image is separate from this trusted host environment.

## Submission and evaluation

Submit one chosen method with seeds 0, 1, and 2. Each `submission/seed-N/` directory must contain `model.py`, `config.json`, and `weights.safetensors`. The three seeds form one submission, not three research episodes.

`model.py` must define `Model(config)` and `forward(x)`. Each model must reload its own saved weights and return normalized `[B, 40]` probabilities. During inference, the model cannot train, use the network, or read task files. Parameters and saved numerical state must each stay at or below 10 million elements.

The public scorer retains validation labels in the trusted parent process. It runs submitted code in isolated Docker inference. Extra files are ignored, but a missing required file fails the submission. Private Test data, labels, and feedback are unavailable. There is no fixed research duration or required improvement threshold.

See the [shared EEG guide](../_shared/README.md) for the inference image, scorer, and metric-profile details.

<details>
<summary>Protocol and provenance</summary>

- Native source case: `ssvep/default`.
- Frozen source task version: `expanded-three-seed-20260923-wang17-v1`.
- Scientific source checkout: `a8092dc10956038e445ff0e07f9c0c7e03a10d36`.
- Original public task-spec SHA-256: `9cd728f7038f36b7783f9f0d04d657789dd19100111791522342892803471216`.
- Native split contract: `native SklearnSplit; rule=subject-disjoint; split_by=subject`.
- Integration snapshot availability field: `frozen_manifest_bound_not_downloaded_here`.
- `contract.json` pins the label mapping, metric profile, and exact bytes and SHA-256 for four public files.
- Historical source-project results remain separate from this BrainPilotBench task.

</details>
