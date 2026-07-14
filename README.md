<div align="center">

<h1>🧠 BrainPilotBench</h1>

<p><strong>Evaluating Agents for Brain Science Research.</strong></p>

<p>
BrainPilotBench measures whether an agent can complete real brain science study,
produce the required research artifacts, and be scored in a transparent,
repeatable way.
</p>

<p>
  <a href="https://github.com/NeuroAIHub/BrainPilotBench/actions/workflows/validate.yml"><img src="https://github.com/NeuroAIHub/BrainPilotBench/actions/workflows/validate.yml/badge.svg" alt="Validation"/></a>
  <img src="https://img.shields.io/badge/status-v0-orange.svg?style=flat-square" alt="Status: v0"/>
  <img src="https://img.shields.io/badge/Node.js-%E2%89%A522-339933?style=flat-square&logo=node.js&logoColor=white" alt="Node.js >= 22"/>
  <img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="MIT license"/>
  <a href="https://github.com/NeuroAIHub/BrainPilotBench/stargazers"><img src="https://img.shields.io/github/stars/NeuroAIHub/BrainPilotBench?style=flat-square" alt="GitHub stars"/></a>
</p>

<p>
  <a href="#quick-start">Quick Start</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#evaluate-your-agent">Evaluate Your Agent</a> ·
  <a href="#task-suite">Task Suite</a> ·
  <a href="#scoring">Scoring</a> ·
  <a href="#contributing">Contributing</a>
</p>

</div>

---

BrainPilotBench is an open evaluation framework and curated task suite for
**agents conducting brain science research**. It evaluates systems that search
and synthesize neuroscience literature, analyze neural and behavioral data,
write code, produce figures and reports, and reason over scientific evidence.

The benchmark's domain scope is brain science, while its evaluation interface is
agent-agnostic. A system does not need to use BrainPilot, TypeScript, or any
particular agent architecture. If it can complete a BrainPilotBench task and
return a valid submission bundle, it can be evaluated.

> [!IMPORTANT]
> **Project status: v0.** The run, submission, scoring, validation, data-fetching,
> release-freezing, and leaderboard pipelines are implemented. The public task
> corpus is still small and growing, and there is not yet an official public
> leaderboard. The <code>@brainpilot/bench</code> package is not yet published to
> npm; use a source checkout for now.

## Why BrainPilotBench

| Real brain science research | Artifact-first evaluation | Comparable scoring | Integrity by construction |
|---|---|---|---|
| Tasks require neuroscience literature synthesis, neural data analysis, code, reports, figures, or structured results. | Agents are compared by the deliverables they leave behind, not by a required internal architecture. | LLM rubrics, human rubrics, and deterministic graders feed one task-declared scoring pipeline. | Canary markers, provenance dates, pinned datasets, frozen releases, and held-out task support reduce leakage and silent drift. |

BrainPilotBench is designed around a simple question:

> **Did the agent produce useful, verifiable brain science research artifacts under the task contract?**

That makes the benchmark suitable for multi-agent research systems, coding
agents, domain assistants, custom harnesses, and future systems applied to brain
science research.

## Quick start

### Prerequisites

