# SpanishBCBL EEG typing

Candidate integration status: public-validation runnable definition; no private Test is imported or rerun. Scientific source case `typing/default`, frozen source task version `d-typing-full-v3-20261012-r1`, source SHA `a8092dc10956038e445ff0e07f9c0c7e03a10d36`, original public task_spec SHA-256 `5e482fdbb948102d728d1a992a2683796cda22999a4f07caaa3531aa3d9ebeae`.

The task-specific `contract.json` binds input [61, 120], 29 classes, 120 Hz, native split `native SimilaritySplit; rule=native sentence-similarity cluster-disjoint`, label mapping, train/valid sample counts, metric profile `native-typing-sparse-macro-torchmetrics-1.9`, and exact SHA-256 and byte length of four public files. The source data were previously prepared under the cited native protocol. No EEG arrays are committed here; `availability_status=prepared_public_packet_not_downloaded_here` means the public bytes must be supplied or fetched into a hash-verified local cache before an Agent starts.

Before public scoring, run `bash tasks/eeg/_shared/setup-python.sh` from the repository root and set `BPB_EEG_PYTHON` to its printed pinned NumPy 2.2.6 environment. This is separate from the Docker image that executes submitted model code.

`data.lock` pins four public files to an immutable Hugging Face revision. You do not need `BPB_LOCAL_DATA_ROOT`.

From the repository root, run `node dist/cli.js fetch eeg-typing-spanishbcbl --public`. Then run `node dist/cli.js prepare eeg-typing-spanishbcbl --workspace /absolute/new-workspace`.

For a public-only local package, set `BPB_EEG_PUBLIC_PACKAGE_DIR` to its directory. The setup script checks the original `task_spec.json` SHA-256 and each public file's SHA-256 and size. Do not put private Test files or source-private bindings in that directory or the Agent workspace.

`env/setup.sh` copies only public train/val and group metadata into the Agent workspace. `checks/check.sh` uses the shared, task-agnostic public-validation scorer: it keeps validation y in the trusted parent and executes only the submitted nine required seed files in isolated Docker inference. It refuses official private Test scoring. This task has not independently passed a new BrainPilotBench Agent run; the original accepted source episode and a later BPB validation are distinct lifecycle records.
