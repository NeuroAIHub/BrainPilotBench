# Alignment profile: four-question offline scaffold

This example implements the engineering path for task two: profile shape,
effect differences, observed-subject consistency, and replication on held-out
materials from the same subjects. It uses locally generated
score tables and the Python standard library (Python >=3.9). It does **not** load
a model, fit an encoding model, download data, or establish real Brain-Score/Agent
performance. It is excluded from the 112 canonical runnable tasks.

See [CONTRACT.md](CONTRACT.md), [protocol.json](protocol.json) and the
[development plan](../../../docs/alignment-task2-development-plan.md).

## Components

- `lib/fixtures.py`: nine small local scenarios, with varying deterministic seeds:
  peak, plateau, heterogeneous subjects, a single influential subject, changed
  confirmation ranking, lost baseline advantage, reversed advantage, missing
  confirmation, and a flat profile. Similar subject curves are constructed test
  cases, not evidence that real participants differ little.
- `lib/core.py`: numeric profile/comparison/stability calculations and fixture-only
  interpretation policy. No statistical significance or equivalence testing.
- `lib/service.py`: tool core and a minimal MCP stdio transport subset.
- `solution/reference_report.py`: scripted baseline that uses the actual stdio
  service and produces the same artifacts required of an Agent.
- `lib/grader.py`: data-only scorer, using separately supplied operator evidence.
- `lib/official_backend.py`: explicit unsupported real-data entry, without fallback.

No external MCP SDK is installed. Implemented protocol subset (2025-06-18):
initialize, initialized notifications, ping, tools/list and tools/call, with
structured tool results. No HTTP, auth, resources, subscriptions, sampling,
production host configuration or full MCP conformance claim is included.

Tools: `describe`, `profile`, `compare`, `stability`, `commit_selection`,
`generalization`. Development profiles expose all layers; there is no artificial
search quota. A 256-call session ceiling bounds fixture resource use. Confirmation
is unavailable through the profile tool and is revealed only after one immutable
selection. Sessions can resume from an operator journal. Tool calls fail with an
explicit error; they never invent a zero measurement. Stdout contains JSON-RPC
only. No tool accepts arbitrary code, paths, metric changes, or network requests.

Q3's `stability` tool returns each subject's highest/near-top layers and score gap,
plus leave-one-subject-out re-aggregation. Its scope is observed subjects; the
removals are not unseen-subject validation or independent CV folds. Exact winner
changes inside a near-optimal plateau do not count as removal sensitivity.
Q4's `generalization` tool retains its name but now specifically measures
replication on disjoint materials from the same subject cohort. It reports the
frozen layer's development/confirmation baseline differences, their change, and
its gap to the confirmation maximum. Baseline-advantage retention and near-optimal
membership are separate conclusions. No-confirmation cases test evidence limits.

The current task version is **0.2**, profile `synthetic-profile-descriptive-v2`,
answer schema `bpb-profile-answers/2`. Use new workspaces/operator sessions for
this version; old contexts and answer formats are rejected. See CONTRACT.md for
all fields and descriptive thresholds; these are not scientific effect criteria.

## Offline checks

Use existing Node dependencies and Python. Do not install/download anything for
this fixture. From the repository root:

```sh
npm run build
npm run test:alignment-profile
```

The test script runs Python checks and the complete CLI lifecycle:
prepare → manual run → MCP baseline → resume/collect → verify → score → leaderboard.
Generated arrays/tables, session logs and bundles live in temporary directories
and are removed after the checks. No benchmark result is published.

To inspect a session manually (choose a new directory):

```sh
TASK=tasks/_example/alignment-profile-synthetic
python3 -B "$TASK/lib/fixtures.py" --output /tmp/profile-session/packet.json --scenario plateau
python3 -B "$TASK/lib/service.py" --packet /tmp/profile-session/packet.json --journal /tmp/profile-session/journal.jsonl
```

The service consumes newline-delimited JSON-RPC on stdin. A real Agent host must
launch/configure that command explicitly. BrainPilotBench's `requires.mcp` field
does not automatically wire a server. The fixture smoke script acts as the host;
there is no installed global MCP plugin.

For offline data-only scoring, set `BPB_ALIGNMENT_PROFILE_EVIDENCE_DIR` to the
operator session directory **only for the scorer**, then run `bp-bench score` in
process mode. Only trusted evaluator code runs as a process; submitted JSON and
Markdown are read, never executed. `--official` and Docker inference mode are
not declared supported by this example. No Docker image is needed or pulled.

The operator evidence directory must be separate from the submission bundle.
Hash chains plus replay check contents but cannot authenticate a log that an Agent
can freely rewrite. Real task acceptance requires a launcher with enforced
operator/Agent storage separation. Do not label this local scaffold formally
isolated or OOD-validated. See VALIDATION.md for what was actually checked.

## Planned real-data integration

Consume task one's accepted cached features, held-out predictions and provenance
through a versioned backend adapter. Confirm numerical compatibility and scientific
aggregation before enabling it. The current descriptive margin and stability
rules must not silently become biological criteria. Keep subject identities fixed
for the material-replication question and split full passages/stories without
letting confirmation test responses enter selection, fitting or tuning. Implement and validate the
chosen uncertainty method, separate exploratory/confirmatory inference, and
calibrate task difficulty against a full-profile scripted baseline.
