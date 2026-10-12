# psych101-steingroever2015data-exp2

Source experiment: `steingroever2015data/exp2.csv`; published package `published-20261002-v1`; source Agent contract `iowa-three-seed-20261002-unbudgeted-v2`.
This task is a public validation integration. It does not replay or expose the original official Test.

## Public data

`data.lock` pins the original 859,179,475-byte public Psych-101 JSONL at a fixed revision and SHA-256. Fetch it with `bp-bench fetch psych101-steingroever2015data-exp2 --public` before running. The setup script reconstructs this experiment's participant-group train/valid split and verifies both published split hashes in `contract.json`. The same content-addressed source is shared by all 12 tasks.

For an existing verified published public package, set `BPB_PSYCH101_PUBLIC_TASK_DIR` to its directory containing `train.jsonl` and `valid.jsonl`; the setup still verifies both hashes. This option does not require a maintainer-specific path.

Run `bash env/setup.sh --role agent` from an empty Agent workspace to create `public_data/`. `python3` 3.11–3.13 and the standard library are the only task-helper dependencies; no package installation or private data is required.

## Submission and score

The Agent submits `report.md` and three seed directories under `submission/`, each with `model.py`, `config.json`, and `weights.json`. `Model(config,weights).predict(prefix)` returns a normalized distribution over the currently displayed keys. `checks/check.sh` verifies every public valid response, writes `psych101-public-validation.json`, and emits a finite numeric `mean_response_nll` when defined. Exact zero probability yields `nll_infinite: 1` and a typed `valid_infinite_loss` sidecar; it is never changed to zero loss.

The public-valid controller keeps each current target answer on the host and loads submitted `model.py` only in a pinned, network-disabled, read-only Docker worker. That worker receives one causal prefix per request and only the nine required frozen files. Earlier completed responses and feedback remain visible in the prefix; current answers, future feedback, private Test, host caches, and credentials do not. The task refuses `BPB_OFFICIAL_SCORING=1` because no authorized private Test is included. Public valid can be used during research, so this score is a development result, not blind generalization or the historical Test score. The historical evaluator backend and frozen results remain in the original project. The inference image includes Python 3.12, NumPy 2.2.6, SciPy 1.15.3, scikit-learn 1.6.1, and PyTorch 2.7.1+cpu; arbitrary historical frozen-model compatibility has not been claimed. See `../README.md` for the standalone image build and immutable-ID scoring command.

A deterministic real-data reference is available at `reference/run_reference.sh`; it fits a Laplace-smoothed option-position prior on public train, saves three declared deterministic seed bundles, reloads them and scores public valid. It is a pipeline check, not a cognitive benchmark claim.
