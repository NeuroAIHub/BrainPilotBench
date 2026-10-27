# Calcium imaging

The runnable [RSC place-cell task](neuro-rsc-place-cell/README.md) studies spatial coding and decoding from calcium activity.
Its protocol and historical results remain unchanged.

## Airscope candidates

These three records are **not runnable** and do not increase the v1 runnable task count.
The inspected release does not establish their complete experiment-specific data and evaluation splits.
Social competition has a verified 17-example processed validation cache, with limitations described in its task guide.
Paired forced-swim and tail-suspension signals and machine-readable labels were not found.

| Candidate | Prediction target | Selected metric |
|---|---|---|
| [Social competition](airscope-social-competition/README.md) | Winner of a dual-animal tube-test trial | Binary F1 |
| [Forced swimming](airscope-forced-swim/README.md) | Swimming, struggling or floating state | AUC only; exact definition pending |
| [Tail suspension](airscope-tail-suspension/README.md) | Active or passive state | Accuracy |

Free-behavior and enriched-habitat data cannot substitute for these experiments.
See the [source audit](../../reports/mouse-expansion-20261026/airscope-source-audit.json) and [preparation guide](../../docs/mouse-task-preparation.md).
