# checks/ — grader assets for `neuro-rsc-place-cell`

## Files

| File               | Role                                                                                     |
|--------------------|------------------------------------------------------------------------------------------|
| `check.sh`         | The exec-script grader. Reads `artifacts/benchmark_summary.json`, compares against       |
|                    | `reference.json`, emits `{metric: number}` between `BPB_SCORES` sentinels.               |
| `reference.json`   | Reference values / tolerances for the three exec metrics.                                |
| `output_schema.json` | JSON Schema advertised to the agent so they know the required summary shape.           |
| `benchmark.py`     | Reference implementation of the full analysis (from the original wwr project).           |
|                    | Not called by `check.sh`; ships here so maintainers can (a) calibrate `reference.json`   |
|                    | and (b) as a documented gold standard. Agent must **not** be shown this file at run-time. |
| `requirements.txt` | Python deps for `benchmark.py` (numpy 2.1.3 / scipy 1.14.1 / scikit-learn 1.5.2).         |

## Exec metrics produced by `check.sh`

| Metric                              | Definition                                                             |
|-------------------------------------|------------------------------------------------------------------------|
| `place_cell_ratio_ok`               | 1 iff `place_cell_ratio_mean ∈ [reference.min, reference.max]`         |
| `decoding_significance_ok`          | 1 iff `decoding_significant` matches reference expectation (true)      |
| `decoding_error_within_tolerance`   | 1 iff `1 - real/shuffle >= frozen improvement minimum`                 |
| `score`                             | Equal-weight mean of the three binary checks                           |

Extra observational floats (`*_value`) are also emitted but do NOT belong to the
category's required-metric set — they're for context on the leaderboard.

## Frozen calibration

Task version 0.2 was calibrated before formal evaluation against the pinned
dataset SHA-256
`0a5f35ccf29ce6611908f5233b4325bfcc43e63c57e4d3763a4cf7dcea6f0987`.
The official command used all 12 sessions, 50 spatial bins, 500 place-cell
shuffles, 500 decoding shuffles, five trial-grouped folds, all decoder cells,
and seed 7. It produced:

```text
place_cell_ratio_mean             0.3862502045956126
place_cell_ratio_std              0.1310122746525408
real_median_decoding_error_cm     7.881120964839798
shuffle_median_decoding_error_cm  23.575363868784294
decoding_improvement_ratio        0.6657052247971856
decoding_p_value                  0.001996007984031936
decoding_significant              true
```

The SHA-256 was
`567eed773226b7bfac2a53d09e8f9a27f56aaf6d86c1d414ecd9e26832c0b8bd`
for a sorted, compact JSON object containing exactly the seven fields printed
above (using the labels above as keys).
Independent runs on macOS arm64/Python 3.12.12 and Linux arm64 using
`python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b`
produced identical normalized summaries, session metrics, shuffle distributions,
and place-cell labels. Cell-level floating-point values agreed within
`1.2e-15` absolute error.

The frozen acceptance region is reference place-cell ratio ±0.10, expected
decoding significance `true`, and reference decoding improvement minus 0.10.
Changing any threshold after an evaluated Agent run has started requires a new
task version and a complete rerun of the comparison matrix.

### Reproduce the reference

```bash
bp-bench fetch neuro-rsc-place-cell --public
mkdir -p /tmp/rsc-reference/{data,artifacts}
ln -sf ~/.cache/brainpilot-bench/0a5f35ccf29ce6611908f5233b4325bfcc43e63c57e4d3763a4cf7dcea6f0987/data \
  /tmp/rsc-reference/data/VRBeltReframe.mat
python -m pip install -r tasks/neuro-rsc-place-cell/checks/requirements.txt
python tasks/neuro-rsc-place-cell/checks/benchmark.py \
  --input /tmp/rsc-reference/data/VRBeltReframe.mat \
  --output /tmp/rsc-reference/artifacts \
  --sessions all --track-length-cm 90 --n-bins 50 \
  --place-shuffles 500 --decoding-shuffles 500 \
  --cv-folds 5 --decoder-cells all --seed 7
```

## Why `solution/solution.sh` remains synthetic

CI intentionally does not download the 203 MB dataset. The Oracle therefore
synthesizes a valid summary only to prove the scorer accepts a conforming bundle;
the real reference fidelity is established by the frozen cross-platform run above.
