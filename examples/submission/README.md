# Example submission bundle

A **template** for evaluating your own agent against a task — system-agnostic, no live
deployment needed. Produce a directory like this however your agent runs, then verify + score it.

```
submission/
  meta.json            # {taskId, agent, taskVersion?, producedAt?, notes?}
  artifacts/           # YOUR agent's outputs — must satisfy the task's expected_artifacts globs
    results.csv
  events.jsonl         # optional trace (reserved for future trajectory scoring)
```

This template targets the seed `example-exec-task` (a deterministic exec-script task). From the
repo root:

```bash
bp-bench submit verify examples/submission   # check the bundle satisfies the task contract
bp-bench score          examples/submission   # run the task's declared scorers → scores.json
bp-bench leaderboard    examples              # aggregate (row = task@agent)
```

Replace `taskId`/`agent` in `meta.json` and the files under `artifacts/` with your own. See the
README section **"Evaluating your own agent"** for the full flow.
