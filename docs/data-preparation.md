# Public data preparation — 2026-10-13

Status: the first public-data batch is published at a fixed Hugging Face revision.
The collection has 105 runnable interfaces: 101 added tasks and four original tasks.
It also has four EEG preparation entries and one withheld EEG candidate.
Interface readiness, data availability, and model validation are separate states.

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

The update also passed build, 41 data-related unit tests, collection/catalog checks,
schema validation, and the documentation smoke check.
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

## Using public data

For the published first batch, run `bp-bench fetch <task-id> --public` to load
the files named in `data.lock`. The fetcher checks each file's size and SHA-256.
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

## Publication boundary

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
