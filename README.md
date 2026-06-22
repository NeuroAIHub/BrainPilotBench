# BrainPilot Benchmark

**BrainPilotBench** is a reproducible, curated benchmark for evaluating **multi-agent scientific-research systems** — agents that *do science*: survey and synthesize literature, analyze data, reason over a domain. It **scores and ranks** (a benchmark, not a pass/fail test suite).

Two things make it different:

- **One score space, two grading modes.** LLM-as-judge rubrics (1–5 per dimension) and deterministic eval scripts run through the same run/eval pipeline, reported as a **per-category three-state leaderboard**: *scored* / *unscored* (excluded — never 0 or fail) / *not-applicable*. "We couldn't score it" is never conflated with "the system did badly."
- **Integrity by construction.** Curated intake + maintainer-run scoring (self-reported numbers are gameable), plus canary GUIDs, `created_at` provenance, and frozen named releases against contamination. The evaluation *method* is fully open (this repo); only task *content* and *official* runs are controlled.

> Status: v0 — the framework is end-to-end; the task corpus is small and growing. Not yet a public leaderboard.

## Quickstart

```bash
git clone https://github.com/NeuroAIHub/BrainPilotBench && cd BrainPilotBench
npm install && npm run build
```

> Snippets use `bp-bench`. From a clone that's `node dist/cli.js` (or run `npm link` once to put `bp-bench` on your PATH).

See the whole eval loop work on the bundled example — a **deterministic exec task, no API keys, no deployment**:

```bash
bp-bench submit verify examples/submission   # the bundle satisfies the task contract ✓
bp-bench score          examples/submission   # run the task's grader → scores.json
bp-bench leaderboard    examples              # per-category table (row = task@agent)
```

That's the eval loop: a **submission bundle** → verified → scored → ranked.

## Evaluate your own agent

