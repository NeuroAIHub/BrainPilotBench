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
| `decoding_error_within_tolerance`   | 1 iff `1 - real/shuffle >= reduction_min - tolerance`                  |

Extra observational floats (`*_value`) are also emitted but do NOT belong to the
category's required-metric set — they're for context on the leaderboard.

## Calibrating `reference.json` (maintainer checklist)

The first version ships with generous ranges. To tighten:

```bash
# 1) Run the official reference on the pinned data
cd /some/scratch/dir
mkdir -p artifacts data
ln -sf ~/.cache/brainpilot-bench/0a5f35ccf29ce6611908f5233b4325bfcc43e63c57e4d3763a4cf7dcea6f0987/data \
       data/VRBeltReframe.mat
python -m pip install -r $BPB/tasks/neuro-rsc-place-cell/checks/requirements.txt
python $BPB/tasks/neuro-rsc-place-cell/checks/benchmark.py \
    --input data/VRBeltReframe.mat \
    --output artifacts \
    --sessions all --track-length-cm 90 --n-bins 50 \
    --place-shuffles 500 --decoding-shuffles 500 \
    --cv-folds 5 --decoder-cells all --seed 7

# 2) Read the produced fields and update reference.json accordingly:
python3 -c "
import json
s = json.load(open('artifacts/benchmark_summary.json'))
ratio = s['cross_session_place_cell_stability']['place_cell_ratio_mean']
sig   = s['position_decoding_significance']['decoding_significant']
real  = s['position_decoding_significance']['real_median_decoding_error_cm']
shuf  = s['position_decoding_significance']['shuffle_median_decoding_error_cm']
print(f'  place_cell_ratio_mean       = {ratio:.4f}')
print(f'  decoding_significant        = {sig}')
print(f'  reduction_ratio 1 - real/shuf = {1 - real/shuf:.4f}')
"

# 3) Set reference.json:
#    place_cell_ratio_mean.{min,max}    = ratio ± 0.10  (empirical margin)
#    decoding_significant_expected      = sig
#    decoding_error_reduction_ratio_min = observed - 0.10
#    decoding_error_relative_tolerance  = 0.10          (kept narrow post-calibration)

# 4) Re-run `bp-bench validate neuro-rsc-place-cell` — Oracle门must pass.
```

## Why `solution/solution.sh` doesn't call `benchmark.py`

The Oracle sandbox has a hard **120 s timeout** (`src/validate.ts:107`).
`benchmark.py` on the 203 MB `.mat` with 500 shuffles takes ~15-30 min — nowhere
near feasible. The Oracle just synthesizes a summary that satisfies the current
`reference.json` (proves the grader accepts a valid submission); the real fidelity
check is running `benchmark.py` yourself against the pinned data (calibration
steps above), which is a maintainer chore, not a per-PR gate.
