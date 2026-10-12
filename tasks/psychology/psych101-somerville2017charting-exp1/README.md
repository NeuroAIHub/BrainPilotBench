# psych101-somerville2017charting-exp1

Source experiment: `somerville2017charting/exp1.csv`; published public package `published-20261002-v1`. BPB profile `byte_next_v1` / metric version `utf8-byte-eos-v1` is new and distinct from the original historical model-token and closed-option protocols.

## Public data

`data.lock` pins the 859,179,475-byte Apache-2.0 public source at a fixed revision and SHA-256. Run `bp-bench fetch psych101-somerville2017charting-exp1 --public`; `env/setup.sh --role agent` reconstructs this experiment's participant-group train/valid split and verifies the exact published split hashes. Or set `BPB_PSYCH101_PUBLIC_TASK_DIR` to a verified directory containing this experiment's public `train.jsonl` and `valid.jsonl`. No maintainer path or private Test is required.

## Inference and score

Submit `report.md` and three `submission/seed-N/` bundles, each with `model.py`, `config.json`, and `weights.json`. `Model.predict_next(prefix, response_prefix_bytes)` returns a normalized 257-element list for 256 raw UTF-8 bytes plus EOS 256. The controller sends one causal query at a time; current target bytes and future feedback remain outside the Docker worker. The per-response loss includes the EOS probability and is averaged over only `<<...>>` marked source responses. No class set, numeric grid, rounding rule or output mapping is learned from public valid or Test.

This is public development validation; valid may have informed Agent research, and historical Test scores are not replayed. Numeric/text answers are scored in their exact source spelling, including decimal precision. For Go/NoGo, unmarked omissions remain context rather than new scored targets. For Wu2018, public `0` responses are preserved despite the 1–30 instruction discrepancy.

The task refuses `BPB_OFFICIAL_SCORING=1`. A task-scoped controller stages exactly nine frozen files and uses a pinned, network-disabled Docker worker with no current targets or private data mounted. See `../README.md` for the standalone inference image build and immutable-ID scoring command. A deterministic train-only byte-unigram pipeline reference is available at `reference/run_reference.sh`; it has not been fitted for this experiment in this integration.
