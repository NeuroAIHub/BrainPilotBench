# Film speech versus music from clinical iEEG

This task classifies speech and music intervals in a film from clinical ECoG and sEEG recordings. It tests held-out film blocks within each participant.

> [!NOTE]
> Agent benchmark results: not yet available. The fixed reference has one owner-only Test receipt.

Maintainers can prepare the hosted Test package and evaluate a frozen submission through the [private evaluation workflow](../../../docs/private-evaluation.md).
This explicit route writes `scores.private.json`; the task's existing default scoring entry remains unchanged.

## Task at a glance

| Field | Task contract |
|---|---|
| Input | One `float32[channels,512]` two-second neural window and an opaque participant ID. |
| Output | One finite `float32` speech probability in `[0,1]` for each window. |
| Split | Global film blocks: Train 1, 3, 6, 7, 8, 10, 13. Valid 4, 11. Evaluator-only Test 2, 5, 9, 12. |
| Metric | Average window probabilities within each block. Compute balanced accuracy per participant, then average participants equally. Higher is better. |

Status: **locally accepted public-validation task**, version `0.2-complete-guarded-windows`.
The [task entry](task.yaml) is active; [acceptance.json](acceptance.json) binds its local checks to the exact files.

## Source and split

The source is Berezutskaya et al. (2022), OpenNeuro `ds003688` version `1.0.7`.
The [source manifest](source_manifest.json) pins the dataset commit and a small real example.
The [full source manifest](full_source_manifest.json) pins 51 clinical records and 306 source files.
These files total 7,179,553,288 bytes. The 51 signal files total 7,179,082,912 bytes.
All 306 selected source files have native digest checks and measured SHA-256 values in the frozen source evidence.
The current [data lock](data.lock) also binds the hosted public Train/Valid files.
The [cohort inventory](cohort_inventory.json) lists all 51 iEEG clinical film file sets in that commit.
It lists 52 film event files because one participant has two recorded playbacks.
This inventory checks filenames and Git blob IDs.
It does not establish data quality or eligibility.
The study reports 51 iEEG participants who watched one 6.5-minute film.
It also reports 30 fMRI participants, who are outside this task.
The film has 13 alternating speech and music blocks of about 30 seconds each.
The source gives public event times and labels, but it does not define this machine-learning split.

The [protocol](protocol.json) splits movie blocks globally across participants.
Blocks 1, 3, 6, 7, 8, 10, and 13 are train.
Blocks 4 and 11 are validation.
Blocks 2, 5, 9, and 12 are evaluator-only Test.
The split evaluates held-out blocks within each participant.
It does not measure transfer to another person or film.

Protocol version `0.2-complete-guarded-windows` keeps only complete guarded windows.
A 29.997-second block has 12 windows, from local second 2 through local second 24.
A block of at least 30 seconds can have 13 windows, through local second 26.
The extraction never rounds a short block up, pads it, or reads another block.
The old [representative receipt](representative_receipt.json) remains a historical version-1 result.

<a id="full-cohort-preparation"></a>

## Prepare the hosted public data

