# Model human behavior across 76 Psych-101 tasks

These 76 task interfaces cover published experiment IDs in the psychology category of [BrainPilotBench v1](../../README.md#task-suite). An ID identifies a source experiment. The IDs do not represent 76 independent papers.

The scientific question is whether an Agent model can predict human responses from the trial history available before each response. The target is the participant's recorded action or answer, not an ideal solution. The tasks span reward choices, classification, memory, navigation, estimation, and response control.

Each task has public participant-level train and validation splits. The interface asks an Agent to fit a model on public train data and predict marked validation responses. The public metric is `mean_response_nll` (lower is better), measured in nats per marked response. It measures probability assigned to the recorded response, not task reward or accuracy. Scores from the two response protocols have different metric versions and should be read within their protocol.

> [!NOTE]
> **Agent benchmark results: not yet available.**
> Runnable tasks and published public data do not establish an accepted Agent benchmark result.

## Run a public task

Choose a task ID from the catalog below. From the repository root, fetch its pinned public splits and prepare a new workspace:

```sh
node dist/cli.js fetch <task-id> --public
node dist/cli.js prepare <task-id> --workspace /absolute/new-workspace
```

Each task's `data.lock` points to `BrainPilot-Bench/Tasks-Data-Public` at revision `f50618208e3e748a8a16dfb6138e335f033d603c`, under `tasks/psychology/<task-id>/public/`. It pins `train.jsonl` and `valid.jsonl` by size and SHA-256. The fetch and preparation steps check those files. Preparation uses the fetched splits; it does not rebuild the original source file.

If a verified experiment package already contains both split files, set `BPB_PSYCH101_PUBLIC_TASK_DIR` to that task directory. The setup helper checks both hashes. Each task README describes its model bundle and submission contract.

### Run public scoring

Build the standalone inference image on a new host. Score a completed submission with the immutable image ID, which can differ by CPU architecture:

```sh
docker build -f tasks/psychology/env/Dockerfile -t bpb-psych101-inference:local tasks/psychology/env
IMAGE_ID="$(docker image inspect bpb-psych101-inference:local --format '{{.Id}}')"
bp-bench score <submission-bundle> --isolation docker --inference-image "$IMAGE_ID"
```

This scores public validation only. The scorer checks the split hashes before model code runs. The host controller emits the BPB score sentinel.

## Two response protocols

- **Displayed-key categorical (22 tasks):** The model assigns probabilities to the keys displayed at each response. The scorer calculates negative log likelihood for the recorded key.
- **Exact-byte `byte_next_v1` (54 tasks):** The model predicts each byte of a marked response from 256 possible byte values, plus an end-of-sequence (EOS) symbol. The scorer sums byte and EOS losses for each response before averaging across responses. This is a byte-based metric, not a model-token metric.

Both protocols use causal trial history. Earlier responses and feedback can appear in the prefix; the current target response and future feedback do not. The [marked-response policy](#marked-response-policy) defines which source spans receive scores.

## Explore the tasks

The groups below describe the actions in each experiment's public instructions. They are navigation aids, not claims about cognitive mechanisms.

<details>
<summary>Reward and choice (38)</summary>

- [Predicting Human Choices Among Four Rewards](psych101-bahrami2020four-exp/README.md) · `psych101-bahrami2020four-exp`
- [Predicting Human Choices Between Changing Slot Machines](psych101-feng2021dynamics-exp1/README.md) · `psych101-feng2021dynamics-exp1`
- [Modeling Human Stop-or-Continue Card Choices](psych101-frey2017cct-exp1/README.md) · `psych101-frey2017cct-exp1`
- [Predicting Human Balloon Pumping and Stopping](psych101-frey2017risk-exp1/README.md) · `psych101-frey2017risk-exp1`
- [Modeling Human Reward Choices and Odds Estimates — Experiment 1](psych101-garcia2023experiential-exp1/README.md) · `psych101-garcia2023experiential-exp1`
- [Modeling Human Reward Choices and Odds Estimates — Experiment 2](psych101-garcia2023experiential-exp2/README.md) · `psych101-garcia2023experiential-exp2`
- [Modeling Human Reward Choices and Odds Estimates — Experiment 3](psych101-garcia2023experiential-exp3/README.md) · `psych101-garcia2023experiential-exp3`
- [Modeling Human Reward Choices and Odds Estimates — Experiment 4](psych101-garcia2023experiential-exp4/README.md) · `psych101-garcia2023experiential-exp4`
- [Human Choices Against a Fixed-Zero Slot Machine](psych101-gershman2018deconstructing-exp1/README.md) · `psych101-gershman2018deconstructing-exp1`
- [Human Choices Between Unequal Slot Machines](psych101-gershman2018deconstructing-exp2/README.md) · `psych101-gershman2018deconstructing-exp2`
- [Human Choices Among Six Gambles](psych101-krueger2022identifying-exp1/README.md) · `psych101-krueger2022identifying-exp1`
- [Modeling Human Choice in a Casino Task](psych101-lefebvre2017behavioural-exp1/README.md) · `psych101-lefebvre2017behavioural-exp1`
- [Modeling Human Casino Choices with Gains and Losses](psych101-lefebvre2017behavioural-exp2/README.md) · `psych101-lefebvre2017behavioural-exp2`
- [Modeling Human Fruit-Market Navigation and Feeding — Experiment 0](psych101-ludwig2023human-exp0/README.md) · `psych101-ludwig2023human-exp0`
- [Modeling Human Fruit-Market Navigation and Feeding — Experiment 1](psych101-ludwig2023human-exp1/README.md) · `psych101-ludwig2023human-exp1`
- [Modeling Human Fruit-Market Navigation and Feeding — Experiment 2](psych101-ludwig2023human-exp2/README.md) · `psych101-ludwig2023human-exp2`
- [Human Gamble Choices under Varying Feedback](psych101-peterson2021using-exp1/README.md) · `psych101-peterson2021using-exp1`
- [Human Gamble Choices before and after Feedback](psych101-plonsky2018when-exp1/README.md) · `psych101-plonsky2018when-exp1`
- [Human Slot-Machine Choices Across Games](psych101-sadeghiyeh2020temporal-exp1/README.md) · `psych101-sadeghiyeh2020temporal-exp1`
- [Modeling Human Search Among Eight Reward Options — Experiment 1](psych101-schulz2020finding-exp1/README.md) · `psych101-schulz2020finding-exp1`
- [Modeling Human Search Among Eight Reward Options — Experiment 2](psych101-schulz2020finding-exp2/README.md) · `psych101-schulz2020finding-exp2`
- [Modeling Human Search Among Eight Reward Options — Experiment 3](psych101-schulz2020finding-exp3/README.md) · `psych101-schulz2020finding-exp3`
- [Modeling Human Search Among Eight Reward Options — Experiment 4](psych101-schulz2020finding-exp4/README.md) · `psych101-schulz2020finding-exp4`
- [Modeling Human Search Among Eight Reward Options — Experiment 5](psych101-schulz2020finding-exp5/README.md) · `psych101-schulz2020finding-exp5`
- [Human Exploration of Two Slot Machines](psych101-somerville2017charting-exp1/README.md) · `psych101-somerville2017charting-exp1`
- [Human Choices from Four Card Decks — Experiment 1](psych101-steingroever2015data-exp1/README.md) · `psych101-steingroever2015data-exp1`
- [Human Choices from Four Card Decks — Experiment 2](psych101-steingroever2015data-exp2/README.md) · `psych101-steingroever2015data-exp2`
- [Human Choices from Four Card Decks — Experiment 3](psych101-steingroever2015data-exp3/README.md) · `psych101-steingroever2015data-exp3`
- [Human Slot-Machine Choices Across Games](psych101-waltz2020differential-exp1/README.md) · `psych101-waltz2020differential-exp1`
- [Human Two-Slot-Machine Choices — Experiment 1](psych101-wilson2014humans-exp1/README.md) · `psych101-wilson2014humans-exp1`
- [Human Two-Slot-Machine Choices — Experiment 2](psych101-wilson2014humans-exp2/README.md) · `psych101-wilson2014humans-exp2`
- [Human Two-Slot-Machine Choices — Experiment 3](psych101-wilson2014humans-exp3/README.md) · `psych101-wilson2014humans-exp3`
- [Human Two-Slot-Machine Choices — Experiment 4](psych101-wilson2014humans-exp4/README.md) · `psych101-wilson2014humans-exp4`
- [Human Two-Slot-Machine Choices — Experiment 5](psych101-wilson2014humans-exp5/README.md) · `psych101-wilson2014humans-exp5`
- [Predicting Human Reward Search Along a Number Line](psych101-wu2018generalisation-exp1/README.md) · `psych101-wu2018generalisation-exp1`
- [Human Choices Between Described Monetary Lotteries](psych101-wulff2018description-exp1/README.md) · `psych101-wulff2018description-exp1`
- [Predicting Human Lottery Sampling and Final Choice](psych101-wulff2018sampling-exp1/README.md) · `psych101-wulff2018sampling-exp1`
- [Human Choices with Changing Slot-Machine Rewards](psych101-xiong2023neural-exp1/README.md) · `psych101-xiong2023neural-exp1`

</details>

<details>
<summary>Learning and classification (6)</summary>

- [Modeling Human Category Learning from Feedback](psych101-badham2017deficits-exp1/README.md) · `psych101-badham2017deficits-exp1`
- [Modeling Human Tree-Category Learning Across Gardens](psych101-flesch2018comparing-exp1/README.md) · `psych101-flesch2018comparing-exp1`
- [Human Stimulus–Response Learning from Rewards](psych101-gershman2020reward-exp1/README.md) · `psych101-gershman2020reward-exp1`
- [Human Object Classification and Typicality Ratings — Experiment 1](psych101-levering2020revisiting-exp1/README.md) · `psych101-levering2020revisiting-exp1`
- [Human Object Classification and Typicality Ratings — Experiment 2](psych101-levering2020revisiting-exp2/README.md) · `psych101-levering2020revisiting-exp2`
- [Predicting Human Weather Judgments from Tarot Cards](psych101-speekenbrink2008learning-exp1/README.md) · `psych101-speekenbrink2008learning-exp1`

</details>

<details>
<summary>Memory and attention (7)</summary>

- [Modeling Human Recognition of Studied Word Pairs](psych101-cox2017information-exp1/README.md) · `psych101-cox2017information-exp1`
- [Predicting Human N-Back Letter Responses](psych101-enkavi2019adaptivenback-exp1/README.md) · `psych101-enkavi2019adaptivenback-exp1`
- [Modeling Human Digit-Sequence Recall](psych101-enkavi2019digitspan-exp1/README.md) · `psych101-enkavi2019digitspan-exp1`
- [Modeling Human Recognition of Recent Letters](psych101-enkavi2019recentprobes-exp1/README.md) · `psych101-enkavi2019recentprobes-exp1`
- [Predicting Human Word Study and Recall — Experiment 1](psych101-popov2023intent-exp1/README.md) · `psych101-popov2023intent-exp1`
- [Predicting Human Word-Pair Study and Recall](psych101-popov2023intent-exp2/README.md) · `psych101-popov2023intent-exp2`
- [Predicting Human Word Study and Recall — Experiment 3](psych101-popov2023intent-exp3/README.md) · `psych101-popov2023intent-exp3`

</details>

<details>
<summary>Navigation and sequential search (12)</summary>

- [Predicting Human Spaceship Choices amid Treasure and Antimatter](psych101-kool2016when-exp1/README.md) · `psych101-kool2016when-exp1`
- [Predicting Human Spaceship and Alien Choices for Treasure](psych101-kool2016when-exp2/README.md) · `psych101-kool2016when-exp2`
- [Modeling Human Spaceship Choices with Treasure Multipliers](psych101-kool2017cost-exp1/README.md) · `psych101-kool2017cost-exp1`
- [Modeling Human Spaceship and Alien Choices with Multipliers](psych101-kool2017cost-exp2/README.md) · `psych101-kool2017cost-exp2`
- [Modeling Human Choices on a Hidden Binary Grid](psych101-kumar2023disentangling-exp1/README.md) · `psych101-kumar2023disentangling-exp1`
- [Predicting Human Subway Navigation — Experiment 2](psych101-tomov2020discovery-exp2/README.md) · `psych101-tomov2020discovery-exp2`
- [Predicting Human Subway Navigation — Experiment 4](psych101-tomov2020discovery-exp4/README.md) · `psych101-tomov2020discovery-exp4`
- [Predicting Human Subway Navigation — Experiment 5](psych101-tomov2020discovery-exp5/README.md) · `psych101-tomov2020discovery-exp5`
- [Predicting Human Subway Navigation — Experiment 7](psych101-tomov2020discovery-exp7/README.md) · `psych101-tomov2020discovery-exp7`
- [Modeling Human Castle-Room Exploration — Experiment 1](psych101-tomov2021multitask-exp1/README.md) · `psych101-tomov2021multitask-exp1`
- [Modeling Human Castle-Room Exploration — Experiment 3](psych101-tomov2021multitask-exp3/README.md) · `psych101-tomov2021multitask-exp3`
- [Predicting Human Rocket and Alien Choices for Treasure](psych101-zorowitz2023data-exp1/README.md) · `psych101-zorowitz2023data-exp1`

</details>

<details>
<summary>Judgment and estimation (10)</summary>

- [Human Hormone-Level Estimates from Verbal Cues](psych101-collsioo2023mcpl-exp1-775cd1984f/README.md) · `psych101-collsioo2023mcpl-exp1-775cd1984f`
- [Human Hormone-Level Estimates from Numeric Cues](psych101-collsioo2023mcpl-exp2-6bd18ff5bf/README.md) · `psych101-collsioo2023mcpl-exp2-6bd18ff5bf`
- [Human Hormone-Level Estimates from Two Cues](psych101-collsioo2023mcpl-exp3-c372064286/README.md) · `psych101-collsioo2023mcpl-exp3-c372064286`
- [Predicting Human Odd-One-Out Judgments](psych101-hebart2023things-exp1/README.md) · `psych101-hebart2023things-exp1`
- [Human Product Choices from Expert Ratings](psych101-hilbig2014generalized-exp1/README.md) · `psych101-hilbig2014generalized-exp1`
- [Modeling Human Grammar Quiz Self-Estimates](psych101-jansen2021dunningkruger-exp1/README.md) · `psych101-jansen2021dunningkruger-exp1`
- [Human Preferences for Immediate and Delayed Payments](psych101-ruggeri2022globalizability-exp1/README.md) · `psych101-ruggeri2022globalizability-exp1`
- [Modeling Human Shock-Probability Estimates from Visual Cues](psych101-wise2019acomputational-exp1/README.md) · `psych101-wise2019acomputational-exp1`
- [Modeling Human Weather-Probability Estimates — Experiment 1](psych101-zhu2020bayesian-exp1/README.md) · `psych101-zhu2020bayesian-exp1`
- [Modeling Human Conditional Weather-Probability Estimates](psych101-zhu2020bayesian-exp2/README.md) · `psych101-zhu2020bayesian-exp2`

</details>

<details>
<summary>Stimulus and response (3)</summary>

- [Predicting Human Go/No-Go Keypresses](psych101-enkavi2019gonogo-exp1/README.md) · `psych101-enkavi2019gonogo-exp1`
- [Modeling Human Responses to Keypress Instructions — Experiment 1](psych101-wu2023chunking-exp1/README.md) · `psych101-wu2023chunking-exp1`
- [Modeling Human Responses to Keypress Instructions — Experiment 2](psych101-wu2023chunking-exp2/README.md) · `psych101-wu2023chunking-exp2`

</details>

## Protocols and boundaries

### Public data and source provenance

The setup helper also checks participant groups and response counts. Normal preparation reads the pinned splits and does not download the original 859,179,475-byte source file. The gated official Test is absent from this collection. Historical research, controller, monitoring, frozen models, and private Test remain in the original Psych101-Agent-Bench project. Prior Test results do not establish BrainPilotBench acceptance.

The original public source is `marcelbinz/Psych-101` revision `611565c66395e2787cd7e3305149bb75dc138024`. The associated paper DOI is `10.1038/s41586-025-09215-4`. The pinned source manifest records Apache-2.0 for the public file. The official Test has a separate redistribution restriction.

The public validation scorer is scoped to each task. It does not use the historical private Test evaluator. The shared task helpers use only the Python 3.11–3.13 standard library.

### Isolated inference and scoring

`checks/check.sh` invokes `_shared/score_isolated.py`. The trusted controller retains the current target answer while a pinned Docker worker receives one causal prefix per query. The worker receives only the nine required model files as its data mount. It has no network, host cache, Test mount, or credentials. It runs under a non-root UID with a read-only root filesystem, 2 CPU cores, 4 GiB memory, a small process limit, and finite scoring deadlines. `env/Dockerfile` pins SciPy and scikit-learn for inference. The tested arm64 image digest is recorded in the controller. These controls define a bounded container boundary; they do not prove formal isolation or compatibility with arbitrary historical frozen models. `BPB_OFFICIAL_SCORING=1` is rejected because these tasks have no authorized private-Test scoring path.

### Marked-response policy

The `byte_next_v1` scorer teacher-forces only prior bytes of the current marked response. It never passes the next target byte or whole answer to the model. It scores only literal `<<...>>` source spans. Unmarked omissions such as Go/NoGo `press nothing` remain context, not additional targets. Raw numeric spellings remain unchanged, including Wu2018 `0` answers that conflict with its 1–30 instruction. This *marked-response* policy does not cover every scientific behavior in every source experiment.

<details>
<summary>Protocol audit and source-file hashes</summary>

All 76 published experiment IDs have individual public-validation task packages. Twenty-two use audited closed categorical response profiles: the original 12 and ten same-family variants. The ten variants have 283,625 public train/valid marked responses, with zero mismatches against the existing profiles. The other 54 use the separately versioned `byte_next_v1` interface. `metadata-only.json` records every published ID. It does not claim scientific acceptance or Agent runs for all tasks.

The original `prompts_training.jsonl` has SHA-256 `7a370a94084acd6f73f20d6559214683cfadcab8a1f69e369df285ba75ccef01`. The shared helpers `_shared/contract.py` and `_shared/responses.py` are byte-identical copies from Psych101-Agent-Bench. Their SHA-256 values are `de9ff85319bde7a20b2f12e26a57ac28ca1f7d7d589d7f4a901e93f901f72cc3` and `584cdecc0bb9f985b7a9a3b3039abd3690ccae165b1ad589ec91ed3a16aa7b52`, respectively.

</details>

## Public-only publication packet preparation

<details>
<summary>Historical packet staging and verification</summary>

`public-source-index.json` pins 76 task IDs and 152 public train/valid files. It includes the public source revision and hashes. It excludes official Test counts, labels, controller records, and prior scores. `_shared/stage_public_packet.py` audits each source `spec.json`, file size, SHA-256, experiment ID, response count, and participant split. A public-only packet candidate was staged and independently verified on 2026-10-12. Its 152 split files total 859,179,475 bytes. Those files were published at commit `09240a63ce2ec96050313c59221291114ff8df6f` in `BrainPilot-Bench/Tasks-Data-Public`, under the historical 101-task namespace `bpb-public-data-20261013-v1`. Current task locks use the `tasks/psychology/<task-id>/public/` route at revision `f50618208e3e748a8a16dfb6138e335f033d603c` described above. The packet manifest and frozen selection manifest retain their original candidate statuses. Those statuses describe preparation at the time, not the later Hub publication. Data publication does not imply scientific task acceptance.

```sh
python3 tasks/psychology/_shared/stage_public_packet.py --plan
python3 tasks/psychology/_shared/stage_public_packet.py --audit-source \
  --source-root /data/psych101/published-20261002-v1
# Use a new, owner-only destination after approval:
python3 tasks/psychology/_shared/stage_public_packet.py --stage \
  --source-root /data/psych101/published-20261002-v1 \
  --destination /data/private/brainpilotbench/psych101-public-packet-v1
python3 tasks/psychology/_shared/stage_public_packet.py --verify \
  --destination /data/private/brainpilotbench/psych101-public-packet-v1
```

The packet contains `public-tasks/<bpb-task-id>/{train,valid}.jsonl` and one `MANIFEST.json`. Set `BPB_PSYCH101_PUBLIC_TASK_DIR` to a task directory in the packet. The stage tool copies each file and checks its hash. It creates the destination exclusively and does not overwrite an existing path. If staging fails after creation, the partial directory remains unverified. Inspect that directory and select a new path for any retry.

New manifests use schema `/2` and status `public_packet_candidate_not_published_or_scored`. This status describes the selected files, not a completed verification. A successful `--verify` checks every file and reports `public_packet_candidate_verified_not_published_or_scored`. The verifier also accepts the exact legacy `/1` manifest after the same checks. Staging does not upload data, run Agent research, or grant official Test access. On another host, transfer only the index, stage tool, and adjacent `responses.py` helper into a private working directory. Check their hashes before use.

</details>
