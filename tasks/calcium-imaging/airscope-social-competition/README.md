# Mouse social competition outcomes

**Candidate only. This task is not runnable and has no BrainPilotBench Agent results.**

Can cortical activity from two interacting mice identify which animal wins a tube-test trial?
The proposed input contains both animals' calcium signals. Each trial produces one predicted winner identity.

## Evaluation

The author code uses binary F1: label 1 means that the first input animal wins.
Training can swap the two inputs if it also inverts the label.
The evaluation order stays fixed. A trial is never counted twice because its inputs were swapped.

The proposed Bench interface returns `trial_id` and `winner_animal_id`.
This interface is not yet an accepted scoring contract.
The analysis interval must distinguish whole-trial outcome decoding from prediction before the outcome occurs.

## Data and preparation status

Deeper inspection found a 17-example public validation cache with winner labels and two PCA feature arrays per example.
It was safely inspected without loading pickle objects on the host.
The cache lacks stable original trial IDs and matching training signals; the source checkpoint was selected on validation.
It can support a small public demonstration, but does not establish the full planned task or an independent evaluation protocol.
Free-behavior and enriched-habitat recordings cannot replace these experiments.
No preparation command, data lock, reference result, or private scoring route is published for this candidate.

The release ZIP directory and historical repository trees contain no complete tube-test training payload.
The source preprocessing fits scaling and PCA on whole recordings before it extracts trial intervals.
A new split of the 17 cached examples cannot undo that preprocessing.
Public labels alone are not the obstacle, and an official new Test release is not required.

With original signals, winner labels, trial times and stable recording identities, BrainPilotBench can define its own session- or pair-grouped split.
That split must precede model fitting and define training-only preprocessing or a separate calibration protocol.
Global animal identities are required only if the task claims animal-disjoint evaluation.

- [Versioned source code](https://github.com/Neurallabware/Airscope_toolbox/tree/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/Software/Neuron_BERT)
- [Protocol and promotion requirements](protocol.json)
- [Source audit](../../../reports/mouse-expansion-20261026/airscope-source-audit.json)
- [Verified public cache and limits](../../../reports/mouse-closeout-20261026/airscope-cache-inspection.json)
- [Archive, history and preprocessing follow-up](../../../reports/mouse-hf-20261027/airscope-gap-audit.json)
- [Mouse expansion guide](../../../docs/mouse-task-preparation.md)
