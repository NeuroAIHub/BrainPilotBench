# SAM2Mice multi-animal detection and tracking

Can a model locate each mouse and preserve its identity across video frames?
Predict bounding boxes and persistent track IDs from original two-dimensional images of five mice.
The evaluation uses the author's ground-truth boxes from the Airscope SAM2Mice benchmark.

## Task at a glance

| Field | Contract |
|---|---|
| Input | RGB frames, `uint8[T,1024,1224,3]`, with up to 128 frames per sequence |
| Output | Local frame index, track ID and normalized `x1,y1,x2,y2` box coordinates |
| Labels | Author `ground_truth_bb_labels`, paired with original images by source frame index |
| Split | Train 251 frames / 17 sequences, Valid 56 / 7, Test 75 / 6 |
| Primary metric | MOTA, including negative values |
| Secondary metric | IDF1 |
| Matching | IoU of at least 0.5 |
| Evaluation scope | Held-out temporal segments from one source recording |
| Status | Source review, frozen split and isolated public/private CLI acceptance passed locally. No Agent result is available. |

## Author labels and source review

The author benchmark evaluates SAM2Mice, DeepLabCut and SuperAnimal against annotated bounding boxes.
The release identifies the selected boxes as benchmark ground truth.
A separate guide describes automatic mask generation, human correction and independent review for segmentation training data.
The review history of individual benchmark boxes remains undocumented.
[Author benchmark](https://github.com/Neurallabware/Airscope_toolbox/blob/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/Software/SAM2Mice/SAM2_Mice/benchmark/README.md) · [Annotation guide](https://github.com/Neurallabware/Airscope_toolbox/blob/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/Software/SAM2Mice/training/README.md)

The verified archive contains 502 original JPEG frames and 501 annotation files in the selected directories.
Exactly 421 frames have both files. Each paired frame contains five annotated mice.
All selected images decode at 1224 × 1024 pixels. Every box passes finite-value, identity and strict image-boundary checks.
Six predetermined source frames received visual review with annotation overlays.
An independent reviewer also inspected 15 frames in five consecutive-frame triplets for alignment and identity continuity.
This review covers selected frames and automated structural checks. It does not establish a new exhaustive annotation-accuracy estimate.

The [source review](source-review.json) binds the prepared files and review evidence.
The [data notice](NOTICE.md) records attribution, licenses and transformations.

## Frozen split

The split uses the paired source-index extent `n=496` and boundaries `floor(0.6*n)=297` and `floor(0.8*n)=396`.
Ten source indices on each side of both boundaries form exclusion gaps.

| Role | Retained source-index interval | Paired frames | Sequences |
|---|---|---:|---:|
| Train | `[0,287)` | 251 | 17 |
| Valid | `[307,386)` | 56 | 7 |
| Test | `[406,496)` | 75 | 6 |

The gaps exclude 39 paired frames. Each missing image or annotation ends a sequence.
All remaining legal pairs are retained, including single-frame sequences. The longest retained sequence contains 64 frames.
The tracker starts with fresh state for each sequence. It receives no ground-truth initialization prompt.
The [split review](split-review.json) records the fixed assignment before model fitting.

This small task measures detection and tracking within one recording.
Short sequences provide limited evidence about long-duration identity preservation. Cross-recording, cross-environment and new-animal generalization require additional data.

## Submission and scoring

Each feature NPZ contains exactly `frames` as a `uint8[T,H,W,3]` array.
Each truth NPZ contains exactly `detections` as a `float64[N,6]` array.
Its columns are `local_frame`, `track_id`, `x1`, `y1`, `x2`, and `y2`.
Box coordinates use the range `[0,1]` and must have positive width and height.

Submit exactly `submission/model.py`, `submission/config.json` and numeric `submission/weights.npz`.
`load_model(config, weights_path)` returns an object with `predict(frames, context)`.
The context contains the task ID, image width and image height.
The model returns a numeric floating-point array with shape `[N,6]`. The worker stores predictions as float64.
An empty prediction uses shape `[0,6]`.

Frame indices start at zero within each sequence. Track IDs are nonnegative integers with an upper limit of `2**31-1`.
Keep each predicted ID consistent within a sequence. The scorer matches predicted IDs to author IDs through detections.
The output allows up to 64 detections per frame and 1,024 distinct IDs per sequence.
Each frame permits at most one detection for each predicted ID.

The evaluator matches boxes at IoU ≥ 0.5 and maintains a separate identity history for each sequence.
It pools counts across sequences for the overall MOTA and IDF1 values.
MOTA equals `1 - (misses + false positives + identity switches) / ground-truth detections`.
Negative MOTA values remain valid scores. Missing predictions count as missed detections.

The scorer preserves explicit source frame correspondence and object IDs through missing detections.
These adaptations address assumptions in the author's input loader. They do not claim exact reproduction of the paper's benchmark numbers.

## Prepare and evaluate

The task currently uses local source-prepared packets. A task-specific HF mirror is not yet published.
The [preparation guide](../../../docs/sam2mice-tracking-preparation.md) covers source download, packet reconstruction, submission and isolated scoring.
The [contract](contract.json), [public lock](data.lock) and [evaluator lock](evaluator.lock) bind the prepared bytes.

The fixed reference estimates a background image and box-size statistics from Train data.
It then uses image components and nearest-centroid assignments to detect and track mice.
The fixed reference passed the complete CLI workflow, including isolated public and owner-only Test scoring.
Its Valid MOTA was -0.42857 and IDF1 was 0.17039. This weak reference provides an engineering check.
An empty detector has MOTA 0, so the reference is unsuitable as evidence of competitive tracking performance.
The [acceptance record](../../../reports/sam2mice-tracking-20261103/acceptance.json) binds the task and scoring code. No formal Agent result is available.

The source images and annotations are public upstream. Test access controls protect the evaluation workflow.
The inference container receives the RGB sequence and frozen model. Ground-truth files and source diagnostics remain outside the container.
Private scores stay in the evaluator-owned result file.
