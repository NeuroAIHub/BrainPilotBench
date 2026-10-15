# Shared task collection

[Task suite](../README.md#task-suite) · [EEG](../tasks/eeg/README.md) · [Psychology](../tasks/psychology/README.md) · [Public data](data-preparation.md)

BrainPilotBench brings brain-science and behavioral research tasks into one shared collection.
Each task describes the problem, available data, required outputs, and evaluation method.
Researchers can use the same task definitions with different agents and research workflows.

> [!IMPORTANT]
> **Agent benchmark results for the 101 new tasks are not yet available.**
> Public data and evaluation code are available. Representative reference checks are not agent benchmark results.
> Published BrainPilotBench-v0 results cover the four original tasks only.

The later invasive-recording additions have separate version-bound acceptance records.
All seven have checked public-validation workflows and frozen-reference owner Test interface checks.
They have no Agent benchmark results.

AgentEEGBench, Psych101-Agent-Bench, and future specialized research benchmarks
remain independent projects. They can reuse a task at a fixed Git commit and version.
Their agents, experiment scheduling, credentials, and research records stay separate.
This repository does not add a top-level `runtimes/` layer.

## Layout and identity

| Domain | Research tasks |
|---|---|
| [EEG](../tasks/eeg/README.md) | 23 new classification tasks and two original v0 tasks |
| [MRI](../tasks/mri/brain-age-mri/README.md) | Structural-MRI age prediction and the original TOPS fMRI task |
| [Psychology](../tasks/psychology/README.md) | 76 behavioral modeling tasks, with categorical or byte-sequence response interfaces |
| [Connectomics](../tasks/connectomics/celegans-structure-function-divergence/README.md) | Anatomical connectivity and signal propagation in C. elegans |
| [Calcium imaging](../tasks/calcium-imaging/neuro-rsc-place-cell/README.md) | The original RSC place-cell task |
| [Intracranial EEG](../tasks/ieeg/README.md) | ECoG finger-flexion decoding and film-condition classification |
| [Intracortical recording](../tasks/intracortical/README.md) | Five FALCON-derived movement, muscle, handwriting, and birdsong tasks |

The collection has 112 runnable task packages. The five previously retained EEG
candidates remain outside that count. All seven invasive additions are now runnable.

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

## Data and environment

Large arrays and MRI files stay outside Git. Existing published data URLs remain
pinned to immutable revisions and SHA-256 hashes. The first 101 added tasks have
246 public data files at Hugging Face revision
[`09240a63ce2ec96050313c59221291114ff8df6f`](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/09240a63ce2ec96050313c59221291114ff8df6f/bpb-public-data-20261013-v1).
The revision also holds one selection manifest. Anonymous downloads verified
the SHA-256 hashes of all 247 paths. The original four tasks keep their older
data references. All four EEG preparation entries are outside this batch,
including two with owner-held public packages.

Run `bp-bench fetch <task-id> --public` to load a task's pinned public files.
The fetcher checks each size and SHA-256. `local://` requires files supplied
locally. It is not a public download URL. Unset
`BPB_LOCAL_DATA_ROOT` before starting an Agent. Keep public and evaluator caches
separate. The launcher rejects a private cache visible to an Agent.

The invasive additions are outside the first public upload.
A later [prepared public package](invasive-task-preparation.md#download-a-prepared-public-package) covers H2, M1-A, M2, B1, and film iEEG.
It contains 402 data files (2,350,248,391 bytes) at revision `a8a8adc87bab8d63253816dad0ae5c435e96a5f6`.
H1 and BCI IV-4 retain source-only download and local preparation routes.
The catalog's `data_access` field describes the `data.lock` route, not this separate prepared-folder download.

The film package is available without a key. Regenerating its exact opaque IDs and hashes requires the owner's private shuffle key.
Its `owner_key_bound_prepared_export` status describes that rebuild constraint, not restricted access to the prepared public files.
The trusted film scorer still needs evaluator mappings, which are not part of the public package.

Each task owns its environment instructions. CPU Docker images are built locally
and evaluated by immutable ID/digest; no images were published. A successful
macOS/arm64 integration run does not verify Linux/amd64 or GPU compatibility.

<a id="low-cost-validation"></a>

## Reference implementation checks

Four reference implementations check representative evaluation paths: native EEG
BCI-IV-2a, Psych Lefebvre exp1, C. elegans and brain age. EEG and Psych use public
train/valid only; historical private Test results are not replayed. The two new
contributions use their own reference-evaluation paths. These runs check data,
environment, saved artifacts, inference and scoring; they are not Agent research
experiments. No paid model calls are needed.

The later [invasive task checks](invasive-task-preparation.md)
cover real source preparation, public staging, fixed submissions, and isolated container scoring.
Owner Test checks use a frozen reference and return separate engineering reports.
They do not tune a model or contribute Agent leaderboard scores.
Each promoted entry has an `acceptance.json` that binds its version and critical files.
The catalog refuses to reuse acceptance after those files change.

This data publication has full byte-level readback. The follow-up limits fetch
and preparation to a small representative check. It does not rerun all 101 tasks.
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

The first public-data batch is published at the fixed Hugging Face revision above.
This branch is not merged into main. It does not publish an npm package or image,
update the Cloud catalog, or change the independent research projects. Private
evaluator files and all four EEG preparation entries are not in the public batch.
Issues #63 and #65 remain deferred. The contributor's MRI source and split
assurance is accepted for this integration. No further source or split evidence
is required for this integration.
