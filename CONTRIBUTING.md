# Contributing to BrainPilotBench

BrainPilotBench is a **curated, maintainer-led** evaluation benchmark for multi-agent
scientific-research systems. It is **not** an open pull-request benchmark: the canonical
task set is authored and integrated by the maintainers. This is deliberate — keeping a
benchmark trustworthy requires editorial judgment on two axes that automation can't replace:

- **Contamination control** — is this task already public and memorizable? A leaked or
  widely-discussed problem measures recall, not capability.
- **Construct validity** — does the task actually measure the scientific-research skill it
  claims to, with a defensible rubric / grader?

So contribution happens as **proposals we review and integrate**, never as code that lands
automatically.

## How to propose a task

1. Open a **Task Proposal issue** (use the *Task proposal* issue template). Describe:
   - the scientific question / what a good answer looks like,
   - the category (or propose a new one),
   - expected artifacts,
   - the data source and rough size (data bodies never go in git — see `data.lock`),
   - a draft rubric (dimensions) or, for deterministic grading, what a check script would verify,
   - why it's unlikely to be contaminated (original? recent? not a famous published result?),
   - references.
2. **Do not** attach `task.yaml`, `check.sh`, `solution.sh`, or any executable code. Proposals
   are prose + data pointers. (This is also why CI never executes contributor-submitted shell:
   by the time anything runs, *we* wrote it.)
3. A maintainer evaluates the proposal, runs a contamination pre-check, and — if accepted —
   authors the canonical task directory, runs the validity gate (`bp-bench validate`), and
   merges. The authoritative commit is ours.

The canonical surfaces — `tasks/`, `registry.json`, `categories.yaml` — are protected
(`CODEOWNERS` + branch protection); nothing lands without maintainer review.

## Contamination pre-check (maintainers, before accepting a task)

- Web-search the exact question / expected answer / dataset — is it already public and easy
  to memorize? If so, reject or adapt.
- Set `created_at` honestly to the authoring date (provenance; `bp-bench validate` enforces it).
- Prefer original or recent material over famous published results.

## Scoring is run by maintainers

Leaderboard numbers are produced by us running the harness against a system, **not**
self-reported (self-reported scores are gameable). Accepting an external system to evaluate
will go through the SUT-adapter seam (next phase); until then the benchmark scores BrainPilot.
Keeping scoring in-house also lets us hold part of the task set back — the strongest
contamination defense there is.

## Three "versions" — don't conflate them

| Version | What it pins | Where |
|---|---|---|
| task `version` | one task's spec; bump on any breaking spec edit | `task.yaml` |
| registry release `BrainPilotBench-vN` | an immutable named snapshot of the whole task set | `registry.json` |
| npm `@brainpilot/bench@0.0.x` | the framework/harness code version | `package.json` |

A paper cites a **registry release** (`BrainPilotBench-v1`), which pins a git commit + each
task at a specific task `version`. `bp-bench registry verify` fails loudly if a frozen task
later drifts — forcing a *new* release rather than silent mutation.

## Local checks before a maintainer merges

```bash
npm install && npm run build
node dist/cli.js validate all      # schema + canary + created_at + Oracle/NOP gate
npm test
```

See `README.md` for the full command reference and `docs/design/` for the architecture.
