# Candidate integration record — 2026-10-12

Source contribution: `celegans-structure-function-divergence`, revision 1, author task version `0.6`. The exported contribution snapshot has SHA-256 `2536b5091a4f6fff9d60c022720e84c08dacba20955a2289a1a12574b4134e09`. This task keeps version `0.6` and declares `integration_status: candidate`; these local changes are not an author release or a scientific protocol bump.

## Changes from the source snapshot

- Removed the submission-controlled `oracle_mode.flag` scoring path. The reference solution now passes through its `DivergenceAnalysis.analyze` implementation on the genuine evaluator arrays.
- The trusted scorer keeps its reference result in the parent process. Submitted Python is imported only by a separate Docker worker with one input reconstruction, read-only artifacts, no network, no evaluator files or Docker socket, limited memory/CPU/PIDs, and bounded output and runtime.
- Replaced the summary and public review documents that contained evaluator-only numerical answers. The author diagnostic scripts and original detailed examples remain in the source snapshot, not this candidate.
- The objective scorer is the only automatic scorer. The author rubric is retained in a sanitized form for separate qualitative review; expert calibration is pending.
- Corrected the generic hub judgment so a statistically significant **negative** degree correlation cannot satisfy “significantly positive.” The original scientific metrics and task version remain otherwise unchanged.
- Updated the worker to Python 3.13. The author's pinned `numpy==2.5.1` cannot be installed on Python 3.11; the same fixed package set installed on the host and in the worker image.
- Required an explicit private evaluator directory outside the task/Agent workspace. The legacy private-path fallback was removed.

## Local validation

The repository's fetch command downloaded all six `data.lock` entries into the gitignored task test cache and verified their declared content hashes and byte counts. Both setup scripts built public and evaluator-only arrays from that cache. Their derived-array hashes matched a separate manual source staging pass. No source data or generated arrays are included in this task directory.

The worker image used in the checks was `bpb-celegans-candidate@sha256:71a8c8ac1e128f40327bb624dfac3731037b646277d5785e1a7939d9bb3812bf` (`linux/arm64`). The official local command was:

```sh
BPB_PYTHON="$PWD/.cache/celegans/venv/bin/python" \
BPB_PRIVATE_EVAL_DIR="$PWD/.cache/celegans/official-private" \
TMPDIR="$PWD/.cache/celegans" \
node dist/cli.js score .cache/celegans/reference \
  --isolation docker --official \
  --inference-image 'bpb-celegans-candidate@sha256:71a8c8ac1e128f40327bb624dfac3731037b646277d5785e1a7939d9bb3812bf'
```

Observed on the actual three evaluator reconstructions: `state=scored`, `score=1.0`, `stat_match_rate=1.0`, `judgment_accuracy=1.0`, `judgment_skill=1.0`; wall time 11.43 seconds on the final warm run. The repository `validate` command passed its reference/NOP gate. The synthetic mathematical self-test passed 26 checks. A bundle containing all required paths plus an attacker-controlled `oracle_mode.flag`, but an invalid contract and analyzer, produced `scoring_failed`, an empty metric object, and no score sentinel. Artifact mutation checking passed during official scoring.

Detailed local receipts, frozen reference artifact hashes, source/derived hashes, and generated arrays are retained only under the gitignored `.cache/celegans/` directory. No submitted Agent experiment, expert rubric acceptance, x86_64 worker build, public release, or production deployment was performed. Data redistribution terms require maintainer review before publication.
