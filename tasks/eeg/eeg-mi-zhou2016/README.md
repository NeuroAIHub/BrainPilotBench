# Zhou2016 motor imagery

Candidate integration status: public-validation runnable definition; no private Test is imported or rerun. Scientific source case `motor_imagery/zhou2016`, frozen source task version `expanded-three-seed-20260923-zhou-v1`, source SHA `a8092dc10956038e445ff0e07f9c0c7e03a10d36`, original public task_spec SHA-256 `f24b704214152c3d6425814dc475c35dabdc1d3c1ad62634c80986b271b26e9e`.

The task-specific `contract.json` binds input [14, 480], 3 classes, 120 Hz, native split `native PredefinedSplit; rule=session-disjoint; valid_split_by=session`, label mapping, train/valid sample counts, metric profile `native-balanced-accuracy-complete-classes`, and exact SHA-256 and byte length of four public files. The source data were previously prepared under the cited native protocol. No EEG arrays are committed here; `availability_status=frozen_manifest_bound_not_downloaded_here` means the public bytes must be supplied or fetched into a hash-verified local cache before an Agent starts.

Before public scoring, run `bash tasks/eeg/_shared/setup-python.sh` from the repository root and set `BPB_EEG_PYTHON` to its printed pinned NumPy 2.2.6 environment. This is separate from the Docker image that executes submitted model code.

`data.lock` pins four public files to an immutable Hugging Face revision. You do not need `BPB_LOCAL_DATA_ROOT`.

From the repository root, run `node dist/cli.js fetch eeg-mi-zhou2016 --public`. Then run `node dist/cli.js prepare eeg-mi-zhou2016 --workspace /absolute/new-workspace`.

For a public-only local package, set `BPB_EEG_PUBLIC_PACKAGE_DIR` to its directory. The setup script checks the original `task_spec.json` SHA-256 and each public file's SHA-256 and size. Do not put private Test files or source-private bindings in that directory or the Agent workspace.

`env/setup.sh` copies only public train/val and group metadata into the Agent workspace. `checks/check.sh` uses the shared, task-agnostic public-validation scorer: it keeps validation y in the trusted parent and executes only the submitted nine required seed files in isolated Docker inference. It refuses official private Test scoring. This task has not independently passed a new BrainPilotBench Agent run; the original accepted source episode and a later BPB validation are distinct lifecycle records.
