# C. elegans structure–function divergence

Integration status: candidate. This task was imported from author contribution revision 1, scientific task version 0.6. The integration modifies its execution boundary and public text; it is not an accepted benchmark release. The original contribution remains in the workflow snapshot recorded in `INTEGRATION.md`.

The agent receives one public reconstruction of a measured C. elegans signaling atlas and an electron microscopy connectome. It writes a reusable Python analyzer, a protocol declaration, and a short report. The analyzer computes edge ranking, community agreement, hub agreement, and pharyngeal co-assignment. The evaluator applies it to other reconstructions and compares its output with an independently computed result. Public instructions are in `prompt/turns.yaml`.

The primary metric is `score` (fraction, maximize). `stat_match_rate`, `judgment_accuracy`, and `judgment_skill` are diagnostics. The author rubric in `rubric.yaml` and `rubric.md` is retained for separate qualitative review and is not an automatic scoring component of this candidate.

## Inputs and provenance

`data.lock` lists three public and three evaluator-only source files with expected byte counts and SHA-256 hashes. The scripts under `env/` build the public and private arrays from those sources. A private evaluator directory must be provided through `BPB_PRIVATE_EVAL_DIR` outside the task and Agent workspace. The evaluator has no task-local private-data fallback.

Source availability and content hashes were checked during integration. Licenses and redistribution terms still require maintainer review before publication. The names and locations of evaluator-only sources in `data.lock` do not make their generated arrays available to the Agent.

## Submission and scoring boundary

Required artifacts are `report.md`, `divergence/divergence_analysis.py`, and `divergence/contract.json`. The trusted scorer checks the contract and computes its reference result in the parent process. Submitted Python runs only in a separate Docker worker that mounts the submitted artifacts read-only and receives one reconstruction's input arrays. It has no network, no evaluator source, no private directory mount, and no Docker socket. An extra `oracle_mode.flag` does not activate any scoring branch.

The worker image uses Python 3.13 and the package pins in `env/requirements.txt`; official scoring should identify the built image by immutable digest. `checks/worker.Dockerfile` and `checks/worker_entry.py` define that image. `solution/solution.sh` writes the author's reference analyzer. It is graded through the same genuine input and Docker worker path as any other submission.

`task.yaml` keeps the author's version 0.6, with `integration_status: candidate`. Any later scientific protocol change requires a separately reviewed task version. Task collection metadata and launch instructions are controlled at the repository level.

## Integration checks

The task-local `INTEGRATION.md` records the source snapshot, pinned source hashes, image digest, exact validation commands, observed objective result, negative gate, and remaining limits. These checks validate the candidate pipeline; they do not constitute an Agent comparison or production release.
