# CalMS21 few-shot behavior: data notice

Task: `calms21-few-shot-behavior`.
This notice covers the public and evaluator data packages. The repository software license does not replace these data terms.

## Source and attribution

Source: [Caltech Mouse Social Interactions (CalMS21) Dataset, version 1.0](https://doi.org/10.22002/D1.1991).
The source record credits Jennifer J. Sun, Tomomi Karigo, David J. Anderson, Pietro Perona, Yisong Yue, and Ann Kennedy.

Citation: Jennifer J. Sun and coauthors, *The Multi-Agent Behavior Dataset: Mouse Dyadic Social Interactions* (2021).
The [paper](https://arxiv.org/abs/2104.02710) supplies the complete author list and dataset description.

This package derives from `task3_new_behaviors.zip` at the [official record](https://data.caltech.edu/records/s0vdx-0k302).
Its SHA-256 is `ed9edd3009b063a8edb4c31b38d4a6773b5d6a1ee80cd57b5df89417ca647821`.
Its published MD5 is `df59df02d069bab1cfc376cdc1a3925b`, and its size is 556,170,163 bytes.
The [pinned source protocol](https://github.com/NeuroAIHub/BrainPilotBench/blob/8b59add4c9d02a324f61606ac8db1ccbe7fbe94e/tasks/animal-behavior/calms21-few-shot-behavior/protocol.json) records these bindings.

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
It derives Valid from whole official-Train sequences and preserves the seven source behavior targets and official Test.
The single intromission training sequence stays in Train. It cannot also supply an independent Valid sequence.
The complete seven-target F1 uses the evaluator role, not an incomplete public Valid aggregate.
It separates public development inputs from evaluator inputs and labels. Recordings can recur across different behavior targets.
The task is a BrainPilotBench adaptation, not an official CalMS21 leaderboard result.

## Reuse and evaluation integrity

Keep the attribution, source links, license links, modification notice, and applicable warranty disclaimers with redistributed material.
Use this mirror for noncommercial purposes under the applicable source terms.
The source licenses provide their own warranty disclaimers and limits of liability.
This mirror does not imply endorsement by an original author or institution.

Evaluator-only access protects experimental integrity. It is not a new copyright restriction on licensed recipients.
The Test labels were publicly available upstream. Their source permissions remain intact.
Access controls do not impose a separate ban on redistribution or another exercise of those rights.
