# Human Choices from Four Card Decks — Experiment 1

[Task collection](../../../README.md#task-suite) · [Psychology tasks](../README.md) · [Data lock](data.lock)

Participants draw cards from four decks and experience varying gains and occasional losses. The agent predicts participants' recorded responses from the information available before each response.

> [!NOTE]
> **Agent benchmark results: not yet available.**
> A task-level reference pipeline is not an accepted Agent result or an official Test score.

## Task at a glance

| Field | Details |
| --- | --- |
| Task ID | `psych101-steingroever2015data-exp1` |
| Source experiment | `steingroever2015data/exp1.csv` |
| Public data | 328 train and 82 valid participants |
| Agent output | `report.md` and three `submission/seed-N/` model bundles |
| Prediction protocol | `iowa_four_deck_v0`: probabilities over displayed keys |
| Public metric | `mean_response_nll` ↓, nats per response · public validation only |

## Run this task

For this task, `data.lock` pins public `train.jsonl` and `valid.jsonl` at one immutable Hugging Face commit. It records the size and SHA-256 of each file.

From the repository root, run:

```sh
node dist/cli.js fetch psych101-steingroever2015data-exp1 --public
node dist/cli.js prepare psych101-steingroever2015data-exp1 --workspace /absolute/new-workspace
```

The fetch command checks both file sizes and SHA-256 hashes. Prepare reads the content-addressed cached splits and creates `public_data/`. It does not download or rebuild the original 859,179,475-byte source.

If you have an existing verified public package, set `BPB_PSYCH101_PUBLIC_TASK_DIR` to its task directory. That directory must contain `train.jsonl` and `valid.jsonl`. The setup helper checks both hashes.

The task helpers need Python 3.11–3.13 and the standard library only. No package installation is required. The package does not contain official private Test data.

## Submission and evaluation

Each seed bundle must declare its parameter count and saved numeric state. The limits are 100,000 fitted or pretrained parameters and 1,000,000 saved numeric elements. The three seeds form one Agent research episode, not three independent repetitions.

The Agent submits `report.md` and three seed directories under `submission/`, each with `model.py`, `config.json`, and `weights.json`. `Model(config,weights).predict(prefix)` returns a normalized distribution over the currently displayed keys. `checks/check.sh` verifies every public valid response, writes `psych101-public-validation.json`, and emits a finite numeric `mean_response_nll` when defined. Exact zero probability yields `nll_infinite: 1` and a typed `valid_infinite_loss` sidecar; it is never changed to zero loss.

The public-valid controller keeps each current target answer on the host and loads submitted `model.py` only in a pinned, network-disabled, read-only Docker worker. That worker receives one causal prefix per request and only the nine required frozen files. Earlier completed responses and feedback remain visible in the prefix; current answers, future feedback, private Test, host caches, and credentials do not. The task refuses `BPB_OFFICIAL_SCORING=1` because no authorized private Test is included. Public valid can be used during research, so this score is a development result, not blind generalization or the historical Test score. The historical evaluator backend and frozen results remain in the original project. The inference image includes Python 3.12, NumPy 2.2.6, SciPy 1.15.3, scikit-learn 1.6.1, and PyTorch 2.7.1+cpu; arbitrary historical frozen-model compatibility has not been claimed. See `../README.md` for the standalone image build and immutable-ID scoring command.

A deterministic real-data reference is available at `reference/run_reference.sh`; it fits a Laplace-smoothed option-position prior on public train, saves three declared deterministic seed bundles, reloads them and scores public valid. It is a pipeline check, not a cognitive benchmark claim.

## Source and provenance

Source experiment: `steingroever2015data/exp1.csv`; published package `published-20261002-v1`; source Agent contract `sampling-agent-20261006-v1`.
This task is a public validation integration. It does not replay or expose the original official Test.

The original public source is `marcelbinz/Psych-101` at revision `611565c66395e2787cd7e3305149bb75dc138024`.
Its `prompts_training.jsonl` has SHA-256 `7a370a94084acd6f73f20d6559214683cfadcab8a1f69e369df285ba75ccef01`.
The current `data.lock` fetches only the public train and valid splits for this task.
