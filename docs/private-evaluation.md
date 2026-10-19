# Private evaluation for maintainers

Agents work with public Train/Valid data. Maintainers evaluate a completed, frozen submission against separate Test data.
The new private route supports 29 tasks: 21 EEG, six invasive recordings, brain-age MRI, and C. elegans.
It does not replace public validation or publish Agent benchmark results.

## Data and scope

The [private task directory](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Private/tree/62ff438a727aa5ca72c688526410930c8f1f664b/tasks) requires an authorized Hugging Face account.
Its 301 data files total 8,353,488,018 bytes. These are task-specific evaluator packages, not a mirror of every raw recording.
Each supported task has an `evaluator.lock` that maps the published files to its native directory layout.
Its `data.lock` pins the HF revision, sizes, and SHA-256 hashes.

| Route | Tasks | Behavior |
|---|---:|---|
| New hosted evaluator packages | 29 | Use the commands below. |
| Retained private tasks | 3 | BCI-IV-2a, Sleep-EDF, and TOPS keep their existing evaluator setup and scoring commands. |
| Original-source access | 78 | Follow the source terms and task guide. No Test payload is mirrored by this route. |
| No independent or official Test | 2 | RSC has no separate private package here. Wilson exp2 has no official Test. |

Source-only entries include 75 Psych-101 experiments, FALCON H1, native BNCI2014, and Wang2017.
Psych-101 and H1 prohibit redistribution. Redistribution permission for the latter two processed packages is not confirmed.
Their absence is not a download failure. This command does not create substitute or synthetic Test data.

## Prepare one evaluator

Install Node.js and the task's Python dependencies from its README. Build the CLI with `npm run build`.
Use the existing `hf auth login` session, or supply an authorized token through the environment.
Do not store a token in the repository or pass it to the Agent.

Run this command on the trusted evaluator host:

```sh
node dist/cli.js prepare-evaluator eeg-mi-barachant2012 \
  --evaluator-root /absolute/owner/alexmi/evaluator \
  --cache-root /absolute/owner/evaluator-cache \
  --fetch \
  --python /absolute/task-venv/bin/python
```

Use a fresh output directory whose last component is `evaluator`.
Keep it and its cache outside the Agent workspace, submission bundle, and public cache.
The command checks every selected file, then copies it with owner-only permissions.
It accepts an existing output only when its completion receipt and file hashes match.
An incomplete output fails closed. Inspect it, then use a fresh output directory.

The default private cache is `$XDG_CACHE_HOME/brainpilot-bench-evaluator`, or `~/.cache/brainpilot-bench-evaluator`.
`BPB_EVALUATOR_CACHE_ROOT` can select another owner-only cache.
Unset evaluator variables before starting an Agent.

For a task with `evaluator.lock`, `fetch <id> --private` downloads only that file whitelist.
It does not fetch older raw-source entries that also appear in `data.lock`.
`--all` selects the public files plus this evaluator whitelist, in separate caches.

MRI preparation safely unpacks the locked archive into `evaluator/prepared/`.
C. elegans preparation also downloads three pinned public source files into the owner cache and runs the existing scientific transform.
Both record output hashes and recheck them before and after scoring.
Other hosted tasks retain their native `test/` or `derived-v2/` layout.

## Score a completed submission

Stop the Agent and select its final submission before Test evaluation. Do not tune the model against Test feedback.
Use the task's inference image, pinned by an immutable digest or local image ID.
The trusted Python interpreter also needs the task's evaluator dependencies.

```sh
node dist/cli.js score /absolute/submission-bundle \
  --private \
  --evaluator-root /absolute/owner/alexmi/evaluator \
  --isolation docker \
  --inference-image '<task-image>@sha256:<64-hex-digest>' \
  --python /absolute/task-venv/bin/python
```

The CLI checks the bundle, snapshots every submitted artifact, and invokes the trusted task scorer.
Submitted model code runs in a restricted Docker container with no network access.
Only required inference inputs and frozen model files enter that container. Labels, mappings, credentials, and owner caches stay outside it.
The scorer rejects changed artifacts or evaluator data. Failures remain unscored, not zero.
The new route requires the standard `docker` executable; it does not support a custom `--docker-binary`.

Results go to `scores.private.json`, separate from the default `scores.json` and public leaderboard input.
The private result identifies its evaluation scope, data revision, and submission-freeze hash.
The default `score` command keeps each task's existing behavior.
For EEG and the public invasive scorers, that default remains public validation.

`--private` does not mean an official upstream competition score. Do not combine it with `--official`.
FALCON-derived tasks retain BrainPilotBench splits. Their results are not official FALCON leaderboard results.
EEG keeps the original class mapping, metric profile, and three-seed submission contract.
Sleep-EDF reads its frozen shard pairs in bounded batches.

## Validation limits

Representative checks cover the download and scoring integration. They do not evaluate every model on every Test set.
The local integration checks include a Train-only EEG reference, existing BCI IV-4 and C. elegans references, and MRI preparation.
Other supported tasks receive file-binding, interface, and failure-path checks.
No new comparative Agent result follows from these checks.
The historical scientific acceptance records remain unchanged and retain their original scope.
The [integration record](../reports/private-evaluator-integration-20261019.json) lists the tested paths and the checks that did not run.
