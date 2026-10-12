# First-stage reference validation — 2026-10-12

This record describes the initial 19-interface stage and its four real references.
The current inventory and subsequent checks are in [coverage-expansion.md](coverage-expansion.md).

Historical validation baseline: `feat/shared-task-collection`, based on
`1bb49ede1ab99a4d370f066d431d59926ea1c1ad`. This record is not a release or
deployment acceptance. The independent EEG and Psych research projects were not
modified. Issues #63 and #65 remain deferred.

## Collection inventory

At this stage, the catalog contained 110 task/protocol records, not 110 independent datasets or
completed experiments. Nineteen have runnable interfaces: four preserved legacy
tasks, one native EEG task, twelve Psych tasks, and two standalone contributions.
Eleven non-representative Psych interfaces received structure checks only.

The 91 remaining records are candidates: 27 EEG frozen task/data bindings have
not been imported; 64 Psych records have data packages but no defined response
space/scoring contract. They have no placeholder scorer or discoverable task YAML.
The candidates' metadata are structurally checked; they are not runnable entries.

## Four real-data reference checks

| Task | Prepared data and reference | Result | Boundary |
|---|---|---|---|
| `eeg-mi-bnci2014` | 2,880 train / 1,152 valid EEG windows; fixed CPU ridge; three saved seed states | Public balanced accuracy 0.3897569444 | Native subject-grouped protocol; no private Test |
| `psych101-lefebvre2017behavioural-exp1` | 35 train participants / 3,360 responses; 9 valid participants / 864 responses; fixed stay/switch reference | Public response NLL 0.5783184149; uniform reference 0.6931471806 | Causal-prefix Docker inference; no private Test |
| `celegans-structure-function-divergence` | Six pinned source files fetched and prepared; reference analyzer on three held-out reconstructions | Objective pipeline score 1.0 | Trusted parent computes reference statistics; isolated submitted analyzer |
| `brain-age-mri` | 449 public T1 MRI subjects; fixed 8³-voxel CPU Ridge; one frozen evaluation on 112 held-out subjects | Scoring completed; private metrics and receipts retained outside task source | Hidden ages stay outside inference; no hidden-result tuning |

EEG initially targeted AlexMI. Its original public array path had not survived
the server migration. The representative switched to the available, hash-matched
native BCI-IV-2a package. This does not substitute its split for the legacy
`bciciv-2a` task. The deterministic seed triplets are single reference submissions,
not three independent Agent episodes. No paid Agent/API experiments ran.

Local detailed evidence lives in the ignored cache:

- `.cache/eeg/evidence.json`, `run/eeg-public-validation.json`, `negative-checks.json`
- `.cache/psych101/representative/evidence.json`
- `.cache/celegans/integration-receipt.json`
- `.cache/brain-age/evidence.json`

Each record binds actual input hashes, environment/image identity, artifact
hashes and scoring output. Data, saved models and private evaluator results stay
outside Git. The MRI contributor's source/split assurance is accepted for this
integration; it is not a pending request for more provenance materials.

## Code and structure checks

- `npm run build`: passed.
- `npm test`: 222 passed, 0 failed, 0 skipped with Docker fixtures and an existing
  numerical Python environment on PATH. This is local evidence, not remote CI.
- Original EEG preprocessing unit checks: 9 passed.
- `npm run test:collection`: 110 unique records, 19 runnable, 91 candidates;
  file paths, contract fields, categories, metric directions and catalog agree.
- `npm run test:docs`: passed for all 19 discoverable tasks.
- `bp-bench validate all --schema-only`: passed, including the example task.
- Legacy reference/NOP gates: passed after selecting the numerical Python
  environment. These remain their original lightweight fixtures, not new full runs.
- All four legacy task YAML files are byte-identical to the base commit.
- New Python sources compile; `git diff --check` passes.

New scorers keep submitted Python in Docker. EEG negative checks reject empty
submissions, parent-directory symlinks and forged score sentinels. Psych keeps
current answers in the host controller and refuses official private-Test mode.
The worm's obsolete `oracle_mode.flag` shortcut is removed and its negative
submission fails without a score. Brain-age checks archive paths, finite values,
subject IDs and submission immutability. No task worker container remained active
after the checks. These checks are bounded evidence, not a formal sandbox proof.

Research budgets may be explicitly null. Scorer timeouts remain finite. Primary
metrics carry direction and units; MAE/NLL minimize, accuracy maximizes, and
diagnostic values do not determine ranking. Results from different task versions
remain separate.

## Remaining publication work

This candidate is usable locally with the documented data packages. It is not a
new public benchmark release. EEG and brain-age archives lack permanent public
mirrors; images are local and tested on arm64. Psych's full 859 MB source
download/reconstruction route was not run; its verified published-package route
was. Other eleven Psych tasks and historical frozen models were not data-tested.
Candidate entries still need their missing bindings or response contracts.

Before an eventual release, review redistribution/hosting for the actual assets,
verify the intended supported platforms, and approve concrete publication targets.
The inherited npm lockfile also reports one high-severity `undici` dependency
finding; this integration did not change it. There is no registry release record
in this checkout and no Cloud catalog update. No production rollback is needed
because no production state changed.
