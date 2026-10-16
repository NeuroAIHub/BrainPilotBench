# Intracranial EEG tasks

[Task collection](../../README.md#task-suite) · [Preparation status](../../docs/invasive-task-preparation.md)

These tasks use real human ECoG or sEEG recordings.
ECoG records from electrodes on the cortical surface. sEEG uses depth electrodes.
The task definitions preserve that distinction from scalp EEG and intracortical spike recordings.
Together with the five [intracortical tasks](../intracortical/README.md), they form the seven-task [invasive-recording category](../../README.md#invasive-recordings) in BrainPilotBench v1.
V1 has six categories and 112 tasks: 108 new tasks plus four carried from v0.

| Task | Research objective | Primary metric | Public preparation |
|---|---|---|---|
| [BCI IV-4](ieeg-finger-flexion-bciciv4/README.md) | Predict continuous finger flexion from ECoG | Mean Pearson correlation | Hosted Train/Valid, 14 files |
| [Film conditions](ieeg-film-speech-music/README.md) | Classify speech and music conditions in unseen portions of the same film | Participant-macro balanced accuracy | Hosted Train/Valid, 51 participants passed local acceptance |

No Agent benchmark results are available for these entries.
Fixed-reference checks establish the local workflow, not Agent performance.
No synthetic recordings replace their source data.

The source recordings and labels are public. The evaluator split separates
data during a BrainPilotBench run. It does not make those sources confidential.
Source archives stay in maintainer storage, outside the Agent workspace.
Both task guides lead with the hosted public preparation route. A source rebuild is a separate owner or audit workflow.
The task READMEs describe source preparation, model interfaces, and scoring.
Each promoted entry has a version-bound `acceptance.json` record.
Entries without complete acceptance remain outside runnable task discovery.
