# Intracortical decoding tasks

This family covers human movement and handwriting, macaque motor output, and birdsong.
Together with two [clinical iEEG tasks](../ieeg/README.md), it forms the seven-task [invasive-recording category in BrainPilotBench v1](../../README.md#invasive-recordings).
All five tasks have locally accepted public-validation workflows and version-bound reference checks.
No Agent benchmark results are available for this family.

| Task | Status | Research target | Primary metric |
|---|---|---|---|
| [H1](falcon-h1-reach-grasp/README.md) | Runnable, <code>0.1-public-validation-stream</code> | Human attempted reach and grasp, seven commanded velocities | Variance-weighted R² |
| [H2](falcon-h2-handwriting/README.md) | Runnable, <code>0.1-public-validation-stream</code> | Human attempted handwriting, full sentence text | WER (CER secondary) |
| [M1-A](falcon-m1-emg/README.md) | Runnable, <code>0.1-public-validation-stream</code> | Macaque reach and grasp, 16 muscle EMG traces | Variance-weighted R² |
| [M2](falcon-m2-finger-velocity/README.md) | Runnable, <code>0.1-public-validation-stream</code> | Macaque finger control, two finger-group velocities | Variance-weighted R² |
| [B1](falcon-b1-birdsong/README.md) | Runnable, <code>0.1-public-validation-motif</code> | Zebra finch song, vocalization spectrogram | Normalized spectrogram MSE |

These five BrainPilotBench tasks use the source profile <code>bpb-falcon-public-derived-cross-session-zs-v1</code>.
They come from [FALCON](https://snel-repo.github.io/falcon/).
They are not official FALCON submissions or scores.
The upstream FALCON code is pinned to [commit 770c9b9](https://github.com/snel-repo/falcon-challenge/tree/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f).
Adapted source retains the [MIT license](UPSTREAM_LICENSE).
DANDI metadata for H2, M1-A, M2, and B1 list CC BY 4.0. H1 also lists CC BY 4.0, but its description prohibits redistribution under a Data Use Agreement.
BrainPilotBench does not mirror H1 source or derived data. H1 remains a runnable task for users who read and comply with the agreement before local download and preparation.

The source split groups data by recording date.
Earlier held-in dates supply Train.
The final held-in date supplies Valid.
Later held-out calibration files supply evaluator-only Test.
Runs from one date stay together.
The split excludes native minival files because some repeat opening calibration trials.
Test source data are public.
The evaluator boundary controls the run and package.
It does not restrict access to source data.
Results cannot be compared with FALCON's private EvalAI results.

The v1 invasive public-data package contains H2, M1-A, M2, B1, and the Berezutskaya film task.
It excludes H1 because its source description prohibits redistribution. Data access does not define a separate benchmark edition.

Each runnable entry has a task version, model interface, data setup, and public scorer.
Its `acceptance.json` binds local engineering evidence to the exact version and critical files.
Read each task guide for the source preparation and scoring commands.
An incomplete candidate remains outside `bp-bench list` and `run all`.

## Maintainer source preparation

The maintainer tool plans without writing data by default.
It downloads only when you select <code>fetch</code>, a task, an access role, an external destination, and asset IDs.
Use <code>--all-selected</code> only when you select the full frozen asset list.
Public downloads go under <code>&lt;dest&gt;/public/</code>.
Evaluator downloads go under <code>&lt;dest&gt;/evaluator/</code>.
The full-file downloader checks each file against its size and SHA-256.
Neither role creates an Agent package.

M2 normally uses source-pinned range extraction to skip unused fullband recordings.
It verifies asset identity, selected HTTP ranges, native conversion, and complete derived arrays.
It does not claim to recompute the full raw-file SHA-256.
Its standard data lock names the small derived arrays; full raw files remain optional source-audit inputs.

Use a separate Python 3.12 environment for NWB checks and metric helpers.
Install the pinned packages from [requirements.txt](_preparation/requirements.txt).
Do not install them globally.
Each runnable task uses the task-specific setup in its README.
The current asset manifest records exact asset IDs and hashes.
H1, M2, and B1 use mutable DANDI draft versions.

    python3.12 -m venv /path/to/isolated-falcon-venv
    /path/to/isolated-falcon-venv/bin/python -m pip install \
      -r tasks/intracortical/_preparation/requirements.txt

For source-asset checks, plan before you fetch:

    python tasks/intracortical/_preparation/prepare.py plan --task falcon-h1-reach-grasp
    python tasks/intracortical/_preparation/prepare.py fetch --task falcon-h1-reach-grasp --access public --asset-id 782b6fad-2679-4174-a88f-ad58589fe283 --dest /path/outside/worktree --limit-bytes 10000000
    python tasks/intracortical/_preparation/prepare.py inspect --task falcon-h1-reach-grasp --access public --asset-id 782b6fad-2679-4174-a88f-ad58589fe283 --dest /path/outside/worktree

These commands do not create a score.
The [public smoke check](_preparation/smoke_public.py) uses placeholder predictions to check shapes and metric arithmetic.
It does not report research performance.
The [H1 Ridge reference](_preparation/h1_reference.py) uses one Train file and both runs from one Valid date.
It does not use the other Train dates or Test.
The H1 reference result is not an Agent result.

Owner Test runners require each completed model to be frozen before scoring.
They isolate data roles and preserve native masks and time order.
They count complete trials and give each recording date equal weight.
H2 and B1 have only three public held-out trials or motifs per date.
Report each date score and sample count with any aggregate.

All five fixed references have passed a single owner Test interface check each.
Those owner reports remain separate from public Valid metrics and are not Agent results.
No Test result selected a model, hyperparameter, or split.

Use the [manual collection workflow](../../README.md#evaluate-your-agent) for runnable tasks.
