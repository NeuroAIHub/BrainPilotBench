# Alignment task one: Pereira2018 analysis candidate

2026-11-02 update: the real server backend has been exercised on Linux with
official Pereira384 data and distilgpt2. See [SERVER_VALIDATION.md](../SERVER_VALIDATION.md),
[SERVER_RUNBOOK.md](../SERVER_RUNBOOK.md) and
[REAL_TASK1_CONTRACT.md](../REAL_TASK1_CONTRACT.md). This candidate remains
non-runnable in the canonical collection; explicitly staged server tasks have
version `0.1-server-draft` and do not constitute acceptance.

**Not runnable, not data accepted, no Agent results.** The objective is correct,
reproducible analysis of fixed cached representations and brain responses.
`analysis_success` measures implementation correctness, not the model's brain score.
Task two, layer search and MCP are outside this scope.

`contract.json` fixes the proposed submission interface and file roles.
`protocol.json` pins the planned upstream commit and records unresolved scientific
bindings as null. These fields block promotion; they must not silently acquire
synthetic defaults. Proposed model: Llama-3.2-1B, block 8 (zero based), last token.
The server record resolves model/tokenizer revisions externally; the candidate's
scientific bindings remain unset until the intended model is validated.

The runnable engineering example is [alignment-synthetic](../../_example/alignment-synthetic/README.md).
Its independently computed ridge results are synthetic-only and provide no evidence
of official Brain-Score equivalence. No placeholder task.yaml is registered here.

Remaining promotion work:

1. Repeat the distilgpt2 integration checks with the intended Llama model and
   retain its complete resolved environment and fold/prediction evidence.
2. Review and freeze the real assembly, ceiling, stimulus grouping, model/tokenizer
   revisions, context, truncation and precision in the candidate's scientific bindings.
3. Calibrate tolerances/resources on the final immutable image and complete
   isolation acceptance with an actual Agent process.
4. Connect the accepted official loader/reference to the trusted parent/worker
   seam, add real-data acceptance records, then create task.yaml/data.lock and
   promote the candidate through collection generation. Keep each rerun's X/Y
   visible to the program; reference answers and other cases stay parent-only.

The server integration record is engineering evidence for its stated model and
environment. It does not establish scientific acceptance or an Agent result.
