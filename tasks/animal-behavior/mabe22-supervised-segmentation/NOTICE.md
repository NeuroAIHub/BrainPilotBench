# MABe22 supervised segmentation: data notice

Task: `mabe22-supervised-segmentation`.
This notice covers the public and evaluator data packages. The repository software license does not replace these data terms.

## Sources, attribution, and licenses

### Original MABe22 labels

Source: [MABe22 dataset, CaltechDATA v1](https://doi.org/10.22002/rdsa8-rde65).
Credit: Jennifer J. Sun, Markus Marks, Ann Kennedy, and the MABe22 collaborators.
The official record and paper identify all dataset creators and authors.
Citation: Sun and coauthors, *MABe22: A Multi-Species Multi-Task Benchmark for Learned Representations of Behavior*, ICML, PMLR 202, 32936–32990 (2023).

The [paper's Mouse datasheet](https://arxiv.org/html/2207.10553v2) specifies [CC BY-NC-SA 2.0](https://creativecommons.org/licenses/by-nc-sa/2.0/legalcode.en).
The [Caltech API](https://data.caltech.edu/api/records/rdsa8-rde65) had no rights field on 2026-10-27. This mirror uses the explicit paper license.
The source `mouse_submission_labels.npy` has published MD5 `7f10c2b676e7dd8b4348423f0ee0aa8a`.
The source `mouse_frame_number_map.npy` has published MD5 `ffc1dcae90176cdac4ff4fe123e18f25`.

### Re-estimated pose

Source and credit: [WeihanLikk/ResiFuse-MABe22](https://huggingface.co/datasets/WeihanLikk/ResiFuse-MABe22/tree/22019237bee137b74f8211977779c822236b8402), revision `22019237bee137b74f8211977779c822236b8402`.
The [pinned dataset card](https://huggingface.co/datasets/WeihanLikk/ResiFuse-MABe22/blob/22019237bee137b74f8211977779c822236b8402/README.md) grants [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en).
It identifies this pose as a derivative of the MABe22 videos. The original MABe22 attribution also remains applicable.

The ResiFuse repository credits Weihan Li, Jingyang Ke, Qinheng Pu, Yule Wang, Chengrui Li, and Anqi Wu.
Their work is *Learning When Visual Context Matters for Mouse Behavior Analysis*.
The [pinned README](https://github.com/BRAINML-GT/ResiFuse/blob/ae4acf51962b1611656da00d3da92a6b02a56ef4/README.md) supplies the method description and credits.

All 108 selected H5 files bind to their source LFS SHA-256 values.
The generated `pose_source_manifest.json` records those paths and hashes.
Its SHA-256 is `def7a7b7f2b405bc42a58c696c7be2ebfc4bf9eb6cddf121258d7d9cfe69eb78`.
The [pinned source protocol](https://github.com/NeuroAIHub/BrainPilotBench/blob/8b59add4c9d02a324f61606ac8db1ccbe7fbe94e/tasks/animal-behavior/mabe22-supervised-segmentation/protocol.json) records the preparation bindings.

### Supervised split metadata

The split comes from [BRAINML-GT/ResiFuse](https://github.com/BRAINML-GT/ResiFuse/tree/ae4acf51962b1611656da00d3da92a6b02a56ef4), commit `ae4acf51962b1611656da00d3da92a6b02a56ef4`.
The source file is `splits/mabe_finetune_split.json`.
Its SHA-256 is `ebb486c7351eff8c9ae0fcfd2a21423083d06d0795e2febd2677d000ad4bffc9`.
The repository's software and documentation use the [MIT License](https://github.com/BRAINML-GT/ResiFuse/blob/ae4acf51962b1611656da00d3da92a6b02a56ef4/LICENSE).

Copyright (c) 2026 Weihan Li, Jingyang Ke, Qinheng Pu, Yule Wang, Chengrui Li, Anqi Wu.

The delivery includes the full upstream MIT notice as `LICENSE-ResiFuse.txt`.
Its permission notice and warranty disclaimer apply to redistributed source split or software material.
The MIT license does not relicense the pose or behavior labels.

## BrainPilotBench changes

BrainPilotBench converts H5 pose and source object labels into numeric NPZ files.
It retains indexed frames 0–1799 and excludes the unlabeled terminal pose row.
It retains the source 54/11/43 video split and separates public development data from evaluator data.
It groups oral-ear and oral-oral contact into oral contact, alongside chases, huddles, and oral-genital contact.
Inference uses label-independent complete clips. The evaluator owns the source-positive and pose-valid eligibility mask.
The resulting pose-only task is a BrainPilotBench adaptation, not an exact ResiFuse or original MABe22 paper reproduction.

Original material retains its source terms.
To the extent copyright applies, BrainPilotBench contributes its new dataset adaptations under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en).
This contribution license does not replace the license of the underlying material.
The [Creative Commons guidance](https://creativecommons.org/faq/#if-i-derive-or-adapt-material-offered-under-a-creative-commons-license-which-cc-licenses-can-i-use) explains source and adapter obligations.

## Reuse and evaluation integrity

Keep the attribution, source links, license links, modification notice, and applicable warranty disclaimers with redistributed material.
Use this mirror for noncommercial purposes under the applicable source terms.
The source licenses provide their own warranty disclaimers and limits of liability.
This mirror does not imply endorsement by an original author or institution.

Evaluator-only access protects experimental integrity. It is not a new copyright restriction on licensed recipients.
The source labels were publicly available upstream. Their source permissions remain intact.
Access controls do not impose a separate ban on redistribution or another exercise of those rights.
