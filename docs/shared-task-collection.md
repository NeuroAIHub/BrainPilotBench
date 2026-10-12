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

## Data and environment

Large arrays and MRI files stay outside Git. Existing published data URLs remain
pinned to immutable revisions and SHA-256 hashes. `local://name` entries refer to
maintainer-provided archives beneath `BPB_LOCAL_DATA_ROOT`; they are not download
URLs. Fetch verifies their hashes and copies them into the content cache.
Unset `BPB_LOCAL_DATA_ROOT` before starting an Agent. Use separate public and
evaluator caches. The launcher rejects evaluator environment variables and a
private cache visible to an Agent.

The new EEG and brain-age entries do not yet have permanent public data mirrors.
Their local package route is tested and documented. A recipient still needs those
packages; cloning the repository alone does not download them. Psych can use the
frozen published public package or reconstruct it from the pinned public source.
The representative run tested the published-package route, not the full source
download/reconstruction route. The worm task fetched its pinned source files.

Each task owns its environment instructions. CPU Docker images are built locally
and evaluated by immutable ID/digest; no images were published. A successful
macOS/arm64 integration run does not verify Linux/amd64 or GPU compatibility.

## Low-cost validation

The current integration runs exactly four representative references: native EEG
BCI-IV-2a, Psych Lefebvre exp1, C. elegans and brain age. EEG and Psych use public
train/valid only; historical private Test results are not replayed. The two new
contributions use their own reference-evaluation paths. These runs check data,
environment, saved artifacts, inference and scoring; they are not Agent research
experiments. No paid model calls are needed.

Other executable family members receive structure and contract checks only.
Four EEG entries remain preparation-only until their frozen data packages exist.
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

This branch prepares a collection candidate. It does not merge, release, publish
data/images, update the Cloud catalog, or change the independent research projects.
Issues #63 and #65 remain deferred. Source/data terms and any hosting work belong
to the concrete publication review; the contributor's MRI source and split
assurance is accepted for this integration and is not a request for more evidence.
