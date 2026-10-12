# Sleep-EDF cassette sleep onset — preparation candidate

Status: **preparation_ready_data_pending**. This directory intentionally has no
`task.yaml`, `contract.json`, or `data.lock`; BrainPilotBench must not
advertise it as runnable or include it in `run all`.

Native scientific task: `sleep_onset/default` from `Kemp2000Analysis`, pinned source
`a8092dc10956038e445ff0e07f9c0c7e03a10d36`. The source-declared
population is 78 subjects. Primary metric: BinnedMAE in seconds (minimize).

Native 5 s windows and scalar seconds prediction. The target is clip(SleepOnsetMarker.n2_onset - (segment.start + segment.duration), 0, 600). Fixed BinnedMAE edges are [0, 40, 90, 300, 600] s; inner-edge values enter the bin on their right, the final edge is included, and empty bins are excluded from the mean. This is separate from sleep staging and from the existing `sleep-edf` grader-trained classification task. Whole-recording zero-phase preprocessing leaves a future-information/causality probe open.

## Reusable data-only preparation

The task-local `preparation.json` pins the vendored exporter under
`tasks/eeg/_preparation/`. No uncommitted AgentEEGBench research runtime or
Agent queue is required. The native scientific source checkout, a calibrated
full-population manifest, already-fetched raw data, and an isolated Python
environment containing the pinned native packages are still external inputs.
Their exact frozen manifests and output data hashes are not available in this
integration; no values have been invented.

From the BrainPilotBench repository root, inspect the candidate recipe without
touching raw data:

```sh
python3 tasks/eeg/eeg-sleep-onset-sleepedf/env/prepare.py --plan \
  --receipt .cache/eeg-d-expansion/eeg-sleep-onset-sleepedf-plan.json
```

When the required inputs are frozen, first use `--check-inputs` with
`--source`, `--manifest`, `--data`, `--python`, and a fresh `--out`.
A separate, authorized data-only `--run` requires a new `--receipt` outside
the task/source/export roots and invokes the vendored native
exporter inside a distinct Linux user/network namespace. It writes public
train/validation shards and controller-only Test/lineage shards. After export:

```sh
python3 tasks/eeg/eeg-sleep-onset-sleepedf/checks/verify_export.py --export /new/export
python3 tasks/eeg/eeg-sleep-onset-sleepedf/env/package_public.py \
  --export /new/export --destination /new/package \
  --preparation-receipt /separate/export-run-receipt.json
```

The package step hashes four public train/validation files and preserves
native subject grouping with opaque IDs. Test features/labels and real source
identities remain in an evaluator-only location. Do not ship the exporter
`complete.json`, `private/`, or `lineage/` as Agent input.
Standalone structure checks are origin-unbound and do not promote a task;
the package needs the source/exporter/calibration-bound `--run` receipt.

Preparation does not fit a model, run an Agent, consume private Test, or prove
the future scorer. Promotion requires exact frozen shapes, labels, split
membership, data hashes, submission API, an isolated scoring implementation,
and a real-path smoke. The independent Agent EEG research project retains its
own queue, Test-once control, and monitoring.
