# Fixed tracking reference

The reference estimates the arena background and typical object area from Train data.
It applies foreground extraction, connected-component detection and nearest-centroid assignment.
Each sequence starts with fresh tracking state.
All configuration constants are fixed before validation or Test scoring.

Run `bash solution/reference.sh` from a workspace with prepared public data, using the task's absolute script path.
The script writes `submission/model.py`, `config.json` and numeric `weights.npz`.
This inexpensive reference exercises the submission and scoring interfaces.
Its results do not represent a research Agent or reproduction of the paper's reported model scores.
