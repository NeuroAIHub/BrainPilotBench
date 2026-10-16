# Public data preparation

## Current unified layout

The v1 collection has 112 runnable tasks. The unified layout covers 111 hosted task folders.
H1 remains source-only under its source Data Use Agreement.
The hosted tree is `tasks/<category>/<task-id>/public/` at [Hugging Face revision `f50618208e3e748a8a16dfb6138e335f033d603c`](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/f50618208e3e748a8a16dfb6138e335f033d603c/tasks).
It has 668 public files totaling 37,945,533,281 bytes, including the four retained v0 tasks.
BCI IV-4 contributes 14 files and 324,773,839 bytes.
The data and 228 metadata files are published at this immutable revision.
The current Hugging Face main tree removed 662 legacy paths at commit `46859131ae68fa2e1afdf91b5de135270563aaa0`.
The old immutable revision URLs remain available. The cutover did not rewrite history or run garbage collection.
The [delivery report](../reports/unified-public-delivery-20261015.json) records identity checks for all hosted paths and 116 anonymous root and task-manifest readbacks.
Anonymous downloads verified 56 representative data files (426,564,046 bytes) by size and SHA-256.
They include all 14 BCI IV-4 and 30 M2 files, four EEG files, and two psychology files.
They also include one input from each other hosted invasive task, MRI support, and a worm CSV.
Eight preparation checks passed: four from fresh anonymous fetches and four from verified existing public caches.
The full 37,945,533,281-byte collection was not redownloaded. No Agent, model, or owner Test ran for this delivery check.
The 371 private `data.lock` entries kept their metadata and remain outside the public layout.

Prepare one hosted task with `node dist/cli.js prepare <task-id> --fetch --workspace /path/to/workspace`.
The CLI fetches only the task's public entries and checks their bytes and SHA-256 values.
For mapped entries, it copies verified regular files into `<workspace>/.bpb/public-data/`.
It gives `BPB_PUBLIC_DATA_ROOT` to the task setup script.
Task-specific Python variables and scorer data roots remain in each task README.
Keep evaluator data and credentials outside the Agent workspace.

