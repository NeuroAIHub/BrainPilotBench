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

## Contributing a task

A task is a directory under `tasks/<id>/`:

| File | Purpose |
|------|---------|
| `task.yaml` | id, domain, summary, `expected_artifacts`, `timeout_min`, `budget_tokens`, `requires` |
| `prompt/turns.yaml` | the user turns to inject — `[{send, then}]` |
| `prompt/ask_user.yaml` | (optional) preset answers for `ask_user` prompts (`pattern → answer`, `default`) |
| `env/env.patch.yaml` | (optional) deviations from baseline (image/model/mcp/gpu) |
| `env/setup.sh` | (optional) stage data into the workspace |
| `data.lock` | (optional) dataset URI + sha256 — **data body never committed** |
| `rubric.yaml` | scoring dimensions (1-5 + comment) |

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

## Relationship to the test platform

This benchmark grew out of BrainPilot's "B 线" (quality evaluation). The plumbing is shared in spirit with the test platform (driver, demo-bundle replay, rubric format) but lives here as an independent, citable benchmark — the engine repo's tests gate red/green, this ranks quality.