The benchmark splits **run** (collect your agent's output) from **eval** (score + rank). Eval is **system-agnostic** — any agent, any language, evaluated by producing a **submission bundle**; no live integration needed.

```
<bundle>/
  meta.json      # {taskId, agent, taskVersion?, producedAt?, notes?}
  artifacts/     # your agent's outputs — must satisfy the task's expected_artifacts globs
  events.jsonl   # optional trace (reserved for future trajectory scoring)
```

```bash
# 1. Read a task: tasks/<id>/task.yaml (goal + expected_artifacts), prompt/turns.yaml (the turns
#    to give your agent), rubric.yaml / checks/ (how it's judged).
bp-bench list
# 2. Run YOUR agent on those turns, producing the expected artifacts.
# 3. Assemble a bundle: meta.json (taskId + agent) + the outputs under artifacts/.
bp-bench submit verify <bundle>          # contract check
bp-bench score          <bundle>          # runs the task's DECLARED scorers (you don't pick them → anti-gaming)
bp-bench leaderboard    <bundles-parent>  # row = task@agent
```

See [`examples/submission/`](examples/submission) for a template. For official leaderboard numbers, scoring is run by maintainers.

> **Not yet automated:** a one-command `run` that drives *any* agent needs the **SUT adapter** (the next deliverable). Today `bp-bench run --base-url` drives only systems speaking BrainPilot's runtime contract (see [Reference](#running-against-a-live-brainpilot-deployment)); everyone else brings a bundle as above.

## How it's scored

- **Two grading modes, one score space.** LLM-judge rubrics (1–5 per dimension, median of N judges) and deterministic exec scripts (`{metric: number}`) flow through the same pipeline; metric and scorer are orthogonal.
- **Three-state per-category leaderboard.** One dense table per `category`; rows = `task@version` (or `task@agent` for submissions), columns = that category's required metrics. Each cell is **scored** (median across runs; rubric 1–5 normalized to `[0,1]`, exec passed through), **unscored** (`—`; judge refusal / infra failure / no output — **excluded from the aggregate, never 0 or fail**), or **not-applicable** (not a column). Cells also show `(scored/total)` coverage.
- **The load-bearing rule:** never let `unscored` count as `0`/fail — a low score means the system did poorly; `unscored` means *we* didn't manage to score it.

---

## Reference

### Project layout

```
@brainpilot/bench   — the framework (npm-publishable; zero runtime deps beyond protocol + yaml)
  task / loader            — task instance format + loading/validation
  scorer/                  — pluggable scorers in one score space: rubric-judge, rubric-human, exec-script
  score / judge / sandbox  — offline eval engine: run/eval split, LLM judge, deterministic exec grader
  data/                    — data.lock content-addressed datasets (bodies in OSS, never in git)
  validate                 — contribution gate (schema + canary + created_at + two-sided Oracle/NOP)
  leaderboard / metrics    — per-category three-state dense tables
  registry                 — frozen named releases (freeze / verify)
  submission               — system-agnostic submission-bundle contract
  runner                   — drives a task against a BrainPilot deployment (a SUT adapter for arbitrary agents is next)
  cli (bp-bench)           — list / run / fetch / score / validate / leaderboard / freeze / registry verify / submit verify

tasks/              — the benchmark task set (the curated content)
  neuro-survey-attention/      — write a survey outline on attention mechanisms
  neuro-trends-connectomics/   — analyze a decade of connectomics trends
```

The **framework** is generic and system-agnostic at the eval boundary. The **task set** is the scientific value — curated content maintainers grow over time.

### Contributing a task

BrainPilotBench is **curated**: you propose a task via a *Task Proposal* issue (prose + data pointers, **no code**), and maintainers author and integrate the canonical task. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for why (contamination + construct validity need editorial judgment) and how. The anatomy below is what a maintainer authors when accepting a proposal.

A task is a directory under `tasks/<id>/`:

| File | Purpose |
|------|---------|
| `task.yaml` | id, domain, summary, `category`, `version`, `created_at`, `expected_artifacts`, `timeout_min`, `budget_tokens`, `requires` |
| `prompt/turns.yaml` | the user turns to inject — `[{send, then}]` |
| `prompt/ask_user.yaml` | (optional) preset answers for `ask_user` prompts (`pattern → answer`, `default`) |
| `env/env.patch.yaml` | (optional) deviations from baseline (image/model/mcp/gpu) |
| `env/setup.sh` | (optional) stage data into the workspace |
| `data.lock` | (optional) dataset URI + sha256 — **data body never committed** |
| `rubric.yaml` | scoring dimensions (1-5 + comment) |

Tasks live one-or-more levels under a task root; `--tasks dirA,dirB` discovers multiple roots recursively. Directories whose name starts with `_` (e.g. `tasks/_example/`) are templates — excluded from `list`/`freeze`, but still gated by `validate all`.

Design a task so it tests a real research capability, and prefer tasks that need no proprietary data (knowledge-organization / survey / trend tasks are ideal — see the two seed tasks). If a task needs data, reference it via `data.lock`, never commit the data.

### Large datasets — `data.lock`

Dataset bodies are **never committed to git** (CI enforces ≤25MB/file and ≤100MB/PR under `tasks/`). A task that needs data ships a `data.lock` content-addressed manifest; the harness lazily fetches by `uri` scheme, verifies `sha256`, and caches under `$XDG_CACHE_HOME/brainpilot-bench/<sha256>/`.

| Field | Meaning |
|------|---------|
| `name` | dataset name (`[A-Za-z0-9._-]`; used as a cache temp filename) |
| `uri` | `oss://bucket/key` (public read-only, rewritten to a transfer-acceleration https endpoint), `https://…`, or `file://…` |
| `sha256` | 64-hex (lowercase) content hash — the cache key + integrity check |
| `bytes` | expected size (audit) |
| `format` | optional tag (parquet/csv/…) |

```bash
bp-bench fetch <taskId|all>   # resolve + verify + cache a task's datasets
```

See `tasks/_example/data.lock.example`. The public OSS endpoint defaults to `oss-accelerate.aliyuncs.com` (Alibaba Cloud transfer acceleration — anonymous public-read, no AK/SK; override with `OSS_PUBLIC_ENDPOINT`). Staging fetched data into the agent's workspace is handled by the runtime adapter (a later phase); `fetch` resolves + verifies + caches locally.

### LLM-judge scoring

Rubric scoring is done by an LLM judge speaking the Anthropic Messages API, configured **entirely via environment variables — never committed**. Bring your own provider (the official API, or any Anthropic-Messages-compatible gateway):

| Env var | Default | Meaning |
|---|---|---|
| `BPB_JUDGE_API_KEY` / `ANTHROPIC_API_KEY` | — | API key (sent as `x-api-key`) |
| `ANTHROPIC_AUTH_TOKEN` | — | OAuth-token alternative (sent as `Authorization: Bearer`) |
| `BPB_JUDGE_BASE_URL` / `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | provider endpoint |
| `BPB_JUDGE_MODEL` | `claude-opus-4-8` | judge model (override per run with `--judge-model`) |
| `BPB_JUDGE_VOTES` | `3` | number of judges; per-dimension scores aggregated by median |

`BPB_JUDGE_*` override `ANTHROPIC_*`, so the judge reuses your existing Anthropic config out of the box. **Never commit keys or endpoints** (use your shell env or a git-ignored `.env`). `scores.json` records only the judge model name (`judged by <model>`), never the endpoint or key. A judge refusal, parse failure, or missing credentials yields `unscored` (excluded from aggregates) — never a 0.

### Exec-script scoring (deterministic)

For tasks with a checkable answer, ship a grader with the task and score deterministically — no LLM judge:

```yaml
scoring:
  scorers:
    - kind: exec-script
      script: checks/check.sh   # task-relative; runs offline against the run bundle
      parser: json
```

`check.sh` runs in the run-bundle directory (produced artifacts under `./artifacts/`) and emits a single flat JSON object of `{metric: number}` between sentinels:

```bash
echo ">>>>> BPB_SCORES"
echo '{"accuracy": 0.83, "runtime_ok": 1}'
echo "<<<<< BPB_SCORES"
```

The grader ships **with the task** (`checks/`) and runs **offline on the captured bundle after the agent finishes** — the agent never sees it, so it cannot game it. Missing script, timeout, or no valid `BPB_SCORES` JSON → `unscored` (never 0). See `tasks/_example/exec-task/`.

**Execution isolation & trust boundary.** Exec scripts run through a pluggable `ExecSandbox`. The shipped implementation is a **local subprocess** (timeout-killed, confined to the bundle dir, credentials stripped). A local subprocess is **not** strong isolation:

> ⚠️ **Only run exec-script scoring on tasks you trust** (your own, or reviewed). A contributed task's `check.sh` is arbitrary code. Strong isolation (a Docker `ExecSandbox`: no-network, read-only mounts, non-privileged) is a documented seam — implement and select it before scoring third-party submissions at scale.

### Validating a task (contribution gate)

```bash
bp-bench validate <taskId|all>
```

Checks (all local — no credentials, deployment, or Docker needed):

- **Schema lint** — canary GUID first line, required fields, valid `created_at` (YYYY-MM-DD), non-empty `expected_artifacts`, no `..` path traversal, `category` exists in `categories.yaml`, declared `exec-script` has its `checks/` script, `gate.oracle_min > gate.nop_max`.
- **Two-sided validity gate** (for `exec-script` tasks shipping a `solution/solution.sh`): the **Oracle** (run the reference solution, then score) must **produce metrics** — proving the task is solvable and the grader isn't impossibly strict; an empty **NOP** submission must **fail to produce metrics** — proving the grader isn't trivially passable (the τ-bench "do-nothing scores 1.0" bug). No `solution/` → skipped with a warning.

> **NOP grader contract:** `check.sh` must **withhold** the `BPB_SCORES` sentinel when there are no artifacts, so an empty bundle comes back `unscored` rather than emitting a degenerate score. See `tasks/_example/exec-task/checks/check.sh`.

CI runs `validate all` + a canary check + the test suite on every PR touching `tasks/`, `categories.yaml`, `registry.json`, or `src/`. The real-model difficulty signal and rubric-judge Oracle (which need credentials / a deployment) are a later layer; this is the local, credential-free gate.

**Categories.** Each task declares a `category`; `categories.yaml` (repo root) maps each category to its required metric set, and the leaderboard groups by category into dense tables. Add a new category to `categories.yaml` before using it.

### Running against a live BrainPilot deployment

`bp-bench run` drives a task against a running BrainPilot over its runtime HTTP/SSE contract (pinned via `@brainpilot/protocol`), producing a run bundle that `score` then consumes offline:

```bash
bp-bench run <taskId|all> --base-url http://127.0.0.1:9001/api --version <engine-tag> \
  --out runs/ [--workspace-root <dir>]
bp-bench score runs/<taskId>-<version>/      # → scores.json
bp-bench leaderboard runs/
```

Each run directory holds `events.jsonl` + `signals.json` (auto-signals: completed / events / tool calls / errors / duration — context for ranking, **not** a quality verdict) + a blank `scoresheet.json` for optional human rubric review (+ `artifacts/` when `--workspace-root` is given). This path currently requires a BrainPilot-protocol system; for any other agent, use [Evaluate your own agent](#evaluate-your-own-agent).

### Frozen releases — `registry.json`

A **release** is an immutable, named snapshot of the task set — what a paper cites (`BrainPilotBench-v1`). It pins a git commit (and optionally a pushed ref/tag) plus each task at a specific `version`. The benchmark iterates slowly, so named snapshots (`v1`, `v2`, …) are the unit of comparability — not a rolling set.

```bash
bp-bench freeze BrainPilotBench-v1 --ref tested/2026-06-18   # snapshot current canonical tasks
bp-bench registry verify                                     # CI gate: every pin still holds
```

`freeze` records the current `git HEAD`, stamps its own `frozenAt` date (task `created_at` is self-reported and not trusted for this), and refuses to overwrite an existing release name — releases are immutable; cut a new one instead. `registry verify` fails loudly if a frozen task was deleted, re-versioned, or its commit isn't reachable — forcing a new release rather than silent drift. With no `registry.json` it's a no-op (exit 0).

`created_at` in each `task.yaml` is a validated provenance field; there is intentionally **no** date-cutoff leaderboard filter — at this scale, held-back tasks + named snapshots are the contamination control.

### Held-out evaluation (OOD)

Final scores should come from tasks the system **hasn't seen** — held-back, to measure generalization rather than overfitting to a public set. This never requires hiding the evaluation *method*: the scoring **mechanism is fully open** (`src/scorer/`, rubric dimensions, how a `check.sh` is written); only the held-out **instances** (a held-out task's prompt, its `solution/`, its concrete rubric values) are withheld.

A task declares `visibility: public | heldout` in `task.yaml` (default `public`). Held-out tasks live **outside the public repo** and are mounted at eval time via multi-root discovery:

```bash
bp-bench list                                    # public tasks only (default)
bp-bench list        --tasks tasks,/path/heldout --visibility all       # both
bp-bench leaderboard runs --tasks tasks,/path/heldout --visibility heldout   # held-out scores only
bp-bench freeze BrainPilotBench-heldout-v1 --tasks tasks,/path/heldout --visibility heldout
```

`list` / `leaderboard` / `freeze` default to `public`; `--visibility heldout|all` switches. A **misfiling guard** keeps held-out content out of the public repo: `validate` errors if a `visibility: heldout` task is found in a public task root (override with `--allow-heldout` when validating a private root).

Two ways to hold a task out, by task type:

- **No input data** (survey / synthesis / reasoning tasks — the prompt *is* the task): mark the whole task `visibility: heldout` and keep it in a private root. *(supported now)*
- **Data-driven** (analyze a private dataset): keep the prompt and grader **public**, but ship the dataset body via `data.lock` from **access-controlled** storage — the public can see how it's scored but can't fetch the data. *(planned next — authenticated `fetch`)*

> Out of scope: a Docker `ExecSandbox` for running *untrusted third-party* task scripts or agent code. The current model is that an agent runs in its own environment and returns a [submission bundle](#evaluate-your-own-agent); strong execution isolation is a separate, later concern (the `ExecSandbox` seam exists for it).

### Governance

Maintainer-led and curated — see [`CONTRIBUTING.md`](CONTRIBUTING.md). Proposals arrive as issues (no code); maintainers author and merge canonical tasks. The canonical surfaces (`tasks/`, `registry.json`, `categories.yaml`) are owned via [`.github/CODEOWNERS`](.github/CODEOWNERS); enable **branch protection + "require review from Code Owners"** on the default branch to enforce it.

---

*BrainPilotBench grew out of BrainPilot's internal quality-evaluation track and shares its plumbing in spirit (driver, demo-bundle replay, rubric format), but lives here as an independent, citable benchmark.*
