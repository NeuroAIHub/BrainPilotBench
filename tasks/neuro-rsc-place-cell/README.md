# neuro-rsc-place-cell

> RSC 位置细胞动态分析 — mouse retrosplenial cortex Ca²⁺ imaging + VR belt behavior. Task version 0.2.

## What the agent does

Reads `./data/VRBeltReframe.mat` (staged by `env/setup.sh` from HF-hosted content-
addressed cache), performs 5 sub-analyses on RSC place-cell dynamics, and produces
`benchmark_summary.json` + `report.md` + `figures/*.png`. Full brief in
`prompt/turns.yaml`.

## How it's scored

Two scorers, one score space (see repo README §"How it's scored"):

| Scorer         | Metrics                                                              | Source                                       |
|----------------|----------------------------------------------------------------------|----------------------------------------------|
| `exec-script`  | Three deterministic checks plus their equal-weight `score` | `checks/check.sh` compares `benchmark_summary.json` to the frozen calibrated reference |
| `rubric-human` | `visualization_quality`, `trial_bin_analysis`, `firing_rate_analysis` | Human reviewer fills `runs/<runId>/scoresheet.json` |

Missing artifacts / missing summary fields → `unscored` (never 0 — see repo README
"three-state leaderboard" and NOP contract).

The deterministic headline score is the mean of
`place_cell_ratio_ok`, `decoding_significance_ok`, and
`decoding_error_within_tolerance`, so it is one of 0, 0.333333, 0.666667, or
1. The human dimensions are reported separately and are never folded into that
deterministic score.

## Running it end-to-end

```bash
# 1) Fetch the pinned public dataset once.
bp-bench fetch neuro-rsc-place-cell --public

# 2) Built-in adapters stage data + the public output schema before prompting.
bp-bench run neuro-rsc-place-cell --adapter brainpilot \
  --base-url http://127.0.0.1:9001 \
  --workspace-root /absolute/path/to/BrainPilot/brainpilot/workspaces \
  --agent brainpilot@local

# 3) Verify and score the captured bundle.
bp-bench submit verify runs/<bundle>
bp-bench score runs/<bundle>

# 4) Optional blinded human review of report/figure dimensions.
bp-bench leaderboard runs/
```

## Data

Pinned to `BrainPilot-Bench/Tasks-Data-Public@7159b2dd` (2026-07-13 drop). See
`data.lock` for uri + sha256. `env/setup.sh` symlinks the cached file to
`./data/VRBeltReframe.mat`.

### Data source and citation

The recordings and virtual-reality behavior originate from the study below.
Please cite it when using this task or its data:

> Mao, D., Molina, L. A., Bonin, V., & McNaughton, B. L. (2020). Vision and
> locomotion combine to drive path integration sequences in mouse
> retrosplenial cortex. *Current Biology, 30*(9), 1680–1688.e4.
> https://doi.org/10.1016/j.cub.2020.02.070

## Files

| Path                        | Purpose                                                    |
|-----------------------------|------------------------------------------------------------|
| `task.yaml`                 | meta + expected_artifacts + scoring (exec + rubric-human)  |
| `prompt/turns.yaml`         | single turn describing all 5 sub-tasks + output contract   |
| `data.lock`                 | `hf://` pin + sha256                                       |
| `env/setup.sh`              | stage cached MAT and public output schema                    |
| `checks/`                   | grader assets (see `checks/README.md`)                     |
| `solution/solution.sh`      | Oracle synthesizer (satisfies exec门 within 120s)          |
| `rubric.yaml`               | 3 dimensions for the rubric-human scorer                   |
