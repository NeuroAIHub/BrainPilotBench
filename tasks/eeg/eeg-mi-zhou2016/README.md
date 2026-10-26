# Zhou2016 motor-imagery classification

[Task collection](../../../README.md#task-suite) · [EEG tasks](../README.md) · [Data lock](data.lock)

This Zhou2016 task classifies four-second motor-imagery EEG windows into three native classes. The source protocol places training and validation in separate sessions.

> [!NOTE]
> **Agent benchmark results: not yet available.**

## Task at a glance

| Field | Details |
| --- | --- |
| Task ID | `eeg-mi-zhou2016` |
| Scientific data | `motor_imagery/zhou2016` (`zhou2016`) |
| EEG input | 14 channels · 120 Hz · 4 s · `[14, 480]` samples |
| Public windows | 614 train · 586 validation |
| Native split | Session-disjoint native PredefinedSplit. |
| Output | 3 native classes · normalized probabilities `[B, 3]` |
| Metric | Balanced accuracy (maximize). Complete-class per-class recall. |

## Run this task

From the repository root, fetch and prepare the public data:

```sh
node dist/cli.js fetch eeg-mi-zhou2016 --public
node dist/cli.js prepare eeg-mi-zhou2016 --workspace /absolute/new-workspace
```

The fetch command checks file sizes and SHA-256 hashes against `data.lock`. The data files stay outside Git.

For a public-only local package, set `BPB_EEG_PUBLIC_PACKAGE_DIR` to its directory. The setup script checks the original `task_spec.json` SHA-256 and all four public file hashes and sizes. Never place private Test files or source-private bindings in that package or the Agent workspace.

Before public scoring, run `bash tasks/eeg/_shared/setup-python.sh`. Set `BPB_EEG_PYTHON` to the printed interpreter with NumPy 2.2.6. The inference image is separate from this trusted host environment.

## Submission and evaluation

Submit one chosen method with seeds 0, 1, and 2. Each `submission/seed-N/` directory must contain `model.py`, `config.json`, and `weights.safetensors`. The three seeds form one submission, not three research episodes.

`model.py` must define `Model(config)` and `forward(x)`. Each model must reload its own saved weights and return normalized `[B, 3]` probabilities. During inference, the model cannot train, use the network, or read task files. Parameters and saved numerical state must each stay at or below 10 million elements.

The public scorer retains validation labels in the trusted parent process. It runs submitted code in isolated Docker inference. Extra files are ignored, but a missing required file fails the submission. Private Test data and labels are unavailable to the Agent during research. There is no fixed research duration or required improvement threshold.

Maintainers can use the separate [private evaluation workflow](../../../docs/private-evaluation.md) with this task's `evaluator.lock`.
It evaluates a frozen submission and writes `scores.private.json`; the default scorer remains public validation.

See the [shared EEG guide](../_shared/README.md) for the inference image, scorer, and metric-profile details.

<details>
<summary>Protocol and provenance</summary>

- Native source case: `motor_imagery/zhou2016`.
- Frozen source task version: `expanded-three-seed-20260923-zhou-v1`.
- Scientific source checkout: `a8092dc10956038e445ff0e07f9c0c7e03a10d36`.
- Original public task-spec SHA-256: `f24b704214152c3d6425814dc475c35dabdc1d3c1ad62634c80986b271b26e9e`.
- Native split contract: `native PredefinedSplit; rule=session-disjoint; valid_split_by=session`.
- Integration snapshot availability field: `frozen_manifest_bound_not_downloaded_here`.
- `contract.json` pins the label mapping, metric profile, and exact bytes and SHA-256 for four public files.
- Historical source-project results remain separate from this BrainPilotBench task.

</details>
