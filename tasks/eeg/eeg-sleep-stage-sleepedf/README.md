# Sleep-EDF cassette sleep-stage classification

[Task collection](../../../README.md#task-suite) · [EEG tasks](../README.md) · [Data lock](data.lock)

This task classifies 30-second Sleep-EDF cassette EEG windows into N1, N2, N3, R, and W. It uses a full native export from 78 subjects. The native pipeline crops wake time to 30 minutes and uses a subject-disjoint split.

> [!NOTE]
> **Agent benchmark results: not yet available.**

## Task at a glance

| Field | Details |
| --- | --- |
| Task ID | `eeg-sleep-stage-sleepedf` |
| Scientific data | `sleep_stage/default` from `Kemp2000Analysis` |
| EEG input | 2 channels · 120 Hz · 30 s · `[2, 3600]` samples |
| Public windows | 116,493 train · 38,071 validation |
| Native split | Subject-disjoint `SklearnSplit` · 78 source subjects |
| Output | 5 class probabilities · N1=0, N2=1, N3=2, R=3, W=4 |
| Metric | Five-class balanced accuracy (maximize) · complete-class profile |

## Run this task

From the repository root, prepare the trusted host environment and the public data:

```sh
bash tasks/eeg/_shared/setup-python.sh
node dist/cli.js fetch eeg-sleep-stage-sleepedf --public
node dist/cli.js prepare eeg-sleep-stage-sleepedf --workspace /absolute/new-workspace
```

Set `BPB_EEG_PYTHON` to the interpreter printed by the setup script. The fetch command checks the four public files against `data.lock`. The package has train and validation arrays plus two group files with opaque subject IDs. These group IDs do not overlap between splits.

For an existing public-only package, set `BPB_EEG_PUBLIC_PACKAGE_DIR` to its directory. The package must contain the byte-identical `source-task-spec.json` as `task_spec.json`, plus four public files under `data/`.

## Submission and evaluation

Submit one chosen method with seeds 0, 1, and 2. Each `submission/seed-N/` directory must contain `model.py`, `config.json`, and `weights.safetensors`. Each model returns normalized `[B, 5]` probabilities after it reloads its own weights.

The task limits parameters and saved numerical state to 10 million elements each. Inference cannot train, use the network, or read task files. The shared scorer keeps validation labels in its trusted parent process and runs model code in isolated containers. Private Test data, labels, and feedback are unavailable. There is no required research duration or improvement threshold.

See the [shared EEG guide](../_shared/README.md) for image and scoring instructions. This task differs from the legacy `sleep-edf` task. Do not combine their protocols or results under one task ID.

<details>
<summary>Data provenance and validation limits</summary>

The source task is `sleep_stage/default` from `Kemp2000Analysis`. The scientific source SHA is `a8092dc10956038e445ff0e07f9c0c7e03a10d36`. The source-task version is `bpb-native-full-20261012-v1`. Its public source-spec SHA-256 is `6d0d40390a3d6374e41b2539caaf45068745c066824cbb06a9e4304cee518609`.

`source-task-spec.json` is a new BrainPilotBench spec, not a frozen spec from the independent AgentEEGBench project. `contract.json` binds this spec and the four public files to the shared scorer. `data_provenance.json` records the v3 producer, full config, export, and package hashes. `preparation.json` is a rebuild recipe, not proof about future producer code.

The data-only export did not fit a model or score private Test. The evaluator binding stays outside the public package. Do not copy `complete.json`, `private/`, `lineage/`, or `evaluator/` into Agent input.

The shared public-data reader passed a real-file check. The trusted scorer accepted the validation shape and labels and a synthetic metric fixture. No new model fit, Agent run, full public score, or private Test score was performed. The representative EEG check covers the shared inference path. This task received structure and real-data input checks under the collection's low-cost validation policy.

</details>
