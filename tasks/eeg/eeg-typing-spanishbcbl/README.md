# SpanishBCBL EEG typing classification

[Task collection](../../../README.md#task-suite) · [EEG tasks](../README.md) · [Data lock](data.lock)

This task classifies one-second typing-related EEG windows into 29 source-defined output classes. The mapping includes characters, space, a number group, and a special-symbol group. The native SimilaritySplit separates train and validation by sentence-similarity clusters.

> [!NOTE]
> **Agent benchmark results: not yet available.**

## Task at a glance

| Field | Details |
| --- | --- |
| Task ID | `eeg-typing-spanishbcbl` |
| Scientific data | `typing/default` (`Levy2026NoninvasiveEeg`) |
| EEG input | 61 channels · 120 Hz · 1 s · `[61, 120]` samples |
| Public windows | 87,656 train · 32,909 validation |
| Native split | Sentence-similarity cluster-disjoint native SimilaritySplit. |
| Output | 29 native classes · normalized probabilities `[B, 29]` |
| Metric | Balanced accuracy (maximize). Sparse macro over observed true or predicted classes. |

## Run this task

From the repository root, fetch and prepare the public data:

```sh
node dist/cli.js fetch eeg-typing-spanishbcbl --public
node dist/cli.js prepare eeg-typing-spanishbcbl --workspace /absolute/new-workspace
```

The fetch command checks file sizes and SHA-256 hashes against `data.lock`. The data files stay outside Git.

For a public-only local package, set `BPB_EEG_PUBLIC_PACKAGE_DIR` to its directory. The setup script checks the original `task_spec.json` SHA-256 and all four public file hashes and sizes. Never place private Test files or source-private bindings in that package or the Agent workspace.

Before public scoring, run `bash tasks/eeg/_shared/setup-python.sh`. Set `BPB_EEG_PYTHON` to the printed interpreter with NumPy 2.2.6. The inference image is separate from this trusted host environment.

## Submission and evaluation

Submit one chosen method with seeds 0, 1, and 2. Each `submission/seed-N/` directory must contain `model.py`, `config.json`, and `weights.safetensors`. The three seeds form one submission, not three research episodes.

`model.py` must define `Model(config)` and `forward(x)`. Each model must reload its own saved weights and return normalized `[B, 29]` probabilities. During inference, the model cannot train, use the network, or read task files. Parameters and saved numerical state must each stay at or below 10 million elements.

The public scorer retains validation labels in the trusted parent process. It runs submitted code in isolated Docker inference. Extra files are ignored, but a missing required file fails the submission. Private Test data, labels, and feedback are unavailable. There is no fixed research duration or required improvement threshold.

The typing metric includes predicted-only classes with zero recall. It excludes classes absent from both targets and predictions.

See the [shared EEG guide](../_shared/README.md) for the inference image, scorer, and metric-profile details.

<details>
<summary>Protocol and provenance</summary>

- Native source case: `typing/default`.
- Frozen source task version: `d-typing-full-v3-20261012-r1`.
- Scientific source checkout: `a8092dc10956038e445ff0e07f9c0c7e03a10d36`.
- Original public task-spec SHA-256: `5e482fdbb948102d728d1a992a2683796cda22999a4f07caaa3531aa3d9ebeae`.
- Native split contract: `native SimilaritySplit; rule=native sentence-similarity cluster-disjoint`.
- Integration snapshot availability field: `prepared_public_packet_not_downloaded_here`.
- `contract.json` pins the label mapping, metric profile, and exact bytes and SHA-256 for four public files.
- The audited source handoff had no completed Agent run for this packet.

</details>
