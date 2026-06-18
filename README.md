# BrainPilot Benchmark

A reproducible, contributable evaluation harness for multi-agent **scientific-research** tasks, run against a [BrainPilot](https://github.com/NeuroAIHub/BrainPilot) deployment.

Unlike a test suite (which答 pass/fail), a benchmark **scores and ranks**: it runs task instances, captures a replayable record, and collects human/LLM rubric scores so engine versions can be compared over time.

> Status: scaffold (v0.0.1). Framework + first neuroscience tasks; not yet a public leaderboard.

## What's here

```
@brainpilot/bench   — the framework (npm-publishable)
  task / loader     — task instance format + loading/validation
  runner            — drives a task against a deployment (thin layer over @brainpilot/protocol)
  scoring           — rubric scoresheet + leaderboard aggregation
  cli (bp-bench)    — list / run / leaderboard

tasks/              — the benchmark task set (the "contributed benchmark")
  neuro-survey-attention/      — write a survey outline on attention mechanisms
  neuro-trends-connectomics/   — analyze a decade of connectomics trends
```

The **framework** is generic (pin the contract via `@brainpilot/protocol`). The **task set** is the scientific value — that's what contributors add.

## Run

```bash
npm install && npm run build
# point at a running BrainPilot deployment
bp-bench list
bp-bench run all --base-url http://127.0.0.1:9001/api --version <engine-tag> --out runs/
# each run/ has events.jsonl + signals.json + a blank scoresheet.json
# humans/LLM fill scoresheet.json (1-5 per rubric dimension), then:
bp-bench leaderboard runs/
```

Auto-signals (completed / events / tool calls / errors / duration) are recorded for context and ranking, **but they do not决定 quality** — that's the rubric scores.

## Evaluating your own agent

The benchmark is split into **run** (collect your agent's output) and **eval** (score + rank).
The eval half is **system-agnostic**: any agent — any language, any harness — can be evaluated
today by producing a **submission bundle**, no live driving required.

```
<bundle>/
  meta.json            # {taskId, agent, taskVersion?, producedAt?, notes?}
  artifacts/           # your agent's outputs — must satisfy the task's expected_artifacts globs
  events.jsonl         # optional trace (reserved for future trajectory scoring)
```

Flow (see [`examples/submission/`](examples/submission) for a runnable template):

```bash
# 1. Pick + read a task: tasks/<id>/task.yaml (goal + expected_artifacts),
#    prompt/turns.yaml (the user turns to give your agent), rubric.yaml / checks/ (how it's judged)
bp-bench list
# 2. Run YOUR agent on the task's turns, in a workspace, producing the expected artifacts.
# 3. Assemble a bundle: write meta.json (taskId + agent) and drop the outputs in artifacts/.
bp-bench submit verify <bundle>    # check the bundle satisfies the task contract
# 4. Score (runs the task's DECLARED scorers — you don't pick them; anti-gaming):
bp-bench score <bundle>            #   · exec tasks: deterministic, no creds
                                   #   · rubric tasks: needs a judge model (ANTHROPIC_API_KEY / BPB_JUDGE_*); else unscored
bp-bench leaderboard <bundles-parent>   # per-category table; row = task@agent
```

> **Not yet automated:** `bp-bench run --base-url` only drives systems that speak BrainPilot's
> runtime HTTP/SSE contract. A one-command **`run` for any agent** needs the **SUT adapter**
> (next deliverable); until then, bring your own bundle as above. Scoring is run by maintainers
> for official leaderboard numbers (self-reported scores are gameable).

## Contributing a task

BrainPilotBench is **curated** — you propose a task via a *Task Proposal* issue (prose + data
pointers, **no code**), and maintainers author and integrate the canonical task. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for why (contamination + construct validity need editorial
judgment) and how. The anatomy below is what a maintainer authors when accepting a proposal.

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

Tasks live one-or-more levels under a task root; `--tasks dirA,dirB` discovers multiple roots
recursively. Directories whose name starts with `_` (e.g. `tasks/_example/`) are templates —
excluded from `list`/`freeze`, but still gated by `validate all`.

**Design a task so it tests a real research capability**, and prefer tasks that need no proprietary data (knowledge-organization / survey / trend tasks are ideal — see the two seed tasks). If a task needs data, reference it via `data.lock`, never commit the data.

## Large datasets — `data.lock`

Dataset bodies are **never committed to git** (CI enforces ≤25MB/file and ≤100MB/PR under `tasks/`). A task that needs data ships a `data.lock` content-addressed manifest; the harness lazily fetches by `uri` scheme, verifies `sha256`, and caches under `$XDG_CACHE_HOME/brainpilot-bench/<sha256>/`.

| Field | Meaning |
|------|---------|
| `name` | dataset name (`[A-Za-z0-9._-]`; used as a cache temp filename) |
| `uri` | `oss://bucket/key` (public read-only, rewritten to a transfer-acceleration https endpoint), `https://…`, or `file://…` |
| `sha256` | 64-hex (lowercase) content hash — the cache key + integrity check |
| `bytes` | expected size (audit) |
| `format` | optional tag (parquet/csv/…) |

Pull a task's datasets explicitly:

```bash
bp-bench fetch <taskId|all>
```

See `tasks/_example/data.lock.example`. Public OSS endpoint defaults to `oss-accelerate.aliyuncs.com` (Alibaba Cloud global transfer acceleration — anonymous public-read, no AK/SK; override with `OSS_PUBLIC_ENDPOINT`, e.g. a CDN custom domain). Note: staging fetched data into the agent's workspace is handled by the runtime adapter (a later phase); `fetch` resolves + verifies + caches locally.

## LLM-judge scoring

Rubric scoring is done by an LLM judge. The judge speaks the Anthropic Messages API and is configured **entirely via environment variables — never committed**. Bring your own provider (the official API, or any Anthropic-Messages-compatible gateway):

| Env var | Default | Meaning |
|---|---|---|
| `BPB_JUDGE_API_KEY` / `ANTHROPIC_API_KEY` | — | API key (sent as `x-api-key`) |
| `ANTHROPIC_AUTH_TOKEN` | — | OAuth-token alternative (sent as `Authorization: Bearer`) |
| `BPB_JUDGE_BASE_URL` / `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | provider endpoint |
| `BPB_JUDGE_MODEL` | `claude-opus-4-8` | judge model (override per run with `--judge-model`) |
| `BPB_JUDGE_VOTES` | `3` | number of judges; per-dimension scores are aggregated by median |

`BPB_JUDGE_*` override `ANTHROPIC_*`, so the judge reuses your existing Anthropic config out of the box, and you can point judging at a different provider when needed.

```bash
# scores a run bundle; without credentials, rubric scores come back `unscored` (never 0)
bp-bench score runs/<taskId>-<version>/
bp-bench score runs/<taskId>-<version>/ --judge-model claude-sonnet-4-6   # compare models
```

**Never commit keys or endpoints.** Put them in your shell env or a git-ignored `.env`. `scores.json` records only the judge model name (`judged by <model>`), never the endpoint or key. A judge refusal, parse failure, or missing credentials yields `unscored` (excluded from aggregates) — never a 0.

## Exec-script scoring (deterministic)

For tasks with a checkable answer, ship a grader with the task and score deterministically — no LLM judge. A task declares:

```yaml
scoring:
  scorers:
    - kind: exec-script
      script: checks/check.sh   # task-relative; runs offline against the run bundle
      parser: json
```

`check.sh` runs in the run-bundle directory (produced artifacts are under `./artifacts/`) and emits a single flat JSON object of `{metric: number}` between sentinels:

```bash
echo ">>>>> BPB_SCORES"
echo '{"accuracy": 0.83, "runtime_ok": 1}'
echo "<<<<< BPB_SCORES"
```

The grader ships **with the task** (`checks/`) and runs **offline on the captured bundle after the agent finishes** — the agent never sees the grader, so it cannot game it. Missing script, timeout, or no valid `BPB_SCORES` JSON → `unscored` (never 0). See `tasks/_example/exec-task/`.

### Execution isolation & trust boundary

Exec scripts run through a pluggable **`ExecSandbox`**. The shipped implementation is a **local subprocess** (timeout-killed, confined to the bundle dir, credentials stripped from its environment). A local subprocess is **not** strong isolation:

> ⚠️ **Only run exec-script scoring on tasks you trust** (your own, or reviewed). A contributed task's `check.sh` is arbitrary code. Strong isolation (a Docker `ExecSandbox`: no-network, read-only mounts, non-privileged) is a documented seam for running untrusted external tasks — implement and select it before scoring third-party submissions at scale.

## Validating a task (contribution gate)

Before a task PR is accepted, it must pass `bp-bench validate`:

```bash
bp-bench validate <taskId|all>
```

Checks (all local — no credentials, deployment, or Docker needed):
- **Schema lint** — canary GUID first line, required fields, non-empty `expected_artifacts`, no `..` path traversal (in artifact globs or scorer scripts), `category` exists in `categories.yaml`, declared `exec-script` has its `checks/` script, `gate.oracle_min > gate.nop_max`.
- **Two-sided validity gate** (for `exec-script` tasks shipping a `solution/solution.sh`): the **Oracle** (run the reference solution, then score) must **produce metrics** — proving the task is solvable and the grader isn't impossibly strict; an empty **NOP** submission must **fail to produce metrics** — proving the grader isn't trivially passable (the τ-bench "do-nothing scores 1.0" bug). A task with no `solution/` skips the gate with a warning.

> **Grader contract for the NOP side:** your `check.sh` must **withhold** the `BPB_SCORES` sentinel when there are no artifacts (empty submission), so an empty bundle comes back `unscored` rather than emitting a degenerate score. See `tasks/_example/exec-task/checks/check.sh`.

CI runs `validate all` (+ a canary first-line check) on every PR touching `tasks/`, `categories.yaml`, or `src/`. The real-model difficulty signal and the rubric-judge Oracle (which need API credentials / a deployment) are a later layer; this is the local, credential-free门禁.

### Categories

Each task declares a `category` (in `task.yaml`); `categories.yaml` (repo root) maps each category to its required metric set. The leaderboard groups by category into dense tables (see the architecture doc). Add a new category to `categories.yaml` before using it.

## Leaderboard

`bp-bench leaderboard <runsDir>` reads every `<runsDir>/*/scores.json` and prints **per-category dense tables** — one table per `category`, rows = `task@version`, columns = that category's required metrics (from `categories.yaml`).

Each cell is one of three states (never conflated):
- **scored** — a real value (median across runs of that task+version). rubric dimensions are normalized 1-5 → [0,1]; exec metrics pass through as-is.
- **unscored** — shown as `—`; the run produced no value for that metric (judge refusal, infra failure, or an unscored result). **Excluded from the aggregate — never counted as 0 or fail.**
- **not-applicable** — the metric isn't in the task's category, so it isn't a column at all.

Each cell also shows `(scored/total)` coverage (`scored` = runs that produced a valid value, ≤ total). Tasks declare a `version` in `task.yaml` (default `"unversioned"`); bump it on any breaking spec edit so leaderboard numbers stay comparable across versions.

**Scoring is run by maintainers, not self-reported** (self-reported numbers are gameable). For now the benchmark scores BrainPilot; evaluating an external system will go through a SUT-adapter seam (the next phase's critical path). Running scoring in-house also lets us hold part of the task set back — the strongest contamination defense.

## Frozen releases — `registry.json`

A **release** is an immutable, named snapshot of the task set — what a paper cites
(`BrainPilotBench-v1`). It pins a git commit (and optionally a pushed ref/tag) plus each task at
a specific `version`. The benchmark iterates slowly, so named snapshots (`v1`, `v2`, …) are the
unit of comparability — not a rolling set.

```bash
bp-bench freeze BrainPilotBench-v1 --ref tested/2026-06-18   # snapshot current canonical tasks
bp-bench registry verify                                     # CI gate: every pin still holds
```

`freeze` records the current `git HEAD`, stamps its own `frozenAt` date (task `created_at` is
self-reported and not trusted for this), and refuses to overwrite an existing release name —
releases are immutable; cut a new one instead. `registry verify` fails loudly if a frozen task
was deleted, re-versioned, or its commit isn't reachable (e.g. never pushed) — forcing a new
release rather than silent drift. With no `registry.json` it's a no-op (exit 0).

`created_at` in each `task.yaml` is a validated provenance field (contamination defense); there
is intentionally **no** date-cutoff leaderboard filter — at this scale, held-back tasks + named
snapshots are the contamination control, not date filtering.

## Governance

BrainPilotBench is maintainer-led and curated — see [`CONTRIBUTING.md`](CONTRIBUTING.md).
Proposals arrive as issues (no code); maintainers author and merge canonical tasks. The
canonical surfaces (`tasks/`, `registry.json`, `categories.yaml`) are owned via
[`.github/CODEOWNERS`](.github/CODEOWNERS); enable **branch protection + "require review from
Code Owners"** on the default branch in repo settings to enforce it.

## Relationship to the test platform

This benchmark grew out of BrainPilot's "B 线" (quality evaluation). The plumbing is shared in spirit with the test platform (driver, demo-bundle replay, rubric format) but lives here as an independent, citable benchmark — the engine repo's tests gate red/green, this ranks quality.
