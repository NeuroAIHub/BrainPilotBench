# Invasive-recording tasks: protocols and acceptance

[Task collection](../README.md#task-suite) · [Catalog](../tasks/catalog.json) · [iEEG](../tasks/ieeg/README.md)

This expansion adds seven tasks from real invasive recordings.
It adds no synthetic research datasets and no Agent runtime.
All seven have locally accepted public-validation interfaces, complete role-bound data,
and separate owner Test workflows checked with frozen references.

> [!IMPORTANT]
> Agent benchmark results are not available for these seven entries.
> Source preparation and fixed-reference checks do not establish comparative Agent performance.
> The original 105 packages and existing public data batch remain unchanged. This checkout has 112 runnable packages.

## Research tasks

| Entry | Input and prediction target | Primary metric |
|---|---|---|
| [BCI IV-4](../tasks/ieeg/ieeg-finger-flexion-bciciv4/README.md) | Human ECoG to five continuous finger-flexion trajectories | Mean Pearson r, excluding the ring finger |
| [Berezutskaya 2022](../tasks/ieeg/ieeg-film-speech-music/README.md) | Human ECoG/sEEG to speech or music conditions within a film | Participant-macro balanced accuracy |
| [FALCON H1](../tasks/intracortical/falcon-h1-reach-grasp/README.md) | Human intracortical activity to seven arm/grasp velocity components | Session-mean, variance-weighted R² |
| [FALCON H2](../tasks/intracortical/falcon-h2-handwriting/README.md) | Human intracortical activity to attempted handwriting text | Session-mean word error rate |
| [FALCON M1-A](../tasks/intracortical/falcon-m1-emg/README.md) | Monkey intracortical activity to 16 muscle activity channels | Session-mean, variance-weighted R² |
| [FALCON M2](../tasks/intracortical/falcon-m2-finger-velocity/README.md) | Monkey intracortical activity to two finger-group velocities | Session-mean, variance-weighted R² |
| [FALCON B1](../tasks/intracortical/falcon-b1-birdsong/README.md) | Songbird intracortical activity to vocalization spectrograms | Officially defined normalized spectrogram MSE |

The FALCON-derived tasks use new BrainPilotBench splits.
Their scores are not FALCON leaderboard scores.
M1-B is outside this seven-task preparation scope. Its data require a separate adapter review.

## BCI IV-4: chronological development split

The original competition supplies 400 seconds of labeled data per participant.
It reserves the following 200 seconds for evaluation.
This preparation creates Train and Valid inside the labeled portion, with a boundary guard.
Public preparation does not read original evaluation arrays or labels.
The separate owner export prepares the original Test interval and later-published official labels.

The native metric averages 12 correlations: four fingers from each of three participants.
A check on one participant must report that smaller scope. It cannot report the native aggregate as complete.
The original evaluation labels are public, so an isolated evaluator does not imply previously unpublished source data.

See the [competition protocol](https://www.bbci.de/competition/iv/desc_4.pdf)
and the task-specific protocol for the exact sample boundaries and citation terms.

## Film conditions: unseen blocks within each participant

This is a new BrainPilotBench protocol, not a pre-existing NeuralBench task.
All eligible participants use the same fixed movie-block split: seven Train, two Valid, and four Test blocks.
The split contains both speech and music conditions in each role.

Each participant retains their own electrode layout.
Input windows exclude movie timestamps, block ordinals, trigger channels, and source paths.
The evaluator aggregates window probabilities into block predictions, then averages balanced accuracy across participants.
Filtering and input context must not cross role boundaries.

This task measures condition classification in unseen parts of the same film.
It does not measure transfer to new films or new participants.
Four Test blocks provide limited stimulus diversity, regardless of the number of extracted windows.
Only participants that pass the declared data checks contribute to the final count.
Duplicate acquisitions cannot count as independent participants.

The source is [OpenNeuro ds003688, version 1.0.7](https://doi.org/10.18112/openneuro.ds003688.v1.0.7).
This preparation uses recording and annotation files. It does not redistribute the copyrighted film.

## FALCON: public-source cross-session Test

The first BrainPilotBench profile uses zero-shot transfer to later recording dates.
It does not depend on access to the official hidden evaluation set.

| Source portion | BrainPilotBench role |
|---|---|
| Earlier held-in dates, calibration files only | Train |
| Last held-in date, calibration files only | Valid |
| Public held-out calibration files | Evaluator-only Test |
| Original minival files | Excluded as duplicate smoke-test excerpts |

The frozen date/session counts are H1 5/1/7, H2 20/1/5, M1-A 3/1/3, M2 3/1/4, and B1 2/1/3.
These counts refer to Train/Valid/Test, not individual files.
All runs from one date share one role.
Multiple runs from the same date contribute to one session score.
No Test calibration data go to the Agent in this zero-shot profile.

These later-date excerpts are shorter than the official evaluation segments.
The eventual results must include each session's score and usable sample count.
A later few-shot profile needs separate adaptation and Test trials.
Small excerpts can make that split unsuitable, especially for text and bird vocalizations.

The source baseline is [FALCON commit 770c9b9](https://github.com/snel-repo/falcon-challenge/tree/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f).
H1 uses the [DANDI 000954 draft record](https://dandiarchive.org/dandiset/000954/draft). Its description prohibits redistribution under a Data Use Agreement. BrainPilotBench does not mirror H1 source or derived data. Before local download, each user must read and comply with that agreement.
Published DANDI versions or exact asset IDs and content digests bind the data separately.
Mutable `draft` names alone do not identify reproducible bytes.
The preparation tools must reject source changes, role mismatches, and duplicate assets.

## Access and acceptance boundary

### Recorded local checks

| Entry | Completed check | Not established |
|---|---|---|
| BCI IV-4 | All three participants, source/derived hashes, public-only reproduction, isolated reference, CLI, and frozen owner Test interface passed. | Agent research performance |
| Film conditions | All 51 clinical participants passed QC. The three roles contain 4,593/1,315/2,639 windows. Public staging, isolated reference, independent block-first scoring, CLI, and frozen owner Test passed. | Agent research performance or transfer to new films/participants |
| FALCON H1 | Full source/derived bindings, public staging, fixed reference, CLI scoring, and frozen owner Test interface passed. | Agent research performance or external Agent training-environment isolation |
| FALCON H2 | All 26 sources and 647/24/15 complete trials are bound. Native mask/trial checks, fixed reference, CLI, and frozen owner Test passed. | Agent research performance or official FALCON results |
| FALCON B1 | All six sources and 40/8/9 complete motifs are bound. Native mask/shape checks, fixed reference, CLI, and frozen owner Test passed. | Agent research performance or official FALCON results |
| FALCON M1-A | Seven full source files, native conversion, all role manifests, fixed reference, CLI, and frozen owner Test interface passed. | Agent research performance |
| FALCON M2 | Thirteen source-bound range extractions matched native conversion. All role manifests, fixed reference, CLI, and frozen owner Test interface passed. | Full raw-file SHA recomputation or Agent research performance |

The current BCI reference's three-participant validation correlation was 0.1202214104.
The H1 reference's validation R² was -0.0809043.
M1-A and M2 reference validation R² values were 0.2416205494 and 0.0760079496.
H2's fixed-sentence reference had Valid WER 1.0086956522; B1's Train-template reference had Valid MSE 0.0010954088.
The film power-spectrum reference fitted three Train participants and had Valid balanced accuracy 0.5098039216 across all 51 participants.
These references used fixed settings. None is an Agent result or an official source-benchmark score.
All seven entries also passed one frozen-reference owner Test interface check each.
Those reports stay separate from public Valid metrics. Test results did not select a model, hyperparameter, or split.
Each task's `acceptance.json` binds the tested version, critical code, environment files, contracts, and reference artifacts.
The catalog check rejects missing evidence or changed file hashes.

M2's source files include large fullband recordings that the native decoder does not use.
Range extraction read 20,696,120 bytes across all 13 assets while preserving the task's required arrays.
Asset IDs, published digests, ETags, exact ranges, and derived hashes bind that route.
An offline reconstruction matched the pinned native loader on real Valid data.
This evidence does not claim that each full raw source SHA-256 was recomputed.

Film preparation verified 306 source files totaling 7,179,553,288 bytes against their native digests and recorded actual SHA-256 values.
Its 257-file public-only package contains Train/Valid arrays, labels, and channel metadata, without Test or source archives.
Exact opaque IDs and shuffled file hashes also require the owner-held shuffle key to rebuild.
The key stays outside Git and Agent workspaces. A new key does not reproduce the frozen package hashes.

### Five-task public package

The candidate contains H2, M1-A, M2, B1, and the Berezutskaya film task.
It has 402 files (2,350,248,391 bytes) and targets `bpb-public-data-20261015-invasive-v1`.
Upload and remote verification are pending.

H1 and BCI IV-4 are outside this package.
H1 source and derived files stay out of mirrors because its DANDI description prohibits redistribution.
Users can download and rebuild H1 locally after they read and comply with the agreement.
BCI IV-4 redistribution terms have not been established here.

### H1 runtime check

H1 version `0.1-public-validation-stream` stages 54 public files from 13 source recordings.
Its default scorer uses `bpb-h1-public-validation-stream-v1`.
The separate owner Test workflow uses a distinct report and cannot enter the public score path.

The reference submission passed `submit verify` and container-isolated CLI scoring.
Two Valid files supplied 23,503 causal bins, with 22,873 mask-selected bins for one date.
The measured R² was -0.08090428869132338. The reference used one Train file, not the entire training set.
The score remained negative and matched the independent numerical calculation within floating-point tolerance.

Five host boundary checks and two Docker checks passed on the final worker.
The Docker checks cover current-bin-only delivery, absent full-array/label mounts, and rejection of ordinary registered-state changes.
The host checks stored tensor budgets and finite values before it imports any submitted Python into the container.
An independent review led to stronger state inspection.
Arbitrary Python behavior is not fully constrained by the registered-state checks.
The parent/container boundary separately enforces which inputs and mounts are available.

The local check used macOS/arm64 and Linux/arm64 Docker. It does not establish Linux/amd64 or GPU compatibility.
The later acceptance pass also checked H1's owner Test interface with the pre-frozen reference.
No paid Agent run, data upload, or container publication was performed.

### Running the accepted tasks

Source downloaders are maintainer tools. They do not create an isolated Agent workspace by themselves.
Keep mixed source files and evaluator data away from that workspace and its mounted caches.
After data preparation, prevent the Agent from downloading the public originals to recover Test data.
Record any external model or pretraining sources separately.

The evaluator can pass required neural inputs to a frozen submission.
It must retain labels in the trusted scoring process and prevent model selection from using Test feedback.
The source data remain public. This protocol claims execution-time separation, not secrecy or freedom from historical pretraining overlap.

Promotion required complete role-bound data manifests, an explicit submission contract,
and container-isolated execution of submitted code. All seven entries met those gates locally.
Metric helpers that accept arrays are not a substitute for that isolation.
An entry without those checks stays out of `bp-bench list` and `run all`.

The reference checks use small, fixed models. They do not run an Agent research sweep or replay historical results.
Normal path, shape, state, cancellation, and transfer-recovery checks complement the real-data runs.
The existing 101-task batch was not rerun. Its representative and structural checks remain separate.

The final local check covers macOS/arm64 preparation and Linux/arm64 CPU inference.
AMD64 and GPU compatibility, an external Agent's training sandbox, and arbitrary-Python scientific-policy enforcement are not established by these checks.

No new data upload, container publication, release, or main-branch merge is part of this local acceptance.
