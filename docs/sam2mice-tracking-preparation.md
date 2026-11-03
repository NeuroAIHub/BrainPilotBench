# SAM2Mice tracking preparation and evaluation

## Scope and status

The [task](../tasks/animal-behavior/sam2mice-multi-animal-tracking/README.md) predicts mouse boxes and track IDs from original two-dimensional RGB frames.
Its labels come from the author's tracking benchmark ground truth.
Complete archive verification, source decoding, six-frame visual review and split freezing are complete.
Full local CLI acceptance passed, including public preparation, a frozen reference, evaluator preparation and isolated public/private scoring.
No formal Agent result or task-specific HF mirror is published.

The prepared source has 421 image/annotation pairs from one recording.
The frozen intervals retain 251 Train frames, 56 Valid frames and 75 Test frames.
They form 17 Train, seven Valid and six Test sequences. The longest sequence contains 64 frames.
Missing images or labels terminate a sequence. Single-frame sequences remain eligible for detection scoring.

## Source and label evidence

The selected archive is `SAM2_Mice.zip`, Figshare file `69058690`, with 724,781,382 bytes.
Its published MD5 is `b86c08e2d11174bf53560453160bb658`.
Its verified SHA-256 is `86871617cc08a954994eb7b053c48a5ed79d99f6d44cf951b88db6b5f53e3883`.
The [data notice](../tasks/animal-behavior/sam2mice-multi-animal-tracking/NOTICE.md) records the author credits, license and selected archive paths.

The source inspection decoded 502 original JPEGs and parsed 501 GT files.
All paired images have dimensions 1224 × 1024 pixels. Each paired frame contains five author boxes with distinct IDs.
All boxes satisfy the strict normalized coordinate limits. Exact file and decoded-pixel duplicate scans found no repeated images.
The perceptual-hash screen is a similarity diagnostic. Static background pixels can dominate that screen.

The author benchmark identifies the selected directory as ground truth.
The separate segmentation-training guide describes human correction and independent review of training masks.
The review history of individual benchmark boxes remains undocumented.
Six predetermined overlays support the maintainer's image/label correspondence review.
An independent reviewer also inspected five consecutive-frame triplets for image alignment and identity continuity.
The task does not claim a new exhaustive estimate of annotation accuracy.

The available source is one recording with incomplete image/label overlap.
The author's Drive description lists additional files, and the inspected public pages contain partial listings.
The frozen task uses the verified archive subset. Additional Drive data require separate pairing and source review.

## Install the local environment

Use Python 3.12, Node.js and Docker.
Run the commands from the repository root under a nonroot account.
Choose a fresh directory for prepared outputs.

```sh
TRACK_ROOT="$PWD/.cache/sam2mice-tracking-local"
TRACK_COMMON="$PWD/tasks/animal-behavior/_sam2mice_tracking"
TRACK_TASK="$PWD/tasks/animal-behavior/sam2mice-multi-animal-tracking"
python3.12 -m venv "$TRACK_ROOT/venv"
"$TRACK_ROOT/venv/bin/python" -m pip install -r "$TRACK_COMMON/requirements.txt"
export BPB_SAM2MICE_PYTHON="$TRACK_ROOT/venv/bin/python"
npm ci
npm run build
```

The requirements pin NumPy 1.26.4, SciPy 1.12.0, Pillow 10.4.0, pandas 2.2.3 and motmetrics 1.4.0.
The source downloader uses the Python standard library and normal HTTPS certificate verification.

## Download and prepare the source

Download the pinned archive.

```sh
"$BPB_SAM2MICE_PYTHON" "$TRACK_COMMON/fetch_sources.py" --output "$TRACK_ROOT/source"
```

The downloader preserves partial files for resumption and verifies the complete size and MD5.
It records SHA-256 in `source-receipt.json`.

Prepare the selected original images and author labels.

```sh
"$BPB_SAM2MICE_PYTHON" "$TRACK_COMMON/prepare_source.py" \
  --archive "$TRACK_ROOT/source/SAM2_Mice.zip" \
  --output "$TRACK_ROOT/prepared-source"
```

The helper reads only the declared raw-image and GT directories from the ZIP.
It rejects unsafe paths and linked members. It preserves source files and pairs exact frame indices.
Its output includes `paired-frames.json`, `audit.json`, `complete.json` and predetermined visual overlays.
The complete receipt binds every prepared file by bytes and SHA-256.
Source preparation and diagnostic files remain owner-only.

## Reconstruct the frozen packets

The checked-in [source review](../tasks/animal-behavior/sam2mice-multi-animal-tracking/source-review.json) binds the exact preparation and visual inspection.
The [split review](../tasks/animal-behavior/sam2mice-multi-animal-tracking/split-review.json) binds the pre-analysis assignment.
Reconstruction reuses those reviews for matching bytes. It does not claim a fresh human inspection.

The source-index extent is `n=496`. Boundaries are `floor(0.6*n)=297` and `floor(0.8*n)=396`.
The retained intervals are Train `[0,287)`, Valid `[307,386)` and Test `[406,496)`.
The ten-index trims on each side exclude 39 paired frames in total.
Every missing image or GT file ends a sequence. Each role preserves the remaining legal pairs.

