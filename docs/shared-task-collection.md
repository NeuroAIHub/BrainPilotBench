# Shared task collection

BrainPilotBench stores task definitions, task-specific environments, pinned data
references, preparation scripts, submission contracts, and scoring entry points.
Research projects use those tasks at a fixed Git commit and task version. Their
Agent implementations, scheduling, credentials and research records stay separate.
There is no top-level `runtimes/` directory.

## Layout and identity

| Domain | Contents |
|---|---|
| `tasks/eeg/` | Two original tasks, 23 native public-validation tasks, four preparation-only recipes, one withheld candidate |
| `tasks/mri/` | TOPS fMRI and structural-MRI brain age |
| `tasks/psychology/` | 76 public-validation tasks: 22 categorical and 54 byte-sequence interfaces |
| `tasks/connectomics/` | C. elegans structure–function divergence |
| `tasks/calcium-imaging/` | Original RSC place-cell task |

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
The fetcher checks each size and SHA-256. `local://` remains a maintainer supply
route for unpublished data. It is not a public download URL. Unset
`BPB_LOCAL_DATA_ROOT` before starting an Agent. Keep public and evaluator caches
separate. The launcher rejects a private cache visible to an Agent.

Each task owns its environment instructions. CPU Docker images are built locally
and evaluated by immutable ID/digest; no images were published. A successful
macOS/arm64 integration run does not verify Linux/amd64 or GPU compatibility.

## Low-cost validation

The integration includes four representative reference checks: native EEG
BCI-IV-2a, Psych Lefebvre exp1, C. elegans and brain age. EEG and Psych use public
train/valid only; historical private Test results are not replayed. The two new
contributions use their own reference-evaluation paths. These runs check data,
environment, saved artifacts, inference and scoring; they are not Agent research
experiments. No paid model calls are needed.

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
npm run test:docs
```

`test:collection` checks task IDs, paths, required files, metadata and metric
directions. It does not fetch data, install Python environments, train models, or
launch all reference solutions. Real-run commands and evidence are documented in
each representative task and `docs/integration-validation.md`.

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