- [Node.js](https://nodejs.org/) 22 or newer
- npm
- Git

Clone and build the framework:

~~~bash
git clone https://github.com/NeuroAIHub/BrainPilotBench.git
cd BrainPilotBench
npm install
npm run build
~~~

Commands below use <code>node dist/cli.js</code>, which works directly from the
source checkout. Optionally run <code>npm link</code> once and replace it with
<code>bp-bench</code>.

### Run the zero-key demo

The bundled example uses a deterministic grader. It needs no model API key, no
BrainPilot deployment, and no Docker environment.

~~~bash
node dist/cli.js submit verify examples/submission
node dist/cli.js score examples/submission
node dist/cli.js leaderboard examples
~~~

The three commands exercise the complete evaluation loop:

1. verify that the bundle satisfies the task contract;
2. run the scorers declared by the task;
3. aggregate the result into a category leaderboard.

You should see the example submission verified, an <code>exec-script</code>
score written to <code>examples/submission/scores.json</code>, and a
<code>rows_ok</code> result of <code>1.00</code>.

List the current canonical tasks:

~~~bash
node dist/cli.js list
~~~

## How it works

~~~mermaid
flowchart LR
    A["Task specification"] --> B["Agent or harness"]
    B --> C["Submission bundle"]
    C --> D["Contract verification"]
    D --> E["Task-declared scorers"]
    E --> F["Scores and coverage"]
    F --> G["Per-category leaderboard"]
~~~

A benchmark run has five layers:

1. **Task** — defines the brain science research goal, prompts, resource requirements,
   expected artifacts, data, and allowed scoring methods.
2. **Agent** — works in its own environment using its own model, tools, memory,
   and orchestration.
3. **Submission bundle** — captures the agent identity, produced artifacts, and
   optionally its event trace.
4. **Scoring** — runs only the scorers declared by the task. The submitting agent
   does not choose the easiest grader.
5. **Aggregation** — groups comparable metrics by task category and reports
   score coverage alongside values.

### Task anatomy

A canonical task is a directory under <code>tasks/</code>:

~~~text
tasks/<task-id>/
├── task.yaml             # identity, version, category, requirements, artifacts, scorers
├── prompt/
│   ├── turns.yaml        # turns delivered to the agent
│   └── ask_user.yaml     # optional preset answers for interactive prompts
├── rubric.yaml           # optional rubric dimensions
├── checks/               # optional deterministic grader
├── solution/             # optional maintainer-authored Oracle for validation
├── env/
│   ├── env.patch.yaml    # optional environment changes
│   └── setup.sh          # optional data staging
└── data.lock             # optional content-addressed dataset manifest
~~~

Directories beginning with an underscore, such as
<code>tasks/_example/</code>, are templates. They are validated but excluded from
canonical task listings and releases.

## Evaluate your agent

BrainPilotBench separates **running an agent** from **evaluating its brain science
research artifacts**. This is the main agent-agnostic interface.

### 1. Choose a task

~~~bash
node dist/cli.js list
~~~

Read:

- <code>tasks/&lt;id&gt;/task.yaml</code> for the goal and expected artifacts;
- <code>tasks/&lt;id&gt;/prompt/turns.yaml</code> for the prompts;
- the declared rubric or check scripts to understand the published evaluation
  method.

### 2. Run your agent

Give the task turns to your agent and let it work using its normal tools and
orchestration. Collect the files matching the task’s
<code>expected_artifacts</code> patterns.

BrainPilotBench does not require a particular message loop or agent API at this
stage.

### 3. Build a submission bundle

~~~text
my-submission/
├── meta.json
├── artifacts/
│   └── ... files required by the task ...
└── events.jsonl          # optional; reserved for trace and trajectory analysis
~~~

Example <code>meta.json</code>:

~~~json
{
  "taskId": "neuro-survey-attention",
  "agent": "my-research-agent@2026-07-13",
  "taskVersion": "0.1",
  "producedAt": "2026-07-13",
  "notes": "Optional run notes"
}
~~~

The <code>agent</code> value should identify the complete evaluated system:
harness version, configuration, or model combination as needed for
reproducibility.

### 4. Verify, score, and aggregate

~~~bash
node dist/cli.js submit verify path/to/my-submission
node dist/cli.js score path/to/my-submission
node dist/cli.js leaderboard path/to/submissions-parent
~~~

The first command checks the contract before grading. The second writes
<code>scores.json</code> inside the bundle. The third aggregates every scored
bundle under the supplied parent directory.

> [!NOTE]
> Official benchmark results will be produced by maintainers rather than
> accepted as self-reported numbers. Local scoring is intended for development,
> debugging, and reproducibility.

## Run against BrainPilot

BrainPilotBench includes a live adapter for systems implementing BrainPilot’s
runtime HTTP/SSE contract.

Start a BrainPilot deployment, then run:

~~~bash
node dist/cli.js run neuro-survey-attention \
  --base-url http://127.0.0.1:9001/api \
  --version "brainpilot@your-commit" \
  --out runs/
~~~

Score and aggregate the captured run:

~~~bash
node dist/cli.js score "runs/neuro-survey-attention-brainpilot@your-commit"
node dist/cli.js leaderboard runs/
~~~

A captured run can contain:

~~~text
runs/<task>-<version>/
├── events.jsonl          # normalized event trace
├── signals.json          # completion, event, tool, error, and duration signals
├── scoresheet.json       # blank or completed human-review sheet
├── artifacts/            # collected when --workspace-root is supplied
└── scores.json           # produced by the score command
~~~

Use <code>--workspace-root &lt;dir&gt;</code> when the BrainPilot workspace is
available to the harness and its artifacts should be collected automatically.

A generic live SUT adapter for arbitrary agents is planned. Until then,
non-BrainPilot systems should use the submission-bundle path above.

## Task suite

The current public task suite contains three canonical tasks.

| Task | Capability | Expected artifacts | Scoring |
|---|---|---|---|
| <code>neuro-survey-attention</code> | Organize a neuroscience survey of attention mechanisms and representative work | Markdown survey outline | Four-dimension LLM rubric |
| <code>neuro-trends-connectomics</code> | Analyze a decade of connectomics development and recurring themes | Markdown trend report | Default five-dimension LLM rubric |
| <code>neuro-rsc-place-cell</code> | Analyze RSC calcium-imaging and VR-belt data, including place-cell screening, decoding, trial-bin structure, and firing-rate dynamics | <code>benchmark_summary.json</code>, report, and PNG figures | Deterministic numerical checks plus human rubric |

The task corpus is intentionally curated rather than accepting arbitrary task
code. Scientific construct validity and contamination risk require editorial
review.

### Datasets

Large dataset bodies are not committed to Git. A task can declare a
<code>data.lock</code> manifest containing a URI, SHA-256 digest, expected byte
size, format, and an optional <code>scope: public|private</code>. Legacy entries
default to public. Private entries are evaluator-only and are never fetched by
an agent run.

Supported URI schemes include:

- <code>hf://</code> for Hugging Face repositories;
- <code>https://</code>;
- <code>file://</code> for local development.

Fetch and verify data with:

~~~bash
node dist/cli.js fetch neuro-rsc-place-cell
~~~

Fetch is public-only by default. Benchmark maintainers can explicitly fetch
gated evaluator inputs with <code>--private</code>; <code>--all</code> fetches
both scopes and should not be used in an agent environment.

Resolved datasets are cached by content hash under
<code>$XDG_CACHE_HOME/brainpilot-bench</code>, or
<code>~/.cache/brainpilot-bench</code> by default.

The current runner can fetch datasets with <code>run --fetch</code>, but task
workspace staging is still adapter-specific. Check the task’s
<code>env/setup.sh</code> before running a data-backed task.

## Scoring

### Declared scorers

Each task declares its scorer set. BrainPilotBench currently supports:

| Scorer | Best for | Output |
|---|---|---|
| <code>rubric-judge</code> | Scientific writing, synthesis, and qualitative analysis | Integer scores from 1–5 per rubric dimension, aggregated across judge votes |
| <code>rubric-human</code> | Dimensions requiring expert scientific review | Human-entered rubric scores |
| <code>exec-script</code> | Deterministic, machine-checkable outputs | Flat numerical metrics emitted by a trusted task script |

Rubric scores are normalized to <code>[0, 1]</code> for leaderboard aggregation.
Deterministic numerical metrics pass through unchanged.

### Three-state leaderboard semantics

A leaderboard cell is one of three states:

| State | Meaning | Aggregate behavior |
|---|---|---|
| **Scored** | A valid score was produced | Included |
| **Unscored** | Output, credentials, judge response, or infrastructure did not produce a valid score | Excluded; never converted to zero |
| **Not applicable** | The metric is outside the task category contract | Not represented as a required cell |

This distinction is load-bearing. A low score means the agent performed poorly.
An unscored run means the benchmark did not obtain a valid measurement. Treating
both as zero would confound system capability with evaluation failure.

Leaderboard cells also report coverage as <code>scored/total</code>. Multiple
runs of the same task and system are aggregated by median, with at most one vote
per run for each metric.

### Configure an LLM judge

Rubric judging uses an Anthropic Messages-compatible API.

| Environment variable | Purpose |
|---|---|
| <code>BPB_JUDGE_API_KEY</code> or <code>ANTHROPIC_API_KEY</code> | API key |
| <code>ANTHROPIC_AUTH_TOKEN</code> | Bearer-token alternative |
| <code>BPB_JUDGE_BASE_URL</code> or <code>ANTHROPIC_BASE_URL</code> | API endpoint |
| <code>BPB_JUDGE_MODEL</code> | Judge model |
| <code>BPB_JUDGE_VOTES</code> | Number of judge votes; default 3 |

The <code>BPB_JUDGE_*</code> variables take precedence. Credentials and provider
endpoints must remain in shell environment variables or a git-ignored
<code>.env</code>; never commit them.

A judge refusal, malformed response, missing credential, or infrastructure error
produces an **unscored** result rather than a zero.

### Deterministic graders and trust

An <code>exec-script</code> grader emits a flat JSON object between
<code>BPB_SCORES</code> sentinels:

~~~bash
echo ">>>>> BPB_SCORES"
echo '{"accuracy": 0.83, "runtime_ok": 1}'
echo "<<<<< BPB_SCORES"
~~~

Graders execute after the agent finishes, against the captured bundle.

> [!WARNING]
> The current <code>ExecSandbox</code> implementation is a local subprocess with
> a timeout, a constrained working directory, and stripped credential
> environment variables. It is **not strong isolation**. Run deterministic
> graders only from trusted, reviewed tasks. A no-network Docker sandbox is on
> the roadmap.

## Integrity and reproducibility

BrainPilotBench uses several complementary controls:

- **Canary markers** — task files carry unique markers to help detect benchmark
  material in training corpora.
- **Creation provenance** — every canonical task has a validated
  <code>created_at</code> date.
- **Content-addressed data** — dataset bodies are pinned by SHA-256.
- **Two-sided task validation** — deterministic tasks can prove that an Oracle
  produces scores while a do-nothing submission does not.
- **Maintainer-run official scoring** — official numbers are not accepted from
  self-reported submissions.
- **Frozen releases** — named releases pin both a Git commit and task versions.
- **Held-out roots** — private task instances can be mounted at evaluation time
  without hiding the public scoring framework.

### Validate the task set

~~~bash
node dist/cli.js validate all
node scripts/check-task-canary.mjs
node dist/cli.js registry verify
~~~

Validation checks schema fields, task categories, artifact patterns, scorer
files, canaries, provenance, path traversal, and applicable Oracle/NOP gates.

### Freeze a release

A named release is the citable unit of comparability:

~~~bash
node dist/cli.js freeze BrainPilotBench-v1 --ref tested/your-tag
node dist/cli.js registry verify
~~~

Release names are immutable. If a task specification changes, bump the task
version and create a new release rather than silently rewriting an existing
benchmark snapshot.

### Held-out evaluation

Public commands default to public tasks:

~~~bash
node dist/cli.js list
~~~

Maintainers can mount private held-out roots explicitly:

~~~bash
node dist/cli.js list \
  --tasks tasks,/path/to/heldout \
  --visibility all
~~~

Held-out releases must use an explicit private registry path. The CLI refuses to
write held-out task identifiers into the default public
<code>registry.json</code>.

## Repository layout

~~~text
BrainPilotBench/
├── src/                  # framework, CLI, runner, scorers, validation, registry
├── tasks/                # canonical public task set
├── examples/             # agent-agnostic example submission
├── scripts/              # repository validation helpers
├── categories.yaml       # category-to-required-metrics registry
├── CONTRIBUTING.md       # proposal and governance policy
└── .github/              # CI, issue templates, ownership, notifications
~~~

The framework and task suite have different responsibilities:

- <code>src/</code> defines how systems are run, verified, scored, and compared;
- <code>tasks/</code> defines the brain science research work being measured;
- <code>categories.yaml</code> defines which metrics are comparable within each
  leaderboard section.

## Build on BrainPilotBench

### Integrate a new agent today

Use the submission-bundle contract. It is stable across languages and does not
require a live adapter.

A wrapper only needs to:

1. read the task and prompts;
2. run the agent;
3. copy expected deliverables into <code>artifacts/</code>;
4. write <code>meta.json</code>;
5. call <code>submit verify</code> and <code>score</code>.

### Add a live adapter

The existing runner targets BrainPilot’s HTTP/SSE runtime contract. A generic
system-under-test adapter is the next framework milestone. New adapters should
preserve the agent’s native action loop while returning the same run-bundle
contract used by offline submissions.

## Roadmap

Near-term priorities are:

- expand the curated public and held-out brain science task sets;
- add a generic live SUT adapter for non-BrainPilot agents;
- add strong Docker isolation for deterministic grader execution;
- add authenticated dataset fetching for private data-backed evaluations;
- publish the first immutable benchmark release;
- open the official leaderboard after sufficient task and run coverage;
- publish <code>@brainpilot/bench</code> after the CLI contract stabilizes.

Roadmap items are plans, not current capabilities.

## Contributing

BrainPilotBench is maintainer-led and curated.

To propose a task, open a
[Task Proposal issue](https://github.com/NeuroAIHub/BrainPilotBench/issues/new?template=task-proposal.yml)
with:

- the scientific question and intended capability;
- expected artifacts;
- data sources and approximate size;
- a draft rubric or deterministic metric;
- contamination considerations;
- relevant references.

Do not submit task implementations, graders, or solutions in the proposal.
Maintainers review construct validity and contamination risk, then author and
validate the canonical task.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete policy.

### Development checks

~~~bash
npm install
npm run build
npm test
node dist/cli.js validate all
node scripts/check-task-canary.mjs
node dist/cli.js registry verify
~~~

CI runs the build, tests, canary checks, task validation, registry validation,
and task-size limits on relevant changes.

## Citation

A formal citation will accompany the first frozen public release. Until then,
cite the repository and include:

- the repository URL;
- the evaluated Git commit;
- each task ID and task version;
- the evaluated agent/harness configuration;
- the judge model and vote count where applicable.

This information is necessary to make results interpretable before a formal
benchmark release exists.

## Community

- [Open an issue](https://github.com/NeuroAIHub/BrainPilotBench/issues)
- [Explore BrainPilot](https://github.com/NeuroAIHub/BrainPilot)
- [Join the BrainPilot Feishu community](https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=0far82db-f790-412e-9217-58ae67df4313)
- Contact: [thu_neuroai@mail.tsinghua.edu.cn](mailto:thu_neuroai@mail.tsinghua.edu.cn)

## License

The package metadata currently declares the framework as MIT licensed.

<!-- TODO before public release: add and link a top-level LICENSE file. -->

---

<div align="center">

**Build agents for brain science research that can be tested, compared, and trusted.**

</div>
