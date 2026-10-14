# D5 native EEG data preparation (candidate, not a research runtime)

These files are a task-collection-owned, data-only preparation dependency for
five EEG recipes, including four preparation-only candidates. They do not start Agents, fit models, consume private
Test, register a runnable task, or manage the independent AgentEEGBench queue.

The scientific source must be a clean checkout of
`a8092dc10956038e445ff0e07f9c0c7e03a10d36` with its native
`neuralbench`, `neuralset`, `neuralfetch`, and `neuraltrain` Python packages in
an isolated environment. This is a pinned scientific dependency, not the
uncommitted NeuralBench-Agent-Bench research workspace. Its exact deployable
environment/image and each full-population calibration manifest are still
required inputs; none is fabricated here.

The vendored, data-only exporter copies were taken from the 2026-10-12 local
preparation source. Original SHA-256 values:

| File | Original SHA-256 | Vendored change |
|---|---|---|
| `export_classification_native.py` | `b7e8009b45176538bc77900b01018f0764f1b49e56fed043c078b23488f6ba19` | Checks lazy imports and package-root containment. Adds the strict CHB sum profile and removes maintainer-specific network probes. Current SHA-256 `adb166da6feda1e632524a6aca0e6f7d796e85950dd2bd1f7c40b531ea811999`. |
| `export_sleep_onset_native.py` | `b7e2618ec33d6ca79b65521c7fb985a6b99e89c90a95bc419b93b8a81ddd0c3a` | Imports adjacent vendored files and documents their repository path. Current SHA `99e457845307af53b0588b772127648506a1eb59de706be86aa919f9f35208f5`. |
| `sleep_special_contract.py` | `c97b394368235bc38df6db43a00116ffb5203a73ff1e5ee86d29227f6fccc77b` | none |
| `seizure_contract.py` | New task-owned adapter | SHA-256 `01fb868ccc4332130ab43d9079b3b291ada1dfe374454b95bff1036c8bb0c56a`; preserves native window-event sums, missing-class encoding, and scientific preprocessing fields. |

The exporter itself checks the pinned source checkout and full-population
resolved config, refuses an existing output, requires a distinct Linux user +
network namespace, and records hashes and private lineage. `prepare.py`
verifies the vendored file hashes and required inputs before launching that
exporter. The full Sleep-EDF stage export and public package were prepared
with a frozen earlier exporter snapshot (`b17a15f2…`). Its actual producer
and configuration hashes remain in the original receipts. Later tool changes
do not relabel those receipts. See [data preparation](../../../docs/data-preparation.md)
for current data availability; new tool checks do not prove all full exports.

For one task, start with the thin entry in `tasks/eeg/<id>/env/prepare.py`:

```sh
python3 tasks/eeg/<id>/env/prepare.py --plan
python3 tasks/eeg/<id>/env/prepare.py --check-inputs \
  --source /pinned/native-science-checkout \
  --manifest /frozen/full-population-calibration.json \
  --data /read-only/raw-data --python /isolated/native-python \
  --out /new/empty/export-path
```

Only after that check and the active research control's natural boundary may
the data-only `--run` mode execute in a separate location. It requires a **new**
`--receipt /separate/export-run-receipt.json`; an existing receipt is never
overwritten. The exporter writes
`public/train`, `public/val`, `private/test`, `lineage`, and `complete.json`.
`checks/verify_export.py` validates output roles and hashes, but a standalone
check remains origin-unbound and cannot promote a task. Then
`env/package_public.py --preparation-receipt /separate/export-run-receipt.json`
checks the exporter/calibration/complete hashes before creating four public files (`train.npz`, `val.npz`, and
subject-group JSON for each) plus a separate evaluator-only binding. Real
subject names are replaced by consistent opaque group IDs, preserving native
subject membership. Never publish `private/`, `lineage/`, the full
`complete.json`, or the evaluator binding with the Agent package.

If a verifier fails after the native exporter writes `complete.json`, keep
the original run status as failed. A separate full verification of that
existing export can create a recovery receipt with schema
`bpb-eeg-existing-export-recovery/1`. This receipt records the old failure
and its status hash. It does not turn the original run into a success.
Package the public files only after the recovery check passes.

An export receipt proves data serialization and role separation only. A task
becomes runnable after its exact array shapes, labels, split membership, four
file hashes, inference API, scorer, and isolated real-path smoke are reviewed
and frozen into a task contract and `data.lock`. The sleep-onset tasks also
require a separate native BinnedMAE regression scorer; classification BA is
not an acceptable substitute. Existing Test remains unconsumed by this
preparation workflow.

CHB-MIT uses a separate `native-seizure-sum-missing-last-v1` profile. Its
five-second windows use `Eeg` triggers and overlapping `Seizure` annotations.
The native missing index is `-1`, represented by the final one-hot column.
The exporter checks each actual native target against window events. It rejects
multiple overlapping seizures and non-one-hot outputs instead of changing them.
Synthetic and native in-memory event checks passed; full CHB data remain unexported.

The synthetic checks `test_contract.py` and `test_package_public.py` use only
small fixtures. They test role-bound output, native regression/classification
shape contracts, and refusal of a Test feature shard containing its label.
