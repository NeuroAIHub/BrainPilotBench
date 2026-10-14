# Task coverage expansion — 2026-10-12

Status: first-batch integration candidate on `feat/shared-task-collection`.
The base commit is `1bb49ede1ab99a4d370f066d431d59926ea1c1ad`.
This batch is for code review. It does not publish data or images, create a
benchmark release, merge into main, or deploy services.

## Current coverage

| Domain | Runnable interfaces | Preparation-only | Withheld |
|---|---:|---:|---:|
| EEG | 25 | 4 | 1 |
| Psychology | 76 | 0 | 0 |
| MRI | 2 | 0 | 0 |
| Connectomics | 1 | 0 | 0 |
| Calcium imaging | 1 | 0 | 0 |
| Total | 105 | 4 | 1 |

The catalog covers 110 task/protocol identities. It does not represent 110
independent datasets or completed experiments. A runnable interface includes a
task definition, pinned data manifest, environment instructions, preparation
entry, submission contract, and scorer. It still requires the specified data.
New EEG and Psych entries provide public validation, not private Test scoring.

The four original task YAML files remain byte-identical to the base commit.
The independent research repositories, experiment queues, and historical results
remain unchanged. There is no top-level `runtimes/` layer.

## EEG: 21 additional frozen protocols

The expansion adds AlexMI, Zyma, Zhou, seven ERP CORE tasks, nine BCI tasks,
Typing, and DICE. Each contract preserves its source version, input shape,
label mapping, native split, and data hashes. Original source metadata match
the 19 archived manifests and two newer prepared packets.

The four public files per task are train and validation arrays plus their group
maps. Their declared sizes total 23,459,995,282 bytes before deduplication.
These arrays were not copied to this Mac. `local://` references require exact
maintainer-supplied files or an existing verified public package.

The shared scorer separates complete-class balanced accuracy from the native
Typing sparse macro metric. Submitted code runs in non-root, network-disabled
Docker containers. The trusted parent keeps labels and checks predictions.
The host NumPy environment and worker dependencies have separate setup instructions.

Some historical packet-master archives contain both public files and private
Test data. They must not become public downloads or Agent workspace inputs.
The maintainer exporter provides a read-only plan and a separate extraction step:

```bash
python3 tasks/eeg/_shared/stage-public-from-archive.py --plan \
  --task tasks/eeg/<task-id> --archive /path/to/owner-held-master.tar

python3 tasks/eeg/_shared/stage-public-from-archive.py --extract \
  --task tasks/eeg/<task-id> --archive /path/to/owner-held-master.tar \
  --output-root /absolute/new-public-staging-root
```

The exporter copies only four allowlisted, hash-bound public files. It rejects
unsafe archive paths, links, duplicates, wrong sizes, and existing destinations.
It does not copy the mixed archive, private files, or original task specification.
The output remains owner-only until a separate publication step is approved.

## Psych: all 76 published IDs

Twenty-two tasks use closed categorical response profiles. This includes ten
new variants: Ludwig exp0/1, Schulz exp1/3/4/5, and Wilson exp1/2/3/4.
Their 722 public rows and 283,625 marked responses passed the existing option
rules with no mismatch. Wilson exp2 has no official Test. It remains usable
for public research and validation.

The other 54 tasks use a new, versioned UTF-8 byte protocol. At each step, the
model returns a normalized distribution over 256 bytes and an end-of-response
symbol. The evaluator sends only earlier response bytes and retains the current
target. Per-response NLL includes the end symbol.

This metric version is not directly comparable with historical token-based or
closed categorical scores. Both the task version and `evaluation.profile` record
the distinction. The results table does not merge different profiles.

The target remains the original `<<...>>` response spans. Unmarked Go/NoGo
omissions remain context. Numeric strings retain their source spelling, including
Wu2018 answers of `0` despite instructions that describe options 1–30.
This target policy does not claim to score every behavior in the source studies.

The public-data scan covered 60,092 rows and 10,681,650 marked responses.
The longest response contains 156 UTF-8 bytes. The longest transcript contains
168,988 bytes. Both fit the configured response and message limits.
All 76 contracts match the published split IDs, hashes, and counts.

## Full native Sleep-EDF and five remaining entries

The full native Sleep-EDF stage task now has a registered public-validation
interface. Its 78-subject export has 116,493 train and 38,071 validation windows,
with two channels and 3,600 time points per window. Public packaging, hashes,
subject grouping, shared data preparation, and trusted scorer input checks passed.
Its new source spec is explicitly a BrainPilotBench-created version.
No additional model was fitted and no private Test score was computed.

Four tasks have preparation recipes but no frozen full task arrays:

- HMC sleep stage and sleep onset.
- Sleep-EDF native sleep onset.
- CHB-MIT seizure state.

Their data-only exporters pin the native source commit. The preparation process
requires a full-population configuration, raw data, and a compatible isolated
native environment. It must run separately from active research jobs.
The two onset tasks retain the native BinnedMAE bins and target semantics.

The verifier checks source, code, calibration, shard, and lineage bindings.
It checks actual subject membership across train, validation, and Test metadata.
The packager requires a matching preparation receipt and writes a new candidate
directory. It does not overwrite source data or a frozen export.

These four entries have no discoverable task YAML or invented data hashes.
Their full native configurations have been resolved. CHB-MIT now has a strict
adapter for its native sum target and separate missing class. Synthetic and
native in-memory checks passed; they do not establish full-data compatibility.
The HMC stage export started separately after its memory admission checks passed.
Its running output is outside the 105-interface batch and is not a completed package.
After those exports exist, their final contracts and scoring bindings need checks.
Thielen2021 remains withheld under the earlier research scope choice.

## Verification and limits

The original four real reference checks remain recorded in
[integration-validation.md](integration-validation.md). This expansion reused
the frozen EEG and Psych references to check changed shared code:

- EEG public balanced accuracy remained 0.3897569444.
- Psych public response NLL remained 0.5783184149.
- Neither regression check retrained a model or used private Test.

Local checks passed:

- 226 main-repository tests, with no failures or skips in the fresh-directory
  check with numerical Python and Docker fixtures available.
- Nine EEG contract, staging, archive, and scoring boundary tests.
- Four Psych byte-protocol tests, including Docker isolation and causal messages.
- Five EEG preparation plans and synthetic export, package, path, and metric checks.
- All 105 task schemas, catalog consistency, and documentation command checks.
- Thirteen Psych packet staging tests, including no-replace races and legacy manifests.
- Eleven CHB sum-target/profile/lineage/receipt tests and the native in-memory label fixture.
- Python syntax checks and `git diff --check`.

Detailed evidence stays in `.cache/eeg-expansion/`, `.cache/psych101-expansion/`,
and `.cache/eeg-d-expansion/`. No new Agent experiments ran. New task-specific
model fits and full scores were not computed. The new byte protocol used
synthetic inference checks, not a claimed real-data research result.

The [data preparation record](data-preparation.md) tracks the verified public
copies and remaining exports. Before publication, complete the missing packages,
choose stable download locations, and check the resulting downloads. The full Psych source-reconstruction
route remains untested. The current images were checked on arm64, not every
target platform. The inherited `undici` dependency advisory also remains open.
Public upload, private evaluator distribution, Git merge, and release each need
their concrete targets and approval.
