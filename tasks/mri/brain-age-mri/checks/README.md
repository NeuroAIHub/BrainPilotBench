# Brain-age scorer

`checks/check.sh` is the BrainPilotBench `exec-script` entry. It requires an
evaluator-only data directory, a separate score directory, Python 3.11 task
environment, and an immutable Docker image digest. The submitted script sees
images and subject IDs only; `labels/true_ages.csv` stays in the trusted parent.

The script emits one flat numeric `BPB_SCORES` payload only on complete success.
`test_mae` is in years and minimized. `score=1/(1+test_mae/10)` is a derived
display measure. Pearson correlation is undefined for a constant predictor;
`pearson_r_defined=0` marks the numeric placeholder in `test_pearson_r`.

The scorer checks exact IDs, finite predictions, model size, artifact
immutability, and Docker exit status. A missing file, invalid output, timeout,
or missing private data yields a nonzero exit with no score sentinel. The local
candidate Docker image digest is evidence of an isolated smoke and reference
run only; it is not a published multi-architecture release artifact.
