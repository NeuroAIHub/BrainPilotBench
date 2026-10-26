# CalMS21 preparation and metric helpers

Source: [CaltechDATA record 10.22002/D1.1991](https://data.caltech.edu/records/s0vdx-0k302), version 1.0. The record's `readme.md` defines JSON field shapes, task vocabularies, and official Train/Test roles. The helpers consume the native JSON, not the upstream `allow_pickle=True` conversion script.

For Task1, use an isolated Python 3.11+ environment with [calms_requirements.txt](calms_requirements.txt) and an already downloaded official `task1_classic_classification.zip` (457,357,950 bytes; MD5 `8a02654fddae28614ee24a6a082261b8`; SHA-256 `f1cd2f46771cc3834020d187604da53e5ff330121f5a816146f14192fb0bf427`):

```bash
python3 -m venv .cache/calms21-local-venv
.cache/calms21-local-venv/bin/python -m pip install -r tasks/animal-behavior/_shared/calms_requirements.txt
.cache/calms21-local-venv/bin/python tasks/animal-behavior/_shared/calms_prepare.py --task task1 \
  --zip .cache/mouse-expansion-20261026/calms/task1_classic_classification.zip \
  --output .cache/mouse-expansion-20261026/calms/task1-prepared-v2
.cache/calms21-local-venv/bin/python tasks/animal-behavior/_shared/calms_reference.py \
  --prepared .cache/mouse-expansion-20261026/calms/task1-prepared-v2 \
  --report .cache/mouse-expansion-20261026/calms/task1-reference-local.json
.cache/calms21-local-venv/bin/python tasks/animal-behavior/_shared/calms_prepare.py \
  --verify-prepared .cache/mouse-expansion-20261026/calms/task1-prepared-v2
```

The report path must also be new. Do not overwrite the checked-in evidence files.

The output path must be new. The ZIP is checked before parsing. No member is extracted. Duplicate JSON keys are rejected. Numeric `NPZ` files are loaded with `allow_pickle=False`. The `public/train` and `public/valid` directories contain only official-Train sequences. The `owner/test` directory contains official-Test arrays and labels and must remain evaluator-only.

The output root and its subdirectories use mode 0700. NPZ and JSON files use mode 0600. Symlink path components are rejected. Each manifest binds sequence IDs, array shapes/dtypes, byte lengths and file SHA-256 hashes to the official source hash. The preparer writes `complete.json` last, after all file checks. An output without this marker is incomplete.

The public reference checks the complete public file set before reading Train/Valid. It does not open owner Test labels. The separate task materializer creates public and evaluator packets. Agent setup copies only the public whitelist.

The Valid split is a BrainPilotBench adaptation: whole official-Train sequence IDs ranked by SHA-256 using `bpb-calms21-valid-v1:` and first `ceil(20%)` held out. It is deterministic and sequence-disjoint. No animal-identity disjointness is asserted. The reference uses a diagonal shared-covariance pose/confidence classifier fitted on public Train. Its Valid F1 is a local preparation probe, not an official CalMS21 Test or Agent score.

The earlier `task1-prepared` and `calms-task1-reference.json` from this same local pass lack per-file hash binding and are superseded as acceptance evidence; they were left intact. Use the `-v2` prepared root and reports for acceptance review.

`calms_metrics.py` accepts evaluator-owned numeric truth and probabilities from an isolated predictor. Task1/2 average F1 over attack, investigation, and mount. The `other` frames contribute errors but are not a fourth averaged class. Task2 scores each annotator group, then averages group scores. Task3 averages positive-class F1 over all seven behaviors. Missing sequences, groups, behaviors, or class mappings cause an error. The helper does not execute untrusted model code.

All three task packages now include the isolated runner and source-prepared evaluator binding. Their fixed-reference CLI acceptance passed, including owner Test interfaces. These checks do not provide Agent benchmark results. The [complete preparation guide](../../../docs/mouse-task-preparation.md) describes local materialization, public staging and private scoring.

The source's licensing metadata needs reconciliation: the associated paper states a noncommercial share-alike term, while platform metadata has presented CC BY 4.0. This preparation makes no license resolution or redistribution claim. No dataset bodies are committed or uploaded to Hugging Face.
