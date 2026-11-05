The optional pose-only Ridge reference fits on the public 54-video Train set.
From a prepared Agent workspace, run `bash solution/solution.sh` to create
exactly `submission/model.py`, `submission/config.json`, and
`submission/weights.npz`. The script does not read Test pose or labels. The
public 11-video Valid check can score this reference; that score is not
private Test acceptance or a ResiFuse paper score.
In a fresh benchmark validation bundle with `artifacts/` but no `data/`, the
same script stages only the Node-verified public files from the content-addressed
cache and writes `artifacts/submission`. It never reads the original source
NPY, H5, Test pose, or Test labels.
