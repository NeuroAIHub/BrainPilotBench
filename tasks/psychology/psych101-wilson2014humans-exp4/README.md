# psych101-wilson2014humans-exp4

Source experiment: `wilson2014humans/exp4.csv`; published package `published-20261002-v1`; adapted interface version `family-profile-20261012-v1`.
This task is a public validation integration. It does not replay or expose the original official Test.

## Public data

For this task, `data.lock` pins public `train.jsonl` and `valid.jsonl` at one immutable Hugging Face commit. It records the size and SHA-256 of each file.

From the repository root, run:

```sh
node dist/cli.js fetch psych101-wilson2014humans-exp4 --public
node dist/cli.js prepare psych101-wilson2014humans-exp4 --workspace /absolute/new-workspace
```

The fetch command checks both file sizes and SHA-256 hashes. Prepare reads the content-addressed cached splits and creates `public_data/`. It does not download or rebuild the original 859,179,475-byte source.

If you have an existing verified public package, set `BPB_PSYCH101_PUBLIC_TASK_DIR` to its task directory. That directory must contain `train.jsonl` and `valid.jsonl`. The setup helper checks both hashes.

The task helpers need Python 3.11–3.13 and the standard library only. No package installation is required. The package does not contain official private Test data.

## Submission and score

The Agent submits `report.md` and three seed directories under `submission/`, each with `model.py`, `config.json`, and `weights.json`. `Model(config,weights).predict(prefix)` returns a normalized distribution over the currently displayed keys. `checks/check.sh` verifies every public valid response, writes `psych101-public-validation.json`, and emits a finite numeric `mean_response_nll` when defined. Exact zero probability yields `nll_infinite: 1` and a typed `valid_infinite_loss` sidecar; it is never changed to zero loss.

The public-valid controller keeps each current target answer on the host and loads submitted `model.py` only in a pinned, network-disabled, read-only Docker worker. That worker receives one causal prefix per request and only the nine required frozen files. Earlier completed responses and feedback remain visible in the prefix; current answers, future feedback, private Test, host caches, and credentials do not. The task refuses `BPB_OFFICIAL_SCORING=1` because no authorized private Test is included. Public valid can be used during research, so this score is a development result, not blind generalization or the historical Test score. Any historical evaluator records remain in the original project. The inference image includes Python 3.12, NumPy 2.2.6, SciPy 1.15.3, scikit-learn 1.6.1, and PyTorch 2.7.1+cpu; arbitrary historical frozen-model compatibility has not been claimed. See `../README.md` for the standalone image build and immutable-ID scoring command.

A deterministic real-data reference is available at `reference/run_reference.sh`; it fits a Laplace-smoothed option-position prior on public train, saves three declared deterministic seed bundles, reloads them and scores public valid. It is a pipeline check, not a cognitive benchmark claim.
