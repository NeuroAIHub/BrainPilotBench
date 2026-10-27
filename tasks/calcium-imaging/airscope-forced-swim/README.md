# Forced-swimming behavior decoding

**Candidate only. This task is not runnable and has no BrainPilotBench Agent results.**

Can cortical calcium activity distinguish swimming, struggling and floating?
The proposed model returns continuous scores for these three states at annotated time points.

## Evaluation

The selected metric is **AUC only**. The source supplement reports AUC but does not establish its complete computation in the inspected material.
ROC versus PR, multiclass reduction and fold aggregation remain unresolved.
No scorer will assume these definitions. Hard class IDs alone cannot support this metric.

## Data and preparation status

The inspected release does not supply matching machine-readable phase labels and aligned calcium examples for this experiment.
No data lock, preparation command or reference run is available.
Supplementary demonstration videos do not constitute a verified label table.

- [Source article](https://doi.org/10.1038/s41586-026-11293-x)
- [Protocol and unresolved metric definition](protocol.json)
- [Source audit](../../../reports/mouse-expansion-20261026/airscope-source-audit.json)
- [Mouse expansion guide](../../../docs/mouse-task-preparation.md)
