# Linux server validation — 2026-11-02

Scope: real Pereira384 data with **distilgpt2**, plus maintainer submissions for
the two experimental tasks. This is integration evidence, not scientific
acceptance or an Agent benchmark result. Canonical collection status is unchanged:
112 runnable tasks, 6 candidates; the real alignment candidate remains inactive.

## Environment and provenance

The checkout was `feat/alignment-task` at `3b96218`, with the fixes described below.
Host: Ubuntu 22.04, Python 3.11.18, Node 22.22.0, CPU execution; Docker exposes 2
CPUs. CUDA libraries are installed, but no GPU execution was used. The worker uses
Python 3.11.2. Both environments use these numerical package versions:

| Package | Version |
|---|---|
| brainscore-language | 2.3.0, Git commit `3b4fde5d6f53a69c652c7a1128397549995547b0` |
| brainscore-core | 2.5.0 |
| NumPy / SciPy | 1.26.4 / 1.17.1 |
| pandas / scikit-learn | 2.3.3 / 1.7.2 |
| Torch / Transformers | 2.6.0+cu124 / 4.57.6 |
| xarray | 2022.3.0 |

All data, weights, environments, submissions and detailed logs are outside Git at
`/tmp/bpb-alignment-server-20261102` (called `RUN` below). This is local temporary
storage, not a published or durable artifact archive. The full environment lock is
`RUN/python311/requirements.resolved.txt`, SHA-256
`e2834b1bbf5bcab89e92d1b2accac01fd71b39495a7fa895f46487c3d88dd433`.
`pip check` passed. Original Conda environments were not modified.

The validation worker was built offline from the existing local image
`brainpilot-sandbox-gpu:0.2.3`, reusing its Torch distribution and copying the
resolved Python dependency payloads and current adapters. It contains no model
weights, brain data or reference outputs. This validates that custom image, not
the network installation recipe in `Dockerfile.server`. Final image:

```
bpb-alignment-server-validation:20261102-py311-final
sha256:14d8fd6c25a24acc3eb72a7e45986ac8bab4699d831d6257997b290f9a814eaa
```

## Real data and numerical results

The official S3 assembly download was resumed after connection failures and
verified against upstream SHA-1 `f8434b4022f5b2c862f0ff2854d5b3f5f2a7fb96`
(35,604,141 bytes). The official loader downloaded and checked the ceiling chain.
After the upstream language-network / 384-sentence selection, the assembly has
384 stimuli, 12,155 neuroids and 9 subjects. The full downloaded assembly has
627 presentations and 13,553 neuroids.

Model and tokenizer: `distilgpt2` revision
`2290a62682d06624634c1f46a6ad5be0f47f38aa`, downloaded from Hugging Face's official
repository. All six blocks were cached in float32 with the official passage
prefix / last-token path. Cache: `RUN/distilgpt2-cache-v3`; manifest SHA-256:
`f6cc1194d94a9b3022c866fa0e503a984db5114a120d8a4f83ab6eeea0fe4e32`.

| Fixed-layer check (`transformer.h.5`) | Observed result |
|---|---|
| Raw official score | 0.07885228013320371 |
| Official ceiling | 0.13521249808656496 |
| Normalized score | 0.5831730146921874 |
| Traced versus untraced scalars | Equal |
| Live official entry versus cached scalars | Equal |
| Live versus cached prediction IDs, folds and selected alphas | Equal |
| Maximum absolute prediction difference | 0.0 |
| Train/test story separation | Disjoint in all 10 folds |

Evidence: `RUN/distilgpt2-reference-v3/{verification.json,results/}`,
`RUN/distilgpt2-live-trace/comparison.json`, and `RUN/structural-checks.json`.
`score-fixed --compare-live` took 101.46 seconds, peak host RSS 2,767,072 KiB.
Other validation jobs overlapped, so these observations are not resource limits
or CPU/GPU tolerance calibration. Atol=1e-6 and rtol=1e-5 remain provisional.

## Task workflows

Task1 passed the CLI manual/resume/verify/score path with the maintainer reference
submission: `analysis_success=1`. Both saved outputs and the Docker rerun matched
the parent's reference; inputs/source were unchanged. A Docker negative control
that added 0.1 to the normalized score received `analysis_success=0` with
`results/summary.json mismatch`. Both used 2 CPUs, 8 GiB and a 900-second limit,
with no network, read-only inputs/source and a non-root worker. Numerical package
and adapter source fingerprints matched between parent and image.