Use Python 3.12 and install [requirements.txt](env/requirements.txt) in a separate environment.
For an Agent workspace, use the [unified public layout](../../../docs/invasive-task-preparation.md#prepare-one-public-task). Public preparation does not require the private shuffle key or owner block mapping:

```sh
BPB_FILM_PYTHON=/path/to/film-venv/bin/python \
  node dist/cli.js prepare ieeg-film-speech-music --fetch \
  --workspace /path/outside-git/film-workspace
```

The CLI verifies the hosted public files and passes `BPB_PUBLIC_DATA_ROOT` to setup.
Setup stages Train and Valid in `/path/outside-git/film-workspace/public_data`.
The hosted public files do not contain the owner-held Test arrays or block mapping.
Preparation passed from a verified existing public cache.
The [delivery acceptance](delivery-acceptance.json) binds the revised lock and setup to the [public delivery report](../../../reports/unified-public-delivery-20261015.json).
This delivery check did not rerun the fixed reference or owner Test.

## Owner source rebuild

The commands below rebuild the frozen data from source and require the owner-held shuffle key.
The owner stores source files, the shuffle key, derived files, and hidden lineage outside the Git checkout.
The owner needs the same private shuffle key to reproduce the exact derived hashes.
A new key produces scientifically equivalent windows with different opaque IDs and file hashes.
The following rebuild commands are for the owner who holds the original key.
Other users can prepare the hosted public files without the private key.
The trusted scorer still requires the matching evaluator data and block mapping, which are not published in that package.
The source files alone cannot reproduce this task version's frozen package hashes.
For a local source rebuild, keep the external data root outside Git.
The source downloader uses at most six independent file streams and verifies native Git blobs or annex MD5 values.
Each source file has one writer. A failed request receives at most three attempts.
It resumes an interrupted signal download from its saved byte offset.
After download, it calculates an actual SHA-256 for each source file.

```sh
python tasks/ieeg/ieeg-film-speech-music/env/fetch_full.py \
  --destination /external/film-data
python tasks/ieeg/ieeg-film-speech-music/env/fetch_full.py \
  --destination /external/film-data --download
python tasks/ieeg/ieeg-film-speech-music/env/prepare_full.py \
  --data-root /external/film-data \
  --shuffle-key-file /external/private/film-shuffle-key \
  --owner-test-export
python tasks/ieeg/ieeg-film-speech-music/checks/verify_full.py \
  --data-root /external/film-data
```

The checked-in `contract.json` and `data.lock` define the accepted version.
Do not regenerate them to accept a different export.
`env/freeze_contract.py` and `env/build_data_lock.py` are maintainer tools for freezing a task definition.
They are not part of an ordinary rebuild of the current version.
A different shuffle key requires a separate task version, matching data lock, and new acceptance record.

The full source includes Test intervals because each `.eeg` file holds the entire clinical recording.
Only the owner fetches these raw files. The Agent workspace receives derived Train and Valid arrays.
First, the owner copies public files into a separate package outside the owner data root.
The Agent setup receives only this package through `BPB_FILM_PUBLIC_ROOT`.
Do not pass the source root, owner root, `BPB_LOCAL_DATA_ROOT`, or `BPB_FILM_EVALUATOR_DATA_ROOT` to the Agent process.
The owner contract binds the pinned source manifest, actual source hashes, three derived roles, and hidden lineage.
The owner keeps the Test arrays, labels, original subject mapping, and block mapping outside the Agent workspace.

```sh
python tasks/ieeg/ieeg-film-speech-music/env/stage_public.py \
  --data-root /external/film-data --destination /external/film-public
BPB_FILM_PUBLIC_ROOT=/external/film-public \
BPB_FILM_STAGE_DIR=/external/agent/public_data \
  bash tasks/ieeg/ieeg-film-speech-music/env/setup.sh
python tasks/ieeg/ieeg-film-speech-music/solution/make_reference.py \
  --public-data /external/film-public \
  --submission /external/agent/submission
python tasks/ieeg/ieeg-film-speech-music/checks/run.py \
  --data-root /external/film-data \
  --submission /external/agent/submission --role validation \
  --image "$BPB_FILM_IMAGE"
```

The reference fits fixed power-spectrum features and logistic regression on three Train participants.
Its one model accepts a variable channel count for the other participants.
The Valid score covers all 51 eligible participants and 1,315 windows.
Its block-first participant-macro balanced accuracy is 0.5098039215686274.
An independent owner calculation returned the same Valid value.
This fixed reference did not use Test for fitting or selection.

## Model and scoring

Submit exactly `model.py`, `config.json`, and `weights.safetensors`.
`Model(config)` must return a PyTorch module.
`forward(window, subject_id)` receives one float32 `[channels,512]` window and an opaque participant ID.
It must return one finite float32 speech probability in `[0,1]`.
The scorer sends one shuffled window per request to a nonroot container with no network.
The container has a read-only filesystem, dropped capabilities, bounded memory, and no host output directory.
The scorer bounds each request and reply. The model receives no labels or block mapping.
The tested image has PyTorch 2.7.1, NumPy 2.2.6, and safetensors 0.5.3.
The [Dockerfile](checks/Dockerfile) and [worker requirements](checks/requirements.txt) define a rebuild on another host.
Set `BPB_FILM_IMAGE` to a verified immutable image ID or registry digest before the direct command.
The benchmark CLI supplies `BPB_INFERENCE_IMAGE` to `checks/check.sh` during scoring.

Owner Test uses a separate frozen-submission receipt and direct `checks/run.py --role test --owner-test` call.
The fixed reference completed one owner-only Test call after Valid acceptance.
Its report stays outside Git with mode 0600. It is not an Agent result or a public leaderboard score.
Public Valid results remain development results.
For a benchmark bundle, set `BPB_FILM_EVALUATOR_DATA_ROOT` only during the later `bp-bench score` command.
The Agent preparation uses the verified public copy in `/path/outside-git/film-workspace/public_data`.
The Agent preparation command must not receive this owner path.
Use separate Agent and score commands for this task.

The preparation code hashes the full source file to make sure that its bytes match the pinned source.
Public extraction requests only the selected Train and Valid intervals.
The explicit owner export also prepares the separate Test intervals.
It makes independent two-second windows with a two-second guard at each block edge.
It resamples each window to 256 Hz without using samples from another split.
It uses good ECoG and sEEG channels from the source channel table.
It excludes marker and other non-neural channels.
The public output shuffles windows and uses opaque sample and participant IDs.
It omits source paths, movie times, block order, and run numbers.
Private lineage stays outside the Agent bundle.

## Earlier real-data representative

The pinned `sub-02` clinical recording has ECoG and sEEG channels at 512 Hz.
Its signal file is 80,591,448 bytes.
The manifest gives the source MD5 digest and Git blob digests.
The downloader enforces a 100 MB limit and verifies each source file.
It does not fetch the film, fMRI, or another participant.

The [representative receipt](representative_receipt.json) records the real source digest and output hashes.
It records 91 train windows, 26 validation windows, and 59 good intracranial channels.
The fixed reference reached 0.5 balanced accuracy on two validation blocks.
That number is a small workflow check, not a scientific performance estimate.
It belongs to the earlier preparation code and protocol version.

## Interpretation and acceptance boundary

The full source selects one clinical film acquisition per participant.
The article describes a second playback for another montage under `sub-44`.
The pinned repository names `sub-45` for the clinical and HDgrid pair.
This identifier difference remains a provenance note. The source-based rule counts each clinical participant once.
Eligibility depends on channel, timing, finite-signal, and complete-window checks.
Full preparation retained all 51 clinical participants; none failed the declared eligibility checks.

The hidden scorer averages window probabilities within each film block.
It calculates balanced accuracy for each participant and then averages participants equally.
The numeric [scorer](checks/score.py) preserves the historical Test metric check.
The isolated [runner](checks/run.py) executes a submitted model on Valid or owner Test.

The public source contains the event labels.
Therefore, this holdout checks an honest protocol.
It cannot serve as a secret blind test.
The four Test blocks are four film segments, even when they produce many windows.
Slow signal drift can still reveal movie time.
A later study can use a temporal nuisance diagnostic before interpreting a score as content-specific neural activity.
This diagnostic is not a gate for task activation.
The score does not establish a speech mechanism or generalization to another film.
The deposited neural data are CC0, but the film has separate copyright limits.
The film is not in this task and is not required to read the speech and music events.

Sources: [article](https://doi.org/10.1038/s41597-022-01173-0),
[dataset version](https://doi.org/10.18112/openneuro.ds003688.v1.0.7),
[pinned events](https://github.com/OpenNeuroDatasets/ds003688/blob/5b2cb4fbde4106ddc1332338df6a4b85ac57aeb2/sub-02/ses-iemu/ieeg/sub-02_ses-iemu_task-film_run-1_events.tsv),
[pinned channels](https://github.com/OpenNeuroDatasets/ds003688/blob/5b2cb4fbde4106ddc1332338df6a4b85ac57aeb2/sub-02/ses-iemu/ieeg/sub-02_ses-iemu_task-film_acq-clinical_run-1_channels.tsv).
