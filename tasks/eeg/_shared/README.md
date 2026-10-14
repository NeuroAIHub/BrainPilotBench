# Shared EEG public-validation contract

For task summaries and lifecycle status, see the [EEG task index](../README.md).

These helpers serve 21 imported native protocols and the new full Sleep-EDF stage task.
Each task has an independent ID and source version. Its `contract.json` binds
the source spec, commit, shapes, label mapping, split, counts, metric, and public file hashes.
The Sleep-EDF spec is a new BrainPilotBench version, not an old research task spec.
The public package excludes Test inputs, Test labels, prior scores, private bindings,
and remote host paths.

The first-batch `data.lock` files point to four public files per task at Hugging Face
revision `09240a63ce2ec96050313c59221291114ff8df6f`. Run
`bp-bench fetch <id> --public` to fill the content cache. The fetcher checks each
file's size and SHA-256. `local://` remains an owner-only supply route for
unpublished packages. It is not required for the published first batch. Some
historical Ceph archives contain both `public/` and `private/` files. Never
pass such an archive to an Agent.

For an owner-held mixed archive, run the maintainer-only helper outside any Agent workspace. `python tasks/eeg/_shared/stage-public-from-archive.py --plan --task tasks/eeg/<id> --archive <packet-master.tar>` checks the tar index, the original small public task-spec hash, member paths, sizes, duplicates and link types without writing files. Then run the same command with `--extract --output-root <absolute-private-staging-root>` instead of `--plan`. Extraction copies only the four contract-declared `public/data/` files, checks their exact bytes and SHA-256, and atomically creates `<root>/<id>/<source-version>/` at mode 0700. It refuses an existing destination. The mixed archive, its private/Test members and the original task spec are never copied into this staging tree. Supply that root as `BPB_LOCAL_DATA_ROOT` only for the maintainer's fetch. A plan checks metadata but does not prove the large public-file hashes; only a completed extraction does. The setup script also accepts `BPB_EEG_PUBLIC_PACKAGE_DIR` pointing to an existing public-only package; it verifies the original `task_spec.json` SHA and all four public file hashes before copying anything to the Agent workspace.

The scorer refuses `BPB_OFFICIAL_SCORING=1`: this collection has only public validation. It verifies the frozen validation file, streams its `x.npy` member to a temporary memory-mapped file, keeps `y` in the trusted parent, and passes x only to one read-only, nonroot, networkless Docker worker per submitted seed. Only the nine required seed files are copied to that worker. Extra files are ignored. A missing required file or unsafe path is an error, not a zero score. Run `_shared/setup-python.sh` once to prepare the trusted host scorer with pinned NumPy 2.2.6 in `.cache/eeg/host-venv`; set `BPB_EEG_PYTHON` to the printed path. The worker image is built from this directory's `Dockerfile` and pinned `requirements.txt`; the operator must use an immutable image digest or local image ID. This helper has not run any private Test.

Two metric profiles are explicit. `native-balanced-accuracy-complete-classes` requires all output classes in public validation and averages per-class recall. `native-typing-sparse-macro-torchmetrics-1.9` uses the union of true and predicted classes, including predicted-only classes with zero recall and excluding classes absent from both. A new task with another scoring rule must add and test a separate profile; it must not inherit either profile by default.

`test_boundaries.py` covers all 22 shared classification contracts, hash-bound preparation,
public-only archive staging, invalid paths and members, array shapes, and both metric profiles.
It does not run an Agent or claim scientific acceptance. Historical source-project
results remain tied to their original controller. They do not become BrainPilotBench scores.
The Typing and DICE packets had no Agent run at the audited handoff.