The public files retain their original source terms. The framework's MIT license does not grant data rights.
BCI IV-4 has its own [source and citation instructions](../tasks/ieeg/ieeg-finger-flexion-bciciv4/README.md#source-and-citation).
This repository does not assert a CC or Apache redistribution grant for BCI IV-4.

## Maintain reader-facing task descriptions

Task READMEs are the source for the descriptions shown on Hugging Face.
Their introductions explain the research problem. Their task tables describe inputs, outputs, splits, and metrics.
Internal `task.yaml` summaries do not replace this reader-facing text.

The documentation builder reads the source guides, a frozen HF catalog, and public file manifests. It does not read arrays or upload files.
Use a committed and published source revision for an update:

```sh
node scripts/build-hf-reader-docs.mjs \
  --source-revision <published-github-commit> \
  --catalog-input /path/to/frozen-hf-metadata/catalog.jsonl \
  --manifest-root /path/to/frozen-hf-metadata \
  --output /path/to/new-reader-docs
```

The builder creates task READMEs and updates only the catalog's `summary` fields.
It rejects source guides that differ from the selected commit and introductions that lack reader-facing content.
The four retained v0 tasks use descriptions and contract tables from their existing guides.
Run `npm run test:reader-docs` to verify coverage, result labels, and catalog preservation.

Review generated text and links before publication. Keep scientific manifests, data objects, and other catalog fields unchanged.
The root HF README is reviewed separately. Documentation publication does not change task versions or add Agent results.

<a id="historical-first-batch"></a>

## Historical first batch — 2026-10-13

The first public-data batch was published at a fixed Hugging Face revision.
At that point, the collection had 105 runnable interfaces: 101 additions and four original tasks.
It also had four EEG preparation entries and one withheld EEG candidate.
The counts and checks below describe that dated snapshot.

## Published first batch

| Selection | Tasks | Public files | Data bytes |
|---|---:|---:|---:|
| Psych-101 published train/validation | 76 | 152 | 859,179,475 |
| Imported EEG frozen train/validation | 21 | 84 | 23,459,995,282 |
| Native BCI representative | 1 | 2 | 170,344,916 |
| Full native Sleep-EDF stage | 1 | 4 | 4,453,124,284 |
| Structural MRI public archive | 1 | 1 | 3,729,262,581 |
| C. elegans public source files | 1 | 3 | 1,063,606 |
| Total | 101 | 246 | 32,672,970,144 |

These totals exclude the selection manifest, evaluator data, and the four retained
original tasks. The published namespace contains 246 data files and one selection
manifest. All 247 paths passed anonymous download and SHA-256 checks.
Data stay outside Git. Source copies remain on shared storage or local staging.

Psych preparation checked all 60,092 public rows and 10,681,650 marked responses.
The packet contains only train and validation files. It excludes official Test.
Its manifest SHA-256 is
`e6c52c7885cea7ff081c637e0fbcdbe538eb5df4235ad9b6e5778d3494a6cc1a`.

EEG staging copied four allowlisted public files per task. Historical mixed
archives were not copied into the public tree. Zhou's recovered arrays match
all four frozen hashes. Its older task specification was not copied or treated
as the later version's specification.

AlexMI was reconstructed from its eight hash-verified raw files. All four public
outputs match the frozen contract exactly. The receipt records the different
exporter version; the original task identity and data hashes remain unchanged.
Zyma, ERN, and LRP also passed reconstruction and independent four-file hash checks.
All 21 imported EEG packages are now staged. No frozen data hash was changed.

Native Sleep-EDF stage is a newly frozen task version. The export covers
78 subjects. Its public splits contain 116,493 train and 38,071 validation
windows; subject groups do not overlap. The four-file public package passed
independent hashing, real preparation, and trusted scorer input checks.

The MRI public copy contains `agent_data.zip`, not `evaluator_data.zip`.
The worm copy contains three public sources, not held-out reconstruction answers.
This preparation does not add model fits or repeat private Test evaluation.

The first-batch selection manifest lists 101 tasks and 246 public data files.
It contains target names, sizes, and hashes, but no maintainer source paths.
The files are under `bpb-public-data-20261013-v1/` in
[BrainPilot-Bench/Tasks-Data-Public](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/09240a63ce2ec96050313c59221291114ff8df6f/bpb-public-data-20261013-v1)
at revision `09240a63ce2ec96050313c59221291114ff8df6f`.
The uploaded selection manifest retains its historical candidate status.
The separate publication receipt records the completed data publication and 247 public
readbacks. The internal source inventory was not uploaded.

## Representative download checks

The 2026-10-13 address update used separate empty caches for these checks:

| Task | Newly downloaded public bytes | Check |
|---|---:|---|
| EEG AlexMI (`eeg-mi-barachant2012`) | 11,825,808 | Four-file fetch and workspace preparation passed |
| Psych Lefebvre exp1 | 450,595 | Two-split fetch and workspace preparation passed without the original source file |
| C. elegans | 1,063,606 | Three-file public fetch and hash checks passed |

These downloads used the pinned Hugging Face revision without a token.
The EEG and Psych caches and prepared workspaces matched their frozen file hashes.
The MRI archive retained its completed full public readback and earlier reference validation.
It was not downloaded or trained again for this address update.

The update also passed build, 41 data-related unit tests, nine EEG synthetic tests,
collection/catalog checks, schema validation, and the documentation smoke check.
The EEG contract test now checks the exact hosted URI, scope, hash, and size of each file.
These checks do not run all task references or establish new model results.
The four original data locks, private entries, task versions, and scientific contracts remain unchanged.
Local smoke evidence is under `.cache/published-fetch-smoke-20261013/`.

## Additional data candidates

HMC sleep stage has a completed native export and a verified public package.
Its four public files total 9,269,836,884 bytes. The public arrays contain
80,171 train and 27,105 validation windows, with shape `[6, 3600]` per window.
The 90 train and 30 validation subject groups do not overlap.
Independent checks covered all four file hashes, array headers, sampled values,
group membership, and the separate evaluator binding. No model was trained or scored.

The trusted preparation receipt binds the source, producer, calibration, and
completed export. The standalone structure checker does not establish that binding
by itself. The HMC package remains separate from the frozen first batch until
its runnable task contract and real preparation path are reviewed.

Sleep-EDF onset also has a verified four-file public candidate: 141,899,355 bytes.
Its arrays contain 21,840 train and 7,680 validation windows, with shape
`[2, 600]` per window. Targets remain within the native 0–600-second range.
Its 46 train and 16 validation subject groups do not overlap.
The corrected checker verified all 1,376 export files before packaging.
Independent package checks confirmed the four hashes, array shapes, targets,
and group separation. The original wrapper failure remains in its own record.

Together, the published batch and these two owner-held candidates contain 103
public packages, 254 data files, and 42,084,706,383 bytes. The two candidates
were not uploaded. They do not change the collection's 105 runnable interfaces.

MRI and worm evaluator inputs also have separate verified copies: four files,
930,292,976 bytes. They are excluded from every public manifest. Preparation
did not open their target labels or repeat private scoring. It did not import
the independent EEG or Psych projects' official Test packets.

## Remaining data work

| Selection | Current state | Required next check |
|---|---|---|
| Native HMC stage | Export and four-file public package verified; candidate only | Freeze the runnable contract and check its real preparation path |
| Native Sleep-EDF onset | Existing export recovered and four-file public package verified; candidate only | Freeze its regression contract and check its real preparation path |
| Native HMC onset | Inputs verified; export not started because memory admission failed | Recheck capacity, then export and verify the data |
| CHB-MIT | Inputs and strict `sum` profile verified; memory admission failed | Run a full data-only export when capacity permits, retaining native labels |
| Thielen2021 | Withheld | Remains outside activation under the existing research scope |

No running export counts as a prepared package. No reconstructed file replaces
a frozen file unless its size and SHA-256 match. A mismatch needs a separate
task version, not an edited hash under the old identity.

Sleep-EDF onset kept the correct 600-second target cap. The checker read the
wrong location within its report. The corrected checker requires matching caps
in all three native target records. Recovery preserves the original failed run
and producer hashes; it does not rerun raw preprocessing or relabel that run
as successful. New exports still require fresh resource and input checks.

The four legacy tasks retain their original pinned download references. They
are not included in the new-copy totals above. Their unchanged task definitions
and path regressions passed; their data were not downloaded again in this phase.
All six pinned public URLs returned HTTP 200 to fresh HEAD requests. Their
reported lengths and linked SHA-256 metadata match `data.lock`. This checks
availability and server metadata, not freshly downloaded content hashes.

## Historical access notes

At the time of the dated first batch, `bp-bench fetch <task-id> --public` loaded
the files named in its then-current `data.lock`. The fetcher checked each file's size and SHA-256.
Current data locks use the unified layout described above.
The owner-only `BPB_LOCAL_DATA_ROOT` route remains a preparation fallback for
unpublished packages. It is not required for the published first batch.

For Psych, use the published public fetch or set
`BPB_PSYCH101_PUBLIC_TASK_DIR` to a verified packet's
`public-tasks/<task-id>` directory. The scorer checks both split hashes before
model execution. The packet route is an optional maintainer source.

Use the individual MRI and worm README commands with their verified public
sources. Evaluator-only inputs stay in a separate maintainer-controlled location.
The four real reference checks are recorded in
[integration-validation.md](integration-validation.md).

## Historical publication boundary

The first public-data batch is complete at the fixed Hugging Face revision above.
The public selection contains no private evaluator file or prepared EEG candidate.
The 247 anonymous readbacks prove hosted bytes, not model performance.
Repository merge, package or image release, and the Bench page update remain
separate actions. Keep private evaluator distribution separate.

Local receipts are under `.cache/psych101-public-staging/`,
`.cache/eeg-public-staging/`, `.cache/public-data-candidate/`, and
`.cache/eeg-d-expansion/actual-prep/`. They retain exact source and output
locations, producer hashes, job identities, and verification results.
First-batch delivery metadata are in `.cache/data-delivery-20261013/`.
The final local publication receipt is in
`.cache/hf-public-upload-20261013/recovery-v1/publication-receipt.json`.
The HMC and onset candidates use separate incremental delivery directories.
The internal inventory and `.cache/private-data-candidate/` must not be uploaded
with public data.
