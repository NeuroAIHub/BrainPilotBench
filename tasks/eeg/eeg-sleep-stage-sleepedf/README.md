# Sleep-EDF cassette sleep staging

Status: registered public-validation interface with an owner-staged data package.
The real data preparation and shared scoring contract checks passed.
This is not a new model result or private Test acceptance.

The native source task is `sleep_stage/default` from `Kemp2000Analysis`.
The pinned scientific source is `a8092dc10956038e445ff0e07f9c0c7e03a10d36`.
The full export contains 78 subjects and uses a subject-disjoint split.
The native pipeline crops wake time to 30 minutes and uses 30-second windows.

The public package contains 116,493 train samples and 38,071 validation samples.
Each feature sample has two channels and 3,600 time points at 120 Hz.
The five labels are N1, N2, N3, R, and W, in that order.
The public validation metric is five-class balanced accuracy.

The public package has four files: `train.npz`, `val.npz`, and two group files.
The group files contain opaque subject IDs with no overlap between the splits.
The package is in owner-only staging. No public download URL exists.
The `data.lock` file names task-scoped local files and their exact hashes.

`source-task-spec.json` is a new BrainPilotBench source spec.
It is not a spec from the independent AgentEEGBench research project.
`contract.json` binds this spec and the four public files to the shared scorer.
`data_provenance.json` records the actual v3 producer, full config, export, and package hashes.
The current `preparation.json` is a rebuild recipe, not a claim about future producer code.

The data-only export did not fit a model or score private Test data.
The owner-only evaluator binding points to private Test material outside the public package.
Do not copy `complete.json`, `private/`, `lineage/`, or `evaluator/` into Agent input.

The shared public-data reader passed a real-file read with this candidate.
The trusted scorer accepted the validation shape, labels, and a synthetic metric fixture.
No new model fit, Agent run, full public score, or private Test score was performed.
The EEG representative check covers the shared inference path; this task received
structure and real-data input checks under the collection's low-cost validation policy.

## Prepare and score

From the repository root, install the trusted NumPy environment:

```sh
bash tasks/eeg/_shared/setup-python.sh
```

Set `BPB_EEG_PYTHON` to the printed interpreter. Place the four public files under
`BPB_LOCAL_DATA_ROOT/eeg-sleep-stage-sleepedf/bpb-native-full-20261012-v1/`, then fetch:

```sh
bp-bench fetch eeg-sleep-stage-sleepedf --public
```

Unset `BPB_LOCAL_DATA_ROOT` before Agent execution. The setup command reads the
verified cache and copies only public files into the workspace. Alternatively,
set `BPB_EEG_PUBLIC_PACKAGE_DIR` to a public package with the byte-identical
`source-task-spec.json` named `task_spec.json` and the four files under `data/`.

Submit the nine seed files specified in `prompt/turns.yaml`. Use the pinned
inference image and scoring instructions in [the shared EEG guide](../_shared/README.md).
The scorer keeps validation labels in its trusted parent process.
This task differs from the legacy `sleep-edf` task; their protocols and results
must not be merged under one task identity.
