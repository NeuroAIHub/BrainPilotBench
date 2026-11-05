# SAM2Mice tracking data notice

This notice covers the prepared data for `sam2mice-multi-animal-tracking`.
The source data license applies to the images and annotations.

## Source and attribution

The source is *Dataset supporting “Cortex-wide imaging in interacting mice with a 1-gram wireless mesoscope”*, Figshare version 1.
The dataset record retains an earlier manuscript title. The published paper uses the title below.
[Versioned dataset](https://doi.org/10.6084/m9.figshare.33942097.v1)

The dataset credits Yuanlong Zhang, Angran Li, Lekang Yuan, Mingrui Wang, Weihao Zhao, Zhenbo Wang, Boyang Zang and Yangxuan Zhou.
It also credits Tao Yu, Lin Gao, Yu Wu, Rongkang Zhu, Mengyi Tian, Kun Li, Jiamin Wu, Pu Dai and Qionghai Dai.

Zhang, Y., Li, A., Yuan, L. et al. *Cortex-wide imaging in naturally behaving mice with 1-gram wireless mesoscopes.* Nature (2026).
[Published paper](https://doi.org/10.1038/s41586-026-11293-x)

| Source field | Value |
|---|---|
| Archive | `SAM2_Mice.zip` |
| Figshare file ID | `69058690` |
| Bytes | `724781382` |
| Published MD5 | `b86c08e2d11174bf53560453160bb658` |
| Verified SHA-256 | `86871617cc08a954994eb7b053c48a5ed79d99f6d44cf951b88db6b5f53e3883` |
| Source code commit | `80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98` |

The public Figshare record supplies the archive size and MD5. BrainPilotBench verified both and recorded SHA-256 after the complete download.
[Source metadata](https://api.figshare.com/v2/articles/33942097) · [Archive download](https://ndownloader.figshare.com/files/69058690)

## Labels and source scope

The input directory is `SAM2_Mice/benchmark_data/openfield_five_mouse/`.
The label directory is `SAM2_Mice/benchmark_data/ground_truth_bb_labels/`.
The author benchmark identifies these label files as annotated ground truth and uses them for method comparison.
[Author benchmark](https://github.com/Neurallabware/Airscope_toolbox/blob/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/Software/SAM2Mice/SAM2_Mice/benchmark/README.md)

The segmentation-training guide describes SAM2 mask generation, human correction and independent review over three to five refinement rounds.
That description covers segmentation training data. The review history of individual benchmark boxes remains undocumented.
BrainPilotBench retains the released box values and object IDs.
[Annotation guide](https://github.com/Neurallabware/Airscope_toolbox/blob/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/Software/SAM2Mice/training/README.md)

This archive supplies 421 matching image/annotation pairs from one recording.
The author's Drive inventory describes a larger collection. The inspected Drive pages expose a partial listing.
The task scope follows the fully downloaded archive and its verified pairs.
[Author directory description](https://github.com/Neurallabware/Airscope_toolbox/blob/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/Software/SAM2Mice/docs/google_drive_data.md)

## License

The Figshare dataset record grants Creative Commons Attribution 4.0 International for the released archive.
Prepared image and annotation packets retain that license, source attribution and modification notice.
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode.en) · [Dataset license record](https://api.figshare.com/v2/articles/33942097)

The upstream SAM2Mice software uses GPL-3.0-only. Its software license remains separate from the dataset license.
The original source terms contain their applicable warranty disclaimers and limitations of liability.
[Upstream license map](https://github.com/Neurallabware/Airscope_toolbox/blob/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/LICENSE)

## BrainPilotBench transformations

BrainPilotBench pairs images and labels through exact source frame indices.
It decodes the original JPEG images into RGB uint8 arrays and stores them in numeric NPZ packets.
It converts normalized center/width/height boxes into normalized corner coordinates with float64 arithmetic.
It preserves author object IDs and valid empty annotation frames. It does not clip or relabel source boxes.

The split uses three temporal intervals, ten-index boundary trims and sequence resets at every missing image or annotation.
The intervals retain 251 Train, 56 Valid and 75 Test frames. Boundary gaps exclude 39 paired frames.
The task adds an automatic-tracker interface, frozen submissions and separate public/evaluator data roles.
The scoring protocol uses IoU ≥ 0.5, MOTA and IDF1 with explicit frame and identity handling.

The selected inputs exclude model overlays, generated segmentation masks and YOLO training labels elsewhere in the archive.
The task does not supply ground-truth prompts to initialize the tracker.
This protocol is a BrainPilotBench adaptation. Source authors and institutions do not endorse this adaptation or its scores.

## Evaluation access

The original images and labels are public upstream. Evaluator-only access separates Test data from the Agent workflow.
This access boundary does not establish historical secrecy or change the rights granted by CC BY 4.0.
Retain source credits, license links and this modification notice with redistributed data.
