# Alignment task one: Pereira2018 analysis candidate

2026-11-02 update: the real server backend is implemented as an **untested server
draft**. See [SERVER_RUNBOOK.md](../SERVER_RUNBOOK.md) and
[REAL_TASK1_CONTRACT.md](../REAL_TASK1_CONTRACT.md). No dependencies, model weights
or neural data were downloaded for this implementation. This candidate remains
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
No model/tokenizer revision was resolved online in this offline phase.

The runnable engineering example is [alignment-synthetic](../../_example/alignment-synthetic/README.md).
Its independently computed ridge results are synthetic-only and provide no evidence
of official Brain-Score equivalence. No placeholder task.yaml is registered here.

Future entry points:

1. Implement `../_shared/official_backend.py::run_official` against the pinned
   Brain-Score Language commit, with a complete dependency lock and fold/prediction
   tracing. Prove original-entry vs traced-entry equality before accepting it.
2. Prepare real inputs in an external directory: retain the official assembly's
   coordinates/missingness and original ceiling object; freeze stimulus grouping,
   model/tokenizer revisions, context, truncation and precision. Implement a
   separate official packet loader; do not relabel synthetic NPY as a lossless
   NetCDF export without evidence.
3. Compare live model vs cached representations for passages and the full experiment;
   record raw, ceiling and normalized outputs and source/file hashes. Calibrate
   tolerances/resources on the target CPU image.
4. Connect the accepted official loader/reference to the trusted parent/worker
   seam, add real-data acceptance records, then create task.yaml/data.lock and
   promote the candidate through collection generation. Keep each rerun's X/Y
   visible to the program; reference answers and other cases stay parent-only.

No downloading, inference, official backend execution or real-data acceptance has
occurred in this change. The upstream method is a planned binding, not a verified
reimplementation in this repository.
