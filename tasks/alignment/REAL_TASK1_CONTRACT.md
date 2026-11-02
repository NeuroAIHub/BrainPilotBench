# Real Task1 server draft

Status: implemented for server validation, **not executed or accepted on real data**.
Task ID `alignment-pereira2018-analysis`, staged version `0.1-server-draft`.
The canonical candidate remains inactive. This protocol uses the pinned upstream
`Pereira2018.384sentences-ridge` implementation, not the synthetic NumPy solver.

The input directory is a hash-bound `bpb-brainscore-cache/1` packet:

- `config.json`: immutable model/tokenizer revisions, layer order, `task1_layer`.
- `stimuli.json`: rows in brain/feature order with stimulus ID/text, passage label,
  passage index, and the upstream story-group coordinate.
- `features/layer-NNN.npy`: float32 `[presentation, feature]`; NNN indexes `config.layers`.
- `brain.nc`: official processed assembly with subject, neuroid, region and stimulus coordinates.
- `ceiling.json`, `protocol.json`, `runtime.json`, and `manifest.json`.

Implement `python submission/analyze.py --inputs DIR --output DIR`. Use the
declared task1 layer. No download or access to maintainer reference paths is needed.
Match X/Y by stimulus identity, retain the upstream story groups and 10-fold
GroupKFold seed 1234, use the pinned upstream RidgeGCVTorch and its training-only
alpha selection. Its candidate alphas are 0.001 through 1000 in powers of ten.
Do not substitute the fixture's fixed alpha, subject-weighted aggregation or
unclipped normalization. The official correlation contains a numerical epsilon.

The output directory is initially empty and already exists in the worker.
Required outputs:

1. `analysis_config.json`: exact keys `schema=bpb-real-analysis-config/1`,
   `benchmark`, `upstream_commit`, `model` (the config's model object), `layer`,
   `input_manifest_sha256` (SHA-256 of the input manifest bytes).
2. `results/summary.json`: exact keys `schema=bpb-real-alignment-summary/1`,
   `synthetic_only=false`, `benchmark`, `upstream_commit`, `layer`,
   `input_manifest_sha256`, `acceptance=server-validation-pending`, `raw_score`,
   `ceiling`, `normalized_score`, and `unclipped_normalized_score`.
3. `results/fold_scores.csv`: columns `fold_id,subject_id,neuroid_id,pearson_r`;
   one row per fold/neuroid. Folds use upstream iteration order `fold-0`...`fold-9`.
4. `results/predictions.npz`: `values` float64 `[prediction_row, neuroid]`, plus
   Unicode `fold_ids`, `stimulus_ids`, `neuroid_ids`. Row and column order may vary
   if identities and values are preserved without missing/duplicate entries.
5. Nonempty `report.md` explaining the method, raw/normalized scores and limits.
   Free prose is not automatically assessed.

For each fold, the official raw aggregate is the median correlation across all
neuroids; the overall raw score is the mean over folds. Normalization divides by
the cached official ceiling, then clips to [0,1]. Do not interpret clipping as
evidence that different layers have identical raw predictive performance.

The trusted parent computes its own reference and executes the submitted program
in Docker without network or access to the reference directory. It compares both
saved artifacts (when a bundle is supplied) and rerun outputs. Provisional
tolerances are atol=1e-6 and rtol=1e-5; they require server calibration. Default
worker limits are 4 CPUs, 8 GiB, 128 PIDs, and 900 seconds; these are uncalibrated.
The draft currently checks one real packet and does not replace the synthetic
suite's metamorphic cases or constitute full scientific/Agent acceptance.
