# Tail-suspension state decoding

**Candidate only. This task is not runnable and has no BrainPilotBench Agent results.**

Can cortical calcium activity distinguish active and passive states during a tail-suspension experiment?
The proposed model assigns a state to each annotated time point.

## Evaluation

The selected metric is **Accuracy**: correct predictions divided by scored predictions.
The supplement reports results across four animals. Exact split membership and across-animal aggregation still need source confirmation.
Windows from the same event must not be treated as independent train and test trials.

## Data and preparation status

The inspected public release does not provide the matching signals, state labels and evaluation split.
No data lock, preparation command or reference run is available.
This candidate does not use unrelated free-behavior recordings as substitutes.

- [Source article](https://doi.org/10.1038/s41586-026-11293-x)
- [Protocol and promotion requirements](protocol.json)
- [Source audit](../../../reports/mouse-expansion-20261026/airscope-source-audit.json)
- [Mouse expansion guide](../../../docs/mouse-task-preparation.md)
