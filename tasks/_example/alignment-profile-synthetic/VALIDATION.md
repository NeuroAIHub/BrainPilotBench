# Local validation — 2026-10-23

## 2026-11-02 server-code handoff (not runtime validation)

The service, loader, reference client and grader now accept an explicit real-data
mode for a separately versioned, server-prepared packet. The no-fallback test was
updated for the new loader. At the user's request, **no test suite, data download,
model execution or environment installation was run on the Mac for this update**.
Only source/configuration syntax and consistency checks were performed. All pass
counts below refer to earlier revisions and do not validate the new code. Server
commands and remaining acceptance criteria are in `tasks/alignment/SERVER_RUNBOOK.md`.

Scope: **synthetic engineering checks only**. No neural dataset, model weights,
remote fixture, package, Docker image, or paid model was downloaded/called for this
change. Existing Node dependencies were reused locally. Python calculations use
only the standard library (tested with Python 3.9.6; Node 24.14.1).

## Q3/Q4 revision: task 0.2, descriptive profile v2

The revised Q3 measures observed-subject representativeness and sensitivity to
removing one subject. Q4 measures retention of baseline advantage and near-optimal
membership separately on disjoint materials from the same subject cohort. The
answer schema is now `bpb-profile-answers/2`; old contexts/answers are rejected.

Validated locally for this revision:

- `npm run build` passed.
- `npm run test:alignment-profile`: 37 Python checks passed, including all nine
  scenarios through the actual stdio MCP client and scorer. The CLI lifecycle
  (prepare/manual/resume/verify/score/leaderboard) also passed, including rejection
  of an old workspace context and binding to task version 0.2.
- Hand-computed checks cover per-subject gaps, one-person removal influence,
  plateau winner flips, confirmation baseline differences and their change.
- Regression cases distinguish baseline advantage from near-optimality, cover
  lost/reversed/no-development advantage and missing confirmation, and ensure
  confirmation uses the committed layer even when it is not the development winner.
- Cohort changes, overlapping materials, wrong baseline identity, unsupported
  unseen-subject claims and forged Q3/Q4 measurements are rejected.
- Existing Node regression: 223 passed, 0 failed, 3 skipped (the same two opt-in
  Docker tests and missing-dependency RSC check documented below).
- Documentation smoke, collection/catalog checks, task schema-only validation
  and diff whitespace checks passed. Canonical counts remain 112 runnable and
  6 candidate tasks.

No data, model, package or container image was downloaded. These are synthetic
engineering checks, not evidence of participant similarity, material independence
in real data, scientific effect thresholds, or actual Agent research performance.
The earlier validation records below describe task version 0.1.

## Initial scaffold checks (task 0.1)

- TypeScript build passed.
- `npm run test:alignment-profile`: 26 Python checks passed, plus the real CLI
  lifecycle with an actual stdio MCP subprocess passed.
- Existing Node tests: 223 passed, 0 failed, 3 skipped. Skips are two opt-in Docker
  isolation tests and one RSC test whose numerical Python dependencies are absent.
- Collection structure and catalog consistency passed: 112 canonical runnable
  tasks and 5 candidates. The new task is under `_example` and does not inflate
  the formal task collection.
- Documentation smoke passed (112 canonical tasks).
- Schema-only validation passed for all 114 discoverable task specs, including
  the original example and this synthetic example.

New checks cover all six fixture scenarios; hand-computed aggregation; ordering
invariance; missing/duplicate cells and nonfinite data; low-score correct reports;
confirmation-before-commit rejection; immutable selection across resume; wrong
numeric outputs; unsupported significance claims; correct not_evaluated answers;
false OOD labels; wrong/forged evidence; packet-bound answer reuse; journal
tampering and recomputation; missing artifacts and infrastructure; no-commit
failures; JSON validation; MCP handshake, notifications and error paths; and a
real backend that explicitly refuses synthetic fallback.

The scripted reference's four-question success is not an Agent benchmark result.
The free-form prose is not automatically assessed. Scores test the declared
descriptive fixture policy, not scientific hypothesis validity.

## Not yet verified

- A real Brain-Score data/prediction adapter or equality with official results.
- Scientifically calibrated uncertainty, significance, equivalence, or OOD claims.
- An actual research Agent using this task.
- Generic MCP-host interoperability beyond the implemented stdio subset and
  tested fixture client.
- Enforced Agent/operator filesystem isolation or authenticated journals. Hash
  chaining and recomputation do not establish trusted authorship.
- Real-data runtime/memory requirements or meaningful task difficulty relative
  to a full-profile scripted baseline.

No Docker worker is required by this grader because it never executes submitted
code; it reads bounded JSON and verifies it against operator-held evidence.

## Combined-branch validation

After integrating task one and task two on `feat/alignment-task`, both npm test
commands and CI steps are retained. The checks above describe the earlier
standalone task-two checkout. The combined checkout additionally passed:

- Task one: 33 Python checks passed, 1 opt-in Docker check skipped; CLI lifecycle
  and example Oracle/NOP checks passed.
- Task two: 26 Python checks and the MCP/CLI lifecycle passed.
- Existing Node regression: 223 passed, 0 failed, 3 skipped.
- Build, docs smoke, collection/catalog checks, all 115 task schemas, canary
  checks and diff whitespace checks passed.

The combined catalog has 118 records: 112 runnable tasks and 6 candidates,
including the task-one alignment candidate. Both synthetic examples remain
excluded from the canonical runnable count. No additional data or packages were
downloaded for integration.
