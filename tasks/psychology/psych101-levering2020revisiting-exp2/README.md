# Human Object Classification and Typicality Ratings — Experiment 2

[Task collection](../../../README.md#task-suite) · [Psychology tasks](../README.md) · [Data lock](data.lock)

Participants classify objects by shape, size, and shading, then rate category typicality in a test block. The agent predicts participants' recorded responses from the information available before each response.

> [!NOTE]
> **Agent benchmark results: not yet available.**
> A task-level reference pipeline is not an accepted Agent result or an official Test score.

## Task at a glance

| Field | Details |
| --- | --- |
| Task ID | `psych101-levering2020revisiting-exp2` |
| Source experiment | `levering2020revisiting/exp2.csv` |
| Public data | 81 train and 21 valid participants |
| Agent output | `report.md` and three `submission/seed-N/` model bundles |
| Prediction protocol | `byte_next_v1`: next UTF-8 byte or EOS for marked responses |
| Public metric | `mean_response_nll` ↓, nats per response · public validation only |

## Run this task

For this task, `data.lock` pins public `train.jsonl` and `valid.jsonl` at one immutable Hugging Face commit. It records the size and SHA-256 of each file.

From the repository root, run:

```sh
node dist/cli.js fetch psych101-levering2020revisiting-exp2 --public
node dist/cli.js prepare psych101-levering2020revisiting-exp2 --workspace /absolute/new-workspace
```

The fetch command checks both file sizes and SHA-256 hashes. Prepare reads the content-addressed cached splits and creates `public_data/`. It does not download or rebuild the original 859,179,475-byte source.

If you have an existing verified public package, set `BPB_PSYCH101_PUBLIC_TASK_DIR` to its task directory. That directory must contain `train.jsonl` and `valid.jsonl`. The setup helper checks both hashes.

The task helpers need Python 3.11–3.13 and the standard library only. No package installation is required. The package does not contain official private Test data.

## Submission and evaluation

Each seed bundle must declare its parameter count and saved numeric state. The limits are 100,000 fitted or pretrained parameters and 1,000,000 saved numeric elements. The three seeds form one Agent research episode, not three independent repetitions.

Submit `report.md` and three `submission/seed-N/` bundles, each with `model.py`, `config.json`, and `weights.json`. `Model.predict_next(prefix, response_prefix_bytes)` returns a normalized 257-element list for 256 raw UTF-8 bytes plus EOS 256. The controller sends one causal query at a time; current target bytes and future feedback remain outside the Docker worker. The per-response loss includes the EOS probability and is averaged over only `<<...>>` marked source responses. No class set, numeric grid, rounding rule or output mapping is learned from public valid or Test.

This is public development validation; valid may have informed Agent research, and historical Test scores are not replayed. Numeric/text answers are scored in their exact source spelling, including decimal precision.

The task refuses `BPB_OFFICIAL_SCORING=1`. A task-scoped controller stages exactly nine frozen files and uses a pinned, network-disabled Docker worker with no current targets or private data mounted. See `../README.md` for the standalone inference image build and immutable-ID scoring command. A deterministic train-only byte-unigram pipeline reference is available at `reference/run_reference.sh`; it has not been fitted for this experiment in this integration.

## Source and provenance

Source experiment: `levering2020revisiting/exp2.csv`; published public package `published-20261002-v1`. BPB profile `byte_next_v1` / metric version `utf8-byte-eos-v1` is new and distinct from the original historical model-token and closed-option protocols.

The original public source is `marcelbinz/Psych-101` at revision `611565c66395e2787cd7e3305149bb75dc138024`.
Its `prompts_training.jsonl` has SHA-256 `7a370a94084acd6f73f20d6559214683cfadcab8a1f69e369df285ba75ccef01`.
The current `data.lock` fetches only the public train and valid splits for this task.
