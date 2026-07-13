# neuro-rsc-place-cell

> RSC 位置细胞动态分析 — mouse retrosplenial cortex Ca²⁺ imaging + VR belt behavior.

## What the agent does

Reads `./data/VRBeltReframe.mat` (staged by `env/setup.sh` from HF-hosted content-
addressed cache), performs 5 sub-analyses on RSC place-cell dynamics, and produces
`benchmark_summary.json` + `report.md` + `figures/*.png`. Full brief in
`prompt/turns.yaml`.

## How it's scored

Two scorers, one score space (see repo README §"How it's scored"):

| Scorer         | Metrics                                                              | Source                                       |
|----------------|----------------------------------------------------------------------|----------------------------------------------|
| `exec-script`  | `place_cell_ratio_ok`, `decoding_significance_ok`, `decoding_error_within_tolerance` | `checks/check.sh` compares `benchmark_summary.json` to `checks/reference.json` (tolerance-based) |
| `rubric-human` | `visualization_quality`, `trial_bin_analysis`, `firing_rate_analysis` | Human reviewer fills `runs/<runId>/scoresheet.json` |

Missing artifacts / missing summary fields → `unscored` (never 0 — see repo README
"three-state leaderboard" and NOP contract).

## Running it end-to-end

```bash
# 1) One-time: fetch the pinned HF dataset into the local content-addressed cache
bp-bench fetch neuro-rsc-place-cell

# 2) Stage into agent workspace (still manual until SUT adapter lands):
cd /path/to/agent-workspace && bash $BPB/tasks/neuro-rsc-place-cell/env/setup.sh

# 3) Run the agent, drop its outputs under artifacts/ + report.md + figures/
#    See examples/submission/ for the bundle contract.
bp-bench submit verify runs/<bundle>
bp-bench score          runs/<bundle>

# 4) Human review — open runs/<bundle>/scoresheet.json, fill rubric scores.
bp-bench leaderboard runs/
```

## Data

Pinned to `BrainPilot-Bench/Tasks-Data-Public@7159b2dd` (2026-07-13 drop). See
`data.lock` for uri + sha256. `env/setup.sh` symlinks the cached file to
`./data/VRBeltReframe.mat`.

## Files

| Path                        | Purpose                                                    |
|-----------------------------|------------------------------------------------------------|
| `task.yaml`                 | meta + expected_artifacts + scoring (exec + rubric-human)  |
| `prompt/turns.yaml`         | single turn describing all 5 sub-tasks + output contract   |
| `data.lock`                 | `hf://` pin + sha256                                       |
| `env/setup.sh`              | stage cached MAT → `./data/VRBeltReframe.mat`              |
| `checks/`                   | grader assets (see `checks/README.md`)                     |
| `solution/solution.sh`      | Oracle synthesizer (satisfies exec门 within 120s)          |
| `rubric.yaml`               | 3 dimensions for the rubric-human scorer                   |
