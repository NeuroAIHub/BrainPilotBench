# CalMS21 annotation style: data notice

Task: `calms21-annotation-style-transfer`.
This notice covers the public and evaluator data packages. The repository software license does not replace these data terms.

## Source and attribution

Source: [Caltech Mouse Social Interactions (CalMS21) Dataset, version 1.0](https://doi.org/10.22002/D1.1991).
The source record credits Jennifer J. Sun, Tomomi Karigo, David J. Anderson, Pietro Perona, Yisong Yue, and Ann Kennedy.

Citation: Jennifer J. Sun and coauthors, *The Multi-Agent Behavior Dataset: Mouse Dyadic Social Interactions* (2021).
The [paper](https://arxiv.org/abs/2104.02710) supplies the complete author list and dataset description.

This package derives from `task2_annotation_styles.zip` at the [official record](https://data.caltech.edu/records/s0vdx-0k302).
Its SHA-256 is `07af9c3a18157a072755c1d1987103f8927e4de5e8996a22a6af25add59b10ab`.
Its published MD5 is `c97e87e13e77ffb80c073e05c05a4683`, and its size is 912,092,847 bytes.
The [pinned source protocol](https://github.com/NeuroAIHub/BrainPilotBench/blob/8b59add4c9d02a324f61606ac8db1ccbe7fbe94e/tasks/animal-behavior/calms21-annotation-style-transfer/protocol.json) records these bindings.

## License basis

The [paper's hosting appendix and datasheet](https://arxiv.org/html/2104.02710) specify Creative Commons Attribution-NonCommercial-ShareAlike.
The datasheet links [CC BY-NC-SA 2.0](https://creativecommons.org/licenses/by-nc-sa/2.0/legalcode.en).
This research mirror follows that noncommercial, attribution, and ShareAlike permission.

On 2026-10-27, the [Caltech record API](https://data.caltech.edu/api/records/s0vdx-0k302) instead listed CC BY 4.0.
We record this difference rather than describe the source as unconditionally commercial or unlicensed.
This notice does not remove any permissions that the original licensors separately granted.

Original material retains its source terms.
To the extent copyright applies, BrainPilotBench contributes its new dataset adaptations under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en).
This contribution license does not replace the license of the underlying material.
The [Creative Commons guidance](https://creativecommons.org/faq/#if-i-derive-or-adapt-material-offered-under-a-creative-commons-license-which-cc-licenses-can-i-use) explains source and adapter obligations.

## Changes and evaluation roles

BrainPilotBench converts source JSON into numeric NPZ files and binds each file by size and SHA-256.
It derives Valid from official Train while grouping exact pose repeats within the local Train/Valid partition.
It preserves source annotator roles and official Test. Source recordings can recur across different annotator groups.
It separates public development inputs from evaluator inputs and labels.
The metric averages the three scored behavior classes within each annotator, then averages annotators equally.
The task is a BrainPilotBench adaptation, not an official CalMS21 leaderboard result.

## Reuse and evaluation integrity

Keep the attribution, source links, license links, modification notice, and applicable warranty disclaimers with redistributed material.
Use this mirror for noncommercial purposes under the applicable source terms.
The source licenses provide their own warranty disclaimers and limits of liability.
This mirror does not imply endorsement by an original author or institution.

Evaluator-only access protects experimental integrity. It is not a new copyright restriction on licensed recipients.
The Test labels were publicly available upstream. Their source permissions remain intact.
Access controls do not impose a separate ban on redistribution or another exercise of those rights.
