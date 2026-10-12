# Public data preparation — 2026-10-12

Status: owner-only preparation. No new data package has been uploaded.
The collection has 105 task interfaces and five EEG candidates.
Interface readiness, data availability, and model validation are separate states.

## Verified copies

| Selection | Tasks | Public files | Data bytes |
|---|---:|---:|---:|
| Psych-101 published train/validation | 76 | 152 | 859,179,475 |
| Imported EEG frozen train/validation | 21 | 84 | 23,459,995,282 |
| Native BCI representative | 1 | 2 | 170,344,916 |
| Full native Sleep-EDF stage | 1 | 4 | 4,453,124,284 |
| Structural MRI public archive | 1 | 1 | 3,729,262,581 |
| C. elegans public source files | 1 | 3 | 1,063,606 |
| Total | 101 | 246 | 32,672,970,144 |

These totals exclude manifests, evaluator data, and the four retained legacy
tasks. Each copied data file was read back and checked against its frozen SHA-256.
Data stay outside Git. The large EEG and Psych copies remain on shared storage;
MRI, BCI, and worm copies are staged locally.

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

## Remaining data work

| Selection | Current state | Required next check |
|---|---|---|
| Native HMC stage | Data-only export started after two memory admission checks; no completed package | Verify the completed export, public package, and scoring contract |
| Native HMC onset, Sleep-EDF onset | Full native configurations resolved; arrays are not materialized | Export, verify, and bind scoring contracts |
| CHB-MIT | Full native configuration resolved; strict `sum` adapter passes bounded checks | Run a full data-only export, retaining native labels and rejecting non-one-hot targets |
| Thielen2021 | Withheld | Remains outside activation under the existing research scope |

No running export counts as a prepared package. No reconstructed file replaces
a frozen file unless its size and SHA-256 match. A mismatch needs a separate
task version, not an edited hash under the old identity.

HMC sleep stage first failed its memory admission check. A later pair of checks
passed, and one isolated data-only export started. This is parallel preparation,
not part of the completed data totals. The other full exports have not started.
No automatic retry or recurring monitor was scheduled.

The four legacy tasks retain their original pinned download references. They
are not included in the new-copy totals above. Their unchanged task definitions
and path regressions passed; their data were not downloaded again in this phase.
All six pinned public URLs returned HTTP 200 to fresh HEAD requests. Their
reported lengths and linked SHA-256 metadata match `data.lock`. This checks
availability and server metadata, not freshly downloaded content hashes.

## Using an available packet

For imported EEG, the maintained layout is
`<root>/<task-id>/<source-task-version>/<file>`. Set `BPB_LOCAL_DATA_ROOT`
to that root, then run the task's public fetch and preparation commands.
The fetcher verifies `data.lock`; it does not accept a same-named file by itself.

For Psych, set `BPB_PSYCH101_PUBLIC_TASK_DIR` to the packet's
`public-tasks/<task-id>` directory. Follow that task's README for preparation
and public scoring. The scorer verifies both split hashes before model execution.

Use the individual MRI and worm README commands with their verified public
sources. Evaluator-only inputs stay in a separate maintainer-controlled location.
The four real reference checks are recorded in
[integration-validation.md](integration-validation.md).

## Publication boundary

Before upload, select an exact destination and immutable data version.
Upload only the public allowlist, verify downloaded hashes, then replace
maintainer-only references with those verified download locations.
Keep private evaluator distribution separate. Repository publication, data
upload, and the Bench page update each need their concrete targets approved.

Local receipts are under `.cache/psych101-public-staging/`,
`.cache/eeg-public-staging/`, `.cache/public-data-candidate/`, and
`.cache/eeg-d-expansion/actual-prep/`. They retain exact source and output
locations, producer hashes, job identities, and verification results.
