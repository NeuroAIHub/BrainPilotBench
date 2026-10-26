# BrainPilotBench v1 task collection

[Task suite](../README.md#task-suite) · [EEG](../tasks/eeg/README.md) · [Psychology](../tasks/psychology/README.md) · [Public data](data-preparation.md)

BrainPilotBench brings brain-science and behavioral research tasks into one shared collection.
Each task describes the problem, available data, required outputs, and evaluation method.
Researchers can use the same task definitions with different agents and research workflows.
The v1 collection has 112 runnable tasks: 108 additions and four retained v0 tasks.
The additions form one collection, not separate benchmark versions based on their upload dates.

> [!IMPORTANT]
> **Agent benchmark results for the 108 new v1 tasks are not yet available.**
> Task data access and evaluation code are available. Representative reference checks are not agent benchmark results.
> Published BrainPilotBench-v0 results cover the four original tasks only.

Invasive recordings is one v1 data category with seven tasks and version-bound acceptance records.
All seven have checked public-validation workflows and frozen-reference owner Test interface checks.
They have no Agent benchmark results.

AgentEEGBench, Psych101-Agent-Bench, and future specialized research benchmarks
remain independent projects. They can reuse a task at a fixed Git commit and version.
Their agents, experiment scheduling, credentials, and research records stay separate.
This repository does not add a top-level `runtimes/` layer.

## Layout and identity

| Data category | Total tasks | New in v1 | Research tasks |
|---|---:|---:|---|
| [EEG](../tasks/eeg/README.md) | 25 | 23 | EEG classification, including two retained v0 protocols |
| [Psychology](../tasks/psychology/README.md) | 76 | 76 | Behavioral models with categorical or byte-sequence responses |
| [MRI](../tasks/mri/brain-age-mri/README.md) | 2 | 1 | Structural-MRI age prediction and the retained TOPS fMRI task |
| [Connectomics](../tasks/connectomics/celegans-structure-function-divergence/README.md) | 1 | 1 | Anatomical connectivity and signal propagation in C. elegans |
| [Calcium imaging](../tasks/calcium-imaging/neuro-rsc-place-cell/README.md) | 1 | 0 | The retained RSC place-cell task |
| [Invasive recordings](invasive-task-preparation.md) | 7 | 7 | Clinical ECoG/sEEG and intracortical movement, muscle, handwriting, and birdsong decoding |
| **Total** | **112** | **108** | **Includes four retained v0 tasks.** |

The five EEG candidates remain outside the 112 runnable tasks.
Invasive recordings groups `tasks/ieeg/` and `tasks/intracortical/` under one reader-facing category.
Their canonical directories and catalog domain identifiers remain distinct.
The v1 collection name does not replace task protocol versions or change their scoring contracts.

Use task IDs in CLI commands; directory moves do not change them. Old directory
paths in external scripts must be updated. The four original task YAML files
keep their scientific versions. `bciciv-2a` and `eeg-mi-bnci2014` share a source
dataset but have different splits, submission interfaces and scores. Do not merge
their results. The same rule applies to future Sleep-EDF and MRI variants.

Each executable task has a README, task YAML, prompt, data lock, environment
preparation and scorer entry. Candidate metadata has no `task.yaml`, so automatic
discovery cannot mistake it for an executable task. The catalog records all
entries and their status; it does not publish research performance rankings.
The catalog's `data_access` describes public Agent inputs.
`private_data_access`, when present, describes the separate evaluator data route.
For 29 hosted evaluator packages, `private_score_entry` identifies the explicit private scoring route.
The default evaluation scope and scientific versions remain unchanged.

## Data and environment

Large arrays and MRI files stay outside Git. The unified data layout uses
`tasks/<category>/<task-id>/public/` at [Hugging Face revision `f50618208e3e748a8a16dfb6138e335f033d603c`](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/f50618208e3e748a8a16dfb6138e335f033d603c/tasks).
The collection hosts public data for 111 tasks, including BCI IV-4 and the four retained v0 tasks.
H1 remains source-only under its source Data Use Agreement.
Each task guide explains the inputs, split, source terms, and required environment.
The [data preparation record](data-preparation.md) preserves the fixed snapshots, transfer checks, and historical publication details.

Run `node dist/cli.js prepare <task-id> --fetch --workspace /absolute/outside-git/workspace` for one hosted task.
The CLI verifies the pinned public files and copies mapped paths into `<workspace>/.bpb/public-data/`.
Setup receives that root as `BPB_PUBLIC_DATA_ROOT`. Task-specific Python variables can still be required.
BCI IV-4 and the four hosted FALCON scorers use staged `<workspace>/public_data`.
The film scorer instead requires the owner-held evaluator data and block mapping in a trusted process.
Unset `BPB_LOCAL_DATA_ROOT` before starting an Agent. Keep public and evaluator caches separate.
The launcher rejects a private cache visible to an Agent.

The earlier [101-task snapshot](data-preparation.md#historical-first-batch) and five-task invasive snapshot remain historical delivery evidence.
They are not the recommended task download paths. Their successful checks do not establish delivery of the unified revision.

The film package is available without a key. Regenerating its exact opaque IDs and hashes requires the owner's private shuffle key.
Its `owner_key_bound_prepared_export` status describes that rebuild constraint, not restricted access to the prepared public files.
The trusted film scorer still needs evaluator mappings, which are not part of the public package.

Each task owns its environment instructions. CPU Docker images are built locally
and evaluated by immutable ID/digest; no images were published. A successful
macOS/arm64 integration run does not verify Linux/amd64 or GPU compatibility.

## Private evaluation

The [maintainer workflow](private-evaluation.md) connects the hosted private snapshot to preparation and isolated Test scoring for 29 tasks.
It includes 21 EEG tasks, six invasive tasks, brain-age MRI, and C. elegans.
Private files stay in a separate owner cache and evaluator directory.
Completed submissions are frozen before scoring; Test results use a separate result file.
Source-only and retained legacy tasks keep their documented routes.

<a id="low-cost-validation"></a>

## Reference implementation checks

The initial four reference implementations checked representative evaluation paths: native EEG
BCI-IV-2a, Psych Lefebvre exp1, C. elegans and brain age. Those EEG and Psych checks used public
train/valid only; historical private Test results were not replayed. The two new
contributions use their own reference-evaluation paths. These runs check data,
environment, saved artifacts, inference and scoring; they are not Agent research
experiments. No paid model calls are needed.

The [invasive task checks](invasive-task-preparation.md)
cover real source preparation, public staging, fixed submissions, and isolated container scoring.
Owner Test checks use a frozen reference and return separate engineering reports.
They do not tune a model or contribute Agent leaderboard scores.
Each promoted entry has an `acceptance.json` that binds its version and critical files.
The catalog refuses to reuse acceptance after those files change.
The original `acceptance.json` records remain evidence for the scientific and reference checks on the earlier task definitions.
Six invasive `delivery-acceptance.json` records bind the updated public locks, setup bridge, and hosted revision to the [delivery report](../reports/unified-public-delivery-20261015.json).
They do not imply that the reference, Agent, or owner Test runs were repeated.
The later private-data integration preserves these original records and adds a separate, scope-limited delivery record.
New reference checks cover selected private workflows, not all tasks or comparative Agent performance.

The historical 101-task snapshot has full byte-level readback.
The earlier invasive snapshot has metadata checks, representative anonymous downloads, and one complete M2 download/setup check.
Those historical checks do not verify the new layout or rerun Agent experiments across v1.
Other family members have structure and contract checks. Some also have input
checks against real public data. Four EEG entries remain preparation-only.
HMC stage and Sleep-EDF onset have public candidate packages, but no runnable
task contracts.
Thielen2021 remains withheld under the earlier research scope choice. A checked
schema is not evidence of a completed data run. New Psych sequence interfaces
have a separate metric version. They do not inherit historical token-based scores.

Run inexpensive checks from the repository root:

```bash
npm ci
npm run build
npm test
npm run test:collection
npm run catalog:check
npm run test:invasive-metadata
npm run test:docs
```

`test:collection` checks task IDs, paths, required files, metadata and metric
directions. It does not fetch data, install Python environments, train models, or
launch all reference solutions. Real-run commands and evidence are documented in
each representative task and [the reference-check record](integration-validation.md).
The invasive metadata gate also checks acceptance-file coverage and rejects stale code or environment bindings.
CI uses ordinary metric, byte-transfer, and metadata fixtures; it does not download research data or replay owner Test runs.

Use `evaluation.primary_metric` to declare the ranking metric, direction and
unit. Diagnostic counts are not ranking scores. Results record task version
separately from Agent version and never aggregate across protocol versions.
`timeout_min: null` and `budget_tokens: null` leave research budgets unrestricted;
each scorer still has a finite operational timeout.

`evaluation.profile` names the scoring protocol. Results from distinct profiles
remain separate, even if they share a metric name. After task changes, run
`npm run catalog:refresh` and then run the structure and catalog checks.

For tasks with an explicit `evaluation` block, `meta.json` must contain the exact
`taskVersion`. Missing or mismatched versions fail submission validation.
Successful and failed scoring records retain the selected task version and profile.
Legacy tasks without this block retain their optional-version submission contract.

## Integration and publication

Both dated public-data snapshots are published at their recorded fixed revisions.
The unified revision `f50618208e3e748a8a16dfb6138e335f033d603c` is published, and the scoped [delivery checks](../reports/unified-public-delivery-20261015.json) passed.
The full collection was not redownloaded, and no Agent, model, or owner Test ran for this data migration.
The v1 source collection entered main through [PR #75](https://github.com/NeuroAIHub/BrainPilotBench/pull/75).
The unified download and preparation update remains on the `feat/unified-public-data-layout` review branch.
The collection name does not bump the CLI package version or create a release tag.
This branch does not publish an npm package or image,
update the Cloud catalog, or change the independent research projects. Private
evaluator files and all four EEG preparation entries are not in the public batch.
Issues #63 and #65 remain deferred. The contributor's MRI source and split
assurance is accepted for this integration. No further source or split evidence
is required for this integration.
