# Mouse behavior

These five tasks study social behavior from real two-dimensional mouse pose recordings.
They join the v1 collection through public HF data, separate evaluator packages, and isolated model scoring.
No new Agent benchmark results are available.

| Task | Research question | Primary metric |
|---|---|---|
| [CalMS21 classification](calms21-classic-classification/README.md) | Which social behavior occurs in each frame? | Behavior-class mean F1 |
| [CalMS21 annotation style](calms21-annotation-style-transfer/README.md) | Can a model adapt to another annotator's behavior definitions? | Annotator-mean F1 |
| [CalMS21 few-shot behavior](calms21-few-shot-behavior/README.md) | Can a model identify new behaviors from limited labels? | Behavior-mean positive F1 |
| [MABe22 representations](mabe22-representation-classification/README.md) | Can fixed linear probes read experimental conditions and behaviors from learned features? | Sequence-first F1 |
| [MABe22 supervised segmentation](mabe22-supervised-segmentation/README.md) | Can a supervised model identify behaviors from re-estimated pose? | macro-F1 |

CalMS21 keeps the `other` class and all background frames. Only its own F1 is excluded from the main class average.
MABe22 representation learning and supervised prediction are separate protocols, not independent source datasets.
ResiFuse provides a method and protocol reference. It does not restrict the submitted model architecture.

The [public mouse directory](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/main/tasks/animal-behavior) follows the collection's existing task layout.
Each task's locks select immutable download revisions. Original-source helpers remain available for regeneration.
Each task's `NOTICE.md` preserves its source licenses and attribution, including the noncommercial terms for these mirrors.

The [preparation guide](../../docs/mouse-task-preparation.md) gives data access, environments, model contracts and verified CLI workflows.
The [Airscope candidates](../calcium-imaging/README.md) concern calcium-to-behavior decoding rather than video-only behavior recognition.