Build the public and evaluator packets from the checked-in reviews.

```sh
"$BPB_SAM2MICE_PYTHON" "$TRACK_COMMON/package_task.py" build \
  --prepared "$TRACK_ROOT/prepared-source" \
  --review "$TRACK_TASK/source-review.json" \
  --split "$TRACK_TASK/split-review.json" \
  --output "$TRACK_ROOT/packets"
"$BPB_SAM2MICE_PYTHON" "$TRACK_COMMON/package_task.py" bind \
  --packets "$TRACK_ROOT/packets" --task-dir "$TRACK_TASK" \
  --local-root "$TRACK_ROOT/local-source" --materialize-only
```

`--materialize-only` compares regenerated metadata against the checked-in contract and locks.
Changed bytes or partial bindings produce an error.
The public packet contains Train/Valid frames and labels. The evaluator packet contains Test frames and labels.
Both packets use numeric NPZ files and exact manifest bindings.

## Prepare a public workspace

Set a public cache and fetch the prepared public packet.

```sh
export BPB_CACHE_ROOT="$TRACK_ROOT/public-cache"
BPB_LOCAL_DATA_ROOT="$TRACK_ROOT/local-source" node dist/cli.js fetch sam2mice-multi-animal-tracking --public
node dist/cli.js prepare sam2mice-multi-animal-tracking --workspace /absolute/agent-workspace
```

The feature NPZ contains only `frames`, with dtype uint8 and shape `[T,H,W,3]`.
The truth NPZ contains `detections`, with dtype float64 and shape `[N,6]`.
Each detection contains a local frame index, object ID and normalized `x1,y1,x2,y2` coordinates.

The model interface is `load_model(config, weights_path).predict(frames, context)`.
The context contains the task ID, image width and image height.
The model supplies floating-point rows with the same six-column schema.
The contract allows 64 detections per frame, 1,024 distinct IDs per sequence and 128 frames per sequence.
Track IDs are integers in `[0,2**31-1]`. Coordinates remain within `[0,1]` with strictly positive box width and height.

The model starts each sequence from original frames with fresh state.
The inference interface excludes GT prompts, source frame indices and role metadata.

## Run the fixed reference

Create a manual run and a separate reference workspace.

```sh
node dist/cli.js run sam2mice-multi-animal-tracking --adapter manual --agent fixed-reference-check \
  --out "$TRACK_ROOT/bundles" --run-id reference --workspace "$TRACK_ROOT/reference-workspace"
(cd "$TRACK_ROOT/reference-workspace" && bash "$TRACK_TASK/solution/reference.sh")
node dist/cli.js run sam2mice-multi-animal-tracking --adapter manual --resume "$TRACK_ROOT/bundles/reference"
node dist/cli.js submit verify "$TRACK_ROOT/bundles/reference"
TRACK_BUNDLE="$TRACK_ROOT/bundles/reference"
```

The reference estimates its background, box area and object count from Train data only.
It uses image components and nearest-centroid matching for tracking.
This reference run exercises the submission and scoring interfaces. Formal Agent evaluation remains separate.

Build the inference image and record its immutable ID.

```sh
docker build -f "$TRACK_COMMON/Dockerfile" -t bpb-sam2mice-tracking:local "$TRACK_COMMON"
TRACK_IMAGE="$(docker image inspect bpb-sam2mice-tracking:local --format '{{.Id}}')"
node dist/cli.js score "$TRACK_BUNDLE" --isolation docker \
  --inference-image "$TRACK_IMAGE" --python "$BPB_SAM2MICE_PYTHON"
```

Each inference container receives one RGB sequence and the frozen model.
The container runs as a nonroot user with network access disabled, two CPUs and 2 GiB memory.
Only its bounded prediction file is writable. The trusted host loads the labels and computes scores.

## Prepare the evaluator and score Test

After the submission is frozen, prepare the evaluator on the trusted owner host.

```sh
BPB_LOCAL_DATA_ROOT="$TRACK_ROOT/local-source" node dist/cli.js prepare-evaluator sam2mice-multi-animal-tracking \
  --fetch --evaluator-root "$TRACK_ROOT/owner/evaluator" --cache-root "$TRACK_ROOT/owner-cache"
node dist/cli.js score "$TRACK_BUNDLE" --private \
  --evaluator-root "$TRACK_ROOT/owner/evaluator" --isolation docker \
  --inference-image "$TRACK_IMAGE" --python "$BPB_SAM2MICE_PYTHON"
```

The evaluator root and cache stay outside the Agent workspace and public cache.
Private scores go to `scores.private.json`. Public validation scores remain separate.
The source images and labels were publicly released upstream. Evaluator-only access protects the experimental workflow and preserves the source license rights.

MOTA and IDF1 use IoU ≥ 0.5 matching and separate identity histories for each sequence.
Overall scores pool the metric counts across sequences. Negative MOTA values remain valid.
The task measures held-out temporal segments from one recording and retains the small-subset limits described in its task guide.
