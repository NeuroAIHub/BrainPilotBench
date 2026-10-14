# CHB-MIT seizure state — preparation candidate

Status: **preparation_ready_data_pending**. This directory intentionally has no
`task.yaml`, `contract.json`, or `data.lock`; BrainPilotBench must not
advertise it as runnable or include it in `run all`.

Native scientific task: `seizure/default` from `Dan2023Bids`, pinned source
`a8092dc10956038e445ff0e07f9c0c7e03a10d36`. The source-declared
population is 23 subjects. Primary metric: balanced accuracy (maximize).

Native 5 s seizure-state windows; two class probabilities. Split by real subject and stratify by state, using the source recipe and seed 33. The earlier six-recording `timeline_index in [0, 2, 75, 90, 115, 144]` query is calibration-only and must not be used as the full task. Source inventory reports 23 people, 24 subject-session memberships, and 686 recordings; these are not yet frozen export sample counts.

The native target sums overlapping `Seizure` events within each `Eeg` window.
It uses a separate missing class: native index `-1`, final one-hot column `1`.
The task-owned adapter preserves this rule and audits the actual native output.
Multiple overlapping seizures, zero-hot, multi-hot, or fractional targets fail
the export. They are not relabeled or silently reduced to a class by argmax.
The profile passed synthetic and native in-memory event checks, not a full export.

## Reusable data-only preparation

The task-local `preparation.json` pins the vendored exporter under
`tasks/eeg/_preparation/`. No uncommitted AgentEEGBench research runtime or
Agent queue is required. The native scientific source checkout, a calibrated
full-population manifest, already-fetched raw data, and an isolated Python
environment containing the pinned native packages are still external inputs.
A full-population configuration has been resolved from that source. Full output
data and hashes remain pending; no data hashes have been invented.

From the BrainPilotBench repository root, inspect the candidate recipe without
touching raw data:

```sh
python3 tasks/eeg/eeg-seizure-chbmit/env/prepare.py --plan \
  --receipt .cache/eeg-d-expansion/eeg-seizure-chbmit-plan.json
```

When the required inputs are frozen, first use `--check-inputs` with
`--source`, `--manifest`, `--data`, `--python`, and a fresh `--out`.
A separate, authorized data-only `--run` requires a new `--receipt` outside
the task/source/export roots and invokes the vendored native
exporter inside a distinct Linux user/network namespace. It writes public
train/validation shards and controller-only Test/lineage shards. After export:

```sh
python3 tasks/eeg/eeg-seizure-chbmit/checks/verify_export.py --export /new/export
python3 tasks/eeg/eeg-seizure-chbmit/env/package_public.py \
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
