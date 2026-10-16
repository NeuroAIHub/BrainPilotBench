# Anatomical Connectivity and Signal Propagation in C. elegans

[BrainPilotBench v1](../../../README.md#task-suite) · [Data lock](data.lock) · [Task specification](task.yaml)

How closely does anatomical wiring match measured signal propagation in C. elegans?
The agent quantifies differences between a connectome and a signaling atlas using
a fixed analysis protocol. It compares connections, communities, hubs, and
pharyngeal organization.

The evaluator runs the submitted analyzer on additional reconstructions and
compares its outputs with independent calculations. The task measures differences
between the networks, not predictions of one network from the other.

> [!NOTE]
> **Agent benchmark results: not yet available.**
> Public data and evaluation code are available. The reference implementation checks below are separate from agent benchmark results.

## Task at a glance

| Field | Details |
|---|---|
| Task ID | `celegans-structure-function-divergence` |
| Task version | `0.6` |
| Public data | A signal propagation atlas, one anatomical connectome reconstruction, and neuron metadata |
| Submission | A reusable Python analyzer, a protocol declaration, and a scientific report |
| Primary metric | `score` in [0, 1]: numerical-statistic agreement weighted by judgment skill, higher is better |
| Evaluation | Statistics and judgments checked on evaluator-controlled reconstructions |

The automatic score is `stat_match_rate × (0.5 + 0.5 × judgment_skill)`.
It rewards agreement with reference statistics and correct judgments across evaluated reconstructions.
Judgment skill adjusts accuracy relative to the best constant answer for each question.
`stat_match_rate`, `judgment_accuracy`, and `judgment_skill` are also reported as diagnostics.
The author rubric in `rubric.yaml` and `rubric.md` supports separate qualitative
review. It does not alter the automatic score.
The full protocol and required statistics are in [the task prompt](prompt/turns.yaml).

## Inputs and provenance

`data.lock` lists three public and three evaluator-only source files with expected byte counts and SHA-256 hashes. The scripts under `env/` build the public and private arrays from those sources. A private evaluator directory must be provided through `BPB_PRIVATE_EVAL_DIR` outside the task and Agent workspace. The evaluator has no task-local private-data fallback.

The three public sources are mirrored at the immutable Hugging Face revision in `data.lock`.
From the repository root, run `node dist/cli.js fetch celegans-structure-function-divergence --public`.
Their sizes and SHA-256 hashes are unchanged from the pinned upstream sources.
Evaluator-only sources and generated arrays remain outside this public data publication.

## Submission and scoring boundary

Required artifacts are `report.md`, `divergence/divergence_analysis.py`, and `divergence/contract.json`. The trusted scorer checks the contract and computes its reference result in the parent process. Submitted Python runs only in a separate Docker worker that mounts the submitted artifacts read-only and receives one reconstruction's input arrays. It has no network, no evaluator source, no private directory mount, and no Docker socket. An extra `oracle_mode.flag` does not activate any scoring branch.

The worker image uses Python 3.13 and the package pins in `env/requirements.txt`; official scoring should identify the built image by immutable digest. `checks/worker.Dockerfile` and `checks/worker_entry.py` define that image. `solution/solution.sh` writes the author's reference analyzer. It is graded through the same genuine input and Docker worker path as any other submission.

<a id="integration-checks"></a>

## Reference implementation checks

The task-local `INTEGRATION.md` records the source snapshot, pinned source hashes, image digest, exact validation commands, observed objective result, negative gate, and remaining limits. These checks validate the candidate pipeline; they do not constitute an Agent comparison or production release.

<details>
<summary>Source and integration record</summary>

This task was imported from author contribution revision 1, scientific task version 0.6.
The integration changes its execution boundary and public text, not its scientific protocol.
The original contribution remains in the workflow snapshot recorded in [INTEGRATION.md](INTEGRATION.md).

`task.yaml` keeps the author's version 0.6, with `integration_status: candidate`.
Any later scientific protocol change requires a separately reviewed task version.
Task collection metadata and launch instructions are controlled at the repository level.
Public data publication is separate from a benchmark release or agent evaluation.

</details>
