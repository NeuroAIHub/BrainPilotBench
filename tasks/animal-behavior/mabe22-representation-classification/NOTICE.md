# MABe22 representations: data notice

Task: `mabe22-representation-classification`.
This notice covers the public and evaluator data packages. The repository software license does not replace these data terms.

## Sources, attribution, and licenses

### Original MABe22 data

Source: [MABe22 dataset, CaltechDATA v1](https://doi.org/10.22002/rdsa8-rde65).
Credit: Jennifer J. Sun, Markus Marks, Ann Kennedy, and the MABe22 collaborators.
The official record and paper identify all dataset creators and authors.
Citation: Sun and coauthors, *MABe22: A Multi-Species Multi-Task Benchmark for Learned Representations of Behavior*, ICML, PMLR 202, 32936–32990 (2023).

The [paper's Mouse datasheet](https://arxiv.org/html/2207.10553v2) specifies [CC BY-NC-SA 2.0](https://creativecommons.org/licenses/by-nc-sa/2.0/legalcode.en).
This covers the original mouse data, including keypoints, condition labels, and UserTrain.
The [Caltech API](https://data.caltech.edu/api/records/rdsa8-rde65) had no rights field on 2026-10-27. This mirror uses the explicit paper license.

| Source file | Published MD5 |
|---|---|
| `mouse_user_train.npy` | `389bc12c9ad49b7cb50b531707b448a5` |
| `mouse_submission_keypoints.npy` | `68a9fe1fe71225787a4dae6369acc9dc` |
| `mouse_submission_labels.npy` | `7f10c2b676e7dd8b4348423f0ee0aa8a` |
| `mouse_frame_number_map.npy` | `ffc1dcae90176cdac4ff4fe123e18f25` |

### Manual behavior labels and source splits

Source: [damaggu/MABe2022](https://github.com/damaggu/MABe2022/tree/234dae7098314d6035066e3028caedee3f3ee379), commit `234dae7098314d6035066e3028caedee3f3ee379`.
Its README credits Jennifer J. Sun, Ann Kennedy, Kristin Branson, Markus Marks, and Dipam Chakraborty.
The pinned [LICENCE](https://github.com/damaggu/MABe2022/blob/234dae7098314d6035066e3028caedee3f3ee379/LICENCE) provides [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en).
The inspected label directories contain no separate license exception.
This notice preserves that repository license and the original MABe22 data attribution and ShareAlike terms.
The delivery includes the unchanged repository license as `LICENSE-MABe-evaluator.txt`.

| Source asset | SHA-256 |
|---|---|
| `round2/metadata/mouse_new_splits/labels.npy` | `cae4936eee6213f7b5247dd14c021221c9ddbe12df69de7a150d906111ee207f` |
| `round2/metadata/mouse_new_splits/frame_number_map.npy` | `7d4c6f891050ac5e6816a5d501c9bb6ea05b7d5f18bc5018a7981c61b4aee82a` |
| Each selected condition split JSON | `ef306e4f369f72b64a53df8f00b45747b50554678dd08b7300553c36feb22eaf` |
| Each selected manual-behavior split JSON | `049f99e3ffb5b939962654265fda18f01088b6905d1a2f8f237c38df1fe41aa3` |

The [pinned source fetcher](https://github.com/NeuroAIHub/BrainPilotBench/blob/8b59add4c9d02a324f61606ac8db1ccbe7fbe94e/tasks/animal-behavior/_shared/mabe_fetch_sources.py) records exact source URLs, file sizes, and checksum algorithms.
SHA-256 values for GitHub assets bind the selected files. Caltech supplies the MD5 values above.

## BrainPilotBench changes

BrainPilotBench converts source object arrays into numeric NPZ files and retains source sequence memberships.
The public development package contains 784 keypoint-only UserTrain clips and protocol metadata, without source annotations.
The evaluator package contains submission poses, probe-training labels, and Test labels in separate roles.
The task retains strain, lights, and four manual behavior targets. It excludes experiment-day and time-of-day regression.
The evaluation profile fixes three 80% sequence samples with seeds 0, 1, and 2, balanced Ridge probes, and sequence-first F1.
These choices define an explicit BrainPilotBench adaptation, not exact official leaderboard reproduction.

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