Evidence: `RUN/runs/task1-real-001`, `RUN/task1-positive-grade.json`, and
`RUN/task1-negative-grade/grade.json`. The final worker also passed all 34
synthetic Python checks (including Docker) and the synthetic CLI lifecycle in
`RUN/alignment-final-docker-test.log`. These synthetic checks do not add real-data
metamorphic coverage; do not interpret the model score as `analysis_success`.
Replaying the unsupported 4-CPU request after the fix produced
`state=scoring_failed`, `analysis_success=null`, recorded in
`RUN/task1-resource-failure/grade.json`.

Task2 used seed 17, confirmation fraction 0.2, five development folds and the
engineering margin 0.02. The split was saved before fitting: 304 development
stimuli / 19 story groups and 80 confirmation stimuli / 5 story groups, with
disjoint IDs and stories and the same 9 subjects. All six layers were computed.
Profile construction took 46.75 seconds, peak host RSS 1,825,720 KiB.

The actual stdio MCP maintainer client and CLI prepare/manual/resume/verify/score
path passed: `profile_analysis_success=1`, `four_question_score=1`. The selected
development maximum was block 2. A separate session confirmed that `generalization`
and direct confirmation profiling are rejected before commitment, and changing
the committed layer is rejected. Changing Q4's reported confirmation difference
gave `profile_analysis_success=0`, `four_question_score=0.75`.

Evidence: `RUN/distilgpt2-profile`, `RUN/runs/task2-real-001`,
`RUN/sessions/task2-real-001`, `RUN/task2-lock-check.log`, and
`RUN/task2-negative-bundle/alignment-profile-score.json`. This is the derived
subject/material protocol; it is not an official full-data Brain-Score total.
The same owner ran both sides of this maintainer check. Actual Agent/owner
filesystem separation and free-form report quality were not assessed.

## Fixes found by execution

1. Core 2.1 installed successfully but lacked `supported_data_standards`, required
   by the pinned Language source. Core 2.5.0 provides the API and passed imports.
2. Python 3.12 failed while opening the actual NetCDF because xarray 2022.3.0 uses
   the removed `entry_points().get` API. Bootstrap/runtime now require Python 3.11;
   the rejected 3.12 bootstrap was checked before installation.
3. Cached passage metadata placed `stimulus_id` inside a MultiIndex, conflicting
   with the official benchmark's coordinate assignment. Replay now unfolds that
   presentation index. Cached feature assemblies also retain the official
   recording coordinates so selecting a layer preserves the `neuroid` axis.
4. Docker rejected the draft's fixed 4-CPU quota on a 2-CPU daemon. CPU quota is now
   configurable and recorded. The evaluator inspects container state so a failed
   launch produces an infrastructure failure rather than an Agent zero. A program
   that actually starts and exits 125 still receives zero.

`python -B tasks/alignment/_shared/test_server.py` passes three targeted checks;
the coordinate/axis and failed-launch cases failed before their fixes. The
complete live/cache comparison above exercised the fixed adapters on real data.
Existing build, Node suite (248 passed, 3 skipped), Task2 suite (37 passed plus
MCP/CLI), collection, catalog and docs checks also passed during this server work.

## Remaining acceptance work

- Intended model `meta-llama/Llama-3.2-1B` (base, not Instruct), resolved revision
  `4e20de362430cd3b72f300e6b0f18e50e7166e08`: official config request returned 401.
  The user is configuring authorized Hugging Face access. No Llama inference has
  run, and distilgpt2 results do not substitute for it.
- Final portable dependency/image lock, scientific protocol review, calibrated
  tolerances and resource limits, GPU behavior, and isolation with an actual
  Agent remain pending. No canonical promotion, push, upload or formal Agent run
  was performed.

Reproduction commands are in [SERVER_RUNBOOK.md](SERVER_RUNBOOK.md). Use new output
directories after interrupted runs and keep operator artifacts outside the Agent
workspace. Earlier failed attempts and their logs remain in `RUN` for diagnosis.
