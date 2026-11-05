The optional PCA reference learns only from the 784 keypoint-only UserTrain
clips. From a prepared Agent workspace, run `bash solution/reference.sh` to
create exactly `submission/model.py`, `submission/config.json`, and
`submission/weights.npz`. This task has no public Oracle labels or public
validation score. The frozen model must be evaluated through the owner-only
private route to fit the six Ridge probes and score Test; do not present the
reference export as a benchmark result.
