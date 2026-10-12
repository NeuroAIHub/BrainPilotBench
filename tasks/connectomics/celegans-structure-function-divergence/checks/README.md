# Scoring implementation notes

This candidate keeps the author's numerical protocol at task version 0.6 while changing the execution boundary. The original revision 1 source snapshot and task-local changes are recorded in `../INTEGRATION.md`.

`check.sh` requires the three declared artifacts, an explicit `BPB_PRIVATE_EVAL_DIR`, and a Docker worker image. It never reads an artifact-controlled oracle flag. `evaluate_external.py` computes the reference result in the trusted parent process, then starts `worker_entry.py` in a separate networkless Docker container for each evaluator reconstruction. The candidate sees only the input arrays and its own read-only artifact tree. The parent compares returned statistics and judgments with its independently computed result.

The worker image is built from `worker.Dockerfile` with `env/requirements.txt`. Official scoring must use an immutable image digest. Worker Docker flags remove networking, privileges, writable root, host mounts beyond the submitted artifacts and one input file, and unbounded processes. A failed contract, absent fixture, missing worker image, worker error, or invalid result produces no score sentinel.

The public `--self-test` exercises mathematical helpers and synthetic fixtures. It does not validate the independent worker boundary or real held-out data. `solution/solution.sh` generates the reference analyzer and is scored through the same worker path with genuine evaluator arrays. The task's objective score is a fraction in [0,1]; the accompanying rates are diagnostics. The author rubric is retained for separate qualitative review and does not alter the objective score.

The original author diagnostic scripts and detailed numerical examples remain in the immutable source snapshot named in `../INTEGRATION.md`, outside this candidate task. They are not needed at scoring time.
