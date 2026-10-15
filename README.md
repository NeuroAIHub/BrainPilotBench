<div align="center">

<h1><img src="https://brainpilot.chat/images/brainpilot-icon-light.png" alt="BrainPilot icon" height="42"/> BrainPilotBench</h1>

<p><strong>Evaluating AI agents on brain-science and behavioral research tasks.</strong></p>

<p>
Analyze data. Develop models. Submit code, predictions, and research reports.
</p>

<p>
  <strong>v1 task collection</strong> &nbsp;·&nbsp; <strong>112 runnable tasks</strong> &nbsp;·&nbsp; <strong>6 data categories</strong>
</p>

<p>
  <img src="https://img.shields.io/badge/v1_new_tasks-agent_results_pending-DFB317?style=flat-square" alt="v1 additions: agent results pending"/>
  <img src="https://img.shields.io/badge/Node.js-%E2%89%A522-339933?style=flat-square&logo=node.js&logoColor=white" alt="Node.js >= 22"/>
  <img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="MIT license"/>
  <a href="https://arxiv.org/abs/2607.15079"><img src="https://img.shields.io/badge/Paper-arXiv%3A2607.15079-B31B1B?style=flat-square" alt="BrainPilot technical report"/></a>
</p>

<p>
  <a href="#project-news">News</a> ·
  <a href="#task-suite">v1 Tasks</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#evaluation-status">Evaluation Status</a> ·
  <a href="#brainpilotbench-v0-results">v0 Results</a> ·
  <a href="https://brainpilot.chat/bench#leaderboard">v0 Leaderboard</a> ·
  <a href="#evaluate-your-agent">Evaluate Your Agent</a> ·
  <a href="#citation">Citation</a>
</p>

</div>

---

## Project news

- **2026-10-15 — BrainPilotBench v1 task collection.** v1 brings **108 new tasks and four retained v0 tasks** into one 112-task collection.
  **Invasive recordings** is a new data category with seven ECoG, sEEG, and intracortical decoding tasks.
  See the [v1 task suite](#task-suite) and [data access options](#v1-data-access). **Agent benchmark results for the 108 additions remain pending.**
- **2026-07-18** — BrainPilot was showcased at the “Intelligence in the Physical World” Science Forum at WAIC 2026. Follow us for the latest updates.
- **2026-07-17** — BrainPilotBench-v0 was released as open source. It provides four real brain-science tasks for agent-agnostic, artifact-based evaluation of the code, figures, models, and reports produced by scientific agents.

## Overview

BrainPilotBench is a benchmark and shared task collection for evaluating AI agents
on brain-science and behavioral research problems. Agents analyze data, develop
models, and submit code, predictions, or reports for task-specific evaluation.

The repository provides task instructions, data access, environments, and scoring
code. Independent research projects can reuse the same versioned tasks.

**BrainPilotBench v1** covers EEG, psychology, MRI, connectomics, calcium imaging, and invasive recordings in one task collection.
The v1 label identifies the collection. Each task keeps its own scientific protocol version, data bindings, and scoring interface.

## Evaluation status

> [!IMPORTANT]
> **v1 task collection: data access and evaluation workflows available. Agent benchmark results for the 108 additions are pending.**
>
> No BrainPilotBench agent benchmark scores are available for the 108 new v1 tasks, including the seven invasive-recording tasks.
> Current checks cover data integrity and selected preparation and reference-scoring workflows.
> They do not measure comparative agent performance across v1.
>
> Published **BrainPilotBench-v0 results cover only the four original tasks**. They remain historical v0 results, not a v1 evaluation.

The complete v1 source collection is under review in [PR #75](https://github.com/NeuroAIHub/BrainPilotBench/pull/75).
It is not yet merged into main or distributed through npm. Use the v1 source branch in the quick start below.

## Task suite

### BrainPilotBench v1 · 112 tasks

Each task defines a research objective, the data available to the agent,
the required outputs, and a task-specific metric.

| Data category | Total tasks | New in v1 | Research tasks |
|---|---:|---:|---|
| [EEG](tasks/eeg/README.md) | 25 | 23 | Motor imagery, evoked responses, sleep staging, and other scalp-EEG classification problems |
| [Psychology](tasks/psychology/README.md) | 76 | 76 | Behavioral models of participants' choices and responses |
| MRI | 2 | 1 | [Structural-MRI age prediction](tasks/mri/brain-age-mri/README.md) and [fMRI tonic-pain prediction](tasks/mri/tops-fmri/README.md) |
| [Connectomics](tasks/connectomics/celegans-structure-function-divergence/README.md) | 1 | 1 | Comparison of anatomical connectivity and measured signal propagation in C. elegans |
| [Calcium imaging](tasks/calcium-imaging/neuro-rsc-place-cell/README.md) | 1 | 0 | Place-cell analysis and decoding from calcium imaging and behavior |
| [Invasive recordings](#invasive-recordings) | 7 | 7 | Finger flexion, film conditions, motor output, handwriting, and birdsong from invasive neural recordings |
| **Total** | **112** | **108** | **Four v0 tasks are retained within the total.** |

**Explore a task:** [AlexMI motor imagery](tasks/eeg/eeg-mi-barachant2012/README.md)
· [Casino choice](tasks/psychology/psych101-lefebvre2017behavioural-exp1/README.md)
· [Category learning](tasks/psychology/psych101-badham2017deficits-exp1/README.md)
· [MRI age prediction](tasks/mri/brain-age-mri/README.md)
· [C. elegans network comparison](tasks/connectomics/celegans-structure-function-divergence/README.md)
· [Handwriting from neural activity](tasks/intracortical/falcon-h2-handwriting/README.md)

### Invasive recordings

This v1 data category contains seven tasks from real invasive recordings.
It combines [clinical ECoG and sEEG](tasks/ieeg/README.md) with [intracortical recordings](tasks/intracortical/README.md) in humans, macaques, and songbirds.
These recording types share one category while retaining their distinct input formats and scientific protocols.

| Task | Prediction target | Primary metric |
|---|---|---|
| [BCI IV-4](tasks/ieeg/ieeg-finger-flexion-bciciv4/README.md) | Five finger-flexion trajectories from human ECoG | Mean Pearson r across three participants and four scored fingers |
| [Film conditions](tasks/ieeg/ieeg-film-speech-music/README.md) | Speech or music in unseen film blocks from clinical ECoG/sEEG | Participant-macro, block-first balanced accuracy |
| [FALCON H1](tasks/intracortical/falcon-h1-reach-grasp/README.md) | Seven attempted arm/grasp velocity components | Date-mean variance-weighted R² |
| [FALCON H2](tasks/intracortical/falcon-h2-handwriting/README.md) | Attempted handwriting sentences | Date-mean word error rate |
| [FALCON M1-A](tasks/intracortical/falcon-m1-emg/README.md) | Sixteen upper-limb muscle activity channels | Date-mean variance-weighted R² |
| [FALCON M2](tasks/intracortical/falcon-m2-finger-velocity/README.md) | Two finger-group velocities | Date-mean variance-weighted R² |
| [FALCON B1](tasks/intracortical/falcon-b1-birdsong/README.md) | Zebra finch vocalization spectrograms | Normalized spectrogram MSE |

Their local checks cover real data, fixed reference submissions, container-isolated public Valid scoring,
and separate owner Test interfaces. They do not provide Agent benchmark results.
Five tasks have a [prepared public package](docs/invasive-task-preparation.md#download-a-prepared-public-package).
H1 and BCI IV-4 retain original-source download, split definitions, and local preparation methods. Their data are not mirrored here.
The film package does not require the owner-held shuffle key to use. Rebuilding the same opaque IDs and hashes does require it.
See the [invasive-recording guide](docs/invasive-task-preparation.md) for access and evaluation boundaries.

### Retained v0 protocols · 4 tasks

These four tasks are included in v1's 112-task total, not added on top of it.
They retain their IDs, scientific protocol versions, and historical v0 results.

| Task | Capability | Compute | Primary scoring |
|---|---|---|---|
| [<code>neuro-rsc-place-cell</code>](tasks/calcium-imaging/neuro-rsc-place-cell/README.md) | RSC calcium imaging, virtual-reality behavior, place-cell analysis, and decoding | CPU | Deterministic checks + human rubric |
| [<code>tops-fmri</code>](tasks/mri/tops-fmri/README.md) | Functional-connectivity modeling and held-out tonic-pain prediction | CPU | Study4 Pearson r + Study5 AUC |
| [<code>bciciv-2a</code>](tasks/eeg/bciciv-2a/README.md) | Four-class motor-imagery EEG decoding | GPU | Held-out accuracy + Cohen's kappa |
| [<code>sleep-edf</code>](tasks/eeg/sleep-edf/README.md) | Five-class sleep staging | GPU | Held-out Cohen's kappa + per-class recall |

The [machine-readable catalog](tasks/catalog.json) lists task IDs and availability.
`bp-bench list` shows runnable packages only.
See the [collection guide](docs/shared-task-collection.md) for protocol differences,
data roles, and reuse across independent research projects.

### v1 data access

Hosted packages for the v1 additions use two immutable storage snapshots:

- **EEG, psychology, structural MRI, and connectomics:** [101-task public package](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/09240a63ce2ec96050313c59221291114ff8df6f/bpb-public-data-20261013-v1), with 246 data files totaling 32.67 GB.
- **Invasive recordings:** [five-task public package](https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public/tree/a8a8adc87bab8d63253816dad0ae5c435e96a5f6/bpb-public-data-20261015-invasive-v1), with 402 data files totaling 2.35 GB.
- **H1 and BCI IV-4:** original-source download, fixed split definitions, and local preparation. Their data are not mirrored here.

Download only the tasks you need. The four retained v0 tasks keep their task-specific data access instructions.
EEG and psychology additions use public validation, not imported private Test scores. Evaluator-only inputs remain separate.

<details>
<summary>Data checks and candidates outside v1's runnable count</summary>

The 101-task package passed anonymous download and SHA-256 checks on all 247 paths, including its selection manifest.
The invasive package passed metadata checks on all 405 paths and anonymous download checks on nine representative files.
An additional complete M2 public-package download and workspace preparation passed.
These checks establish data delivery and selected workflows, not Agent benchmark performance.
See the [data preparation record](docs/data-preparation.md) and [invasive task guide](docs/invasive-task-preparation.md) for the exact scopes.

Four EEG entries remain preparation-only: HMC sleep stage, HMC sleep onset, Sleep-EDF onset, and CHB-MIT seizure detection.
Thielen2021 remains withheld. These five candidates are outside the 112 runnable tasks.
Candidate packages and evaluator-only inputs are not included in the public packages above.

</details>

<a id="reference-evaluation"></a>

## BrainPilotBench-v0 results

The [BrainPilot technical report](https://arxiv.org/abs/2607.15079) evaluates seven
harness–backbone configurations across all four BrainPilotBench-v0 tasks. BrainPilot
matched or approached the strongest evaluated configurations on multiple tasks, with
a performance–cost trade-off across backbones.

<p align="center">
  <img src="assets/readme/brainpilotbench-v0-results.png" alt="BrainPilotBench-v0 performance, cost, and resource-use comparison across four completed tasks" width="100%"/>
</p>

Except for the BrainPilot RSC result, which follows the report's stated selection of the
higher of two runs, all results are single runs. <code>F</code> denotes the absence of a
valid primary score and is distinct from <code>0.00</code>. These are reference runs from
the technical report.

<p align="center">
  <a href="https://brainpilot.chat/bench#leaderboard"><strong>Explore the BrainPilotBench-v0 evaluation →</strong></a>
</p>

## Quick start

### Requirements

- [Node.js](https://nodejs.org/) 22 or newer
- npm
- Git
- Any task-specific Python, CPU, GPU, or storage requirements listed in its task README

Until [PR #75](https://github.com/NeuroAIHub/BrainPilotBench/pull/75) is merged, use the v1 source branch:

~~~bash
git clone --branch feat/invasive-task-collection https://github.com/NeuroAIHub/BrainPilotBench.git
cd BrainPilotBench
npm ci
npm run build
npm link
~~~

Run the zero-key example:

~~~bash
bp-bench submit verify examples/submission
bp-bench score examples/submission
bp-bench leaderboard examples
~~~

List the current tasks:

~~~bash
bp-bench list
~~~

Before starting a full task, read its linked README and run:

~~~bash
bp-bench doctor tops-fmri
bp-bench fetch tops-fmri --public
~~~

## How it works

~~~mermaid
flowchart LR
    A["Task specification"] --> B["Agent or harness"]
    B --> C["Submission bundle"]
    C --> D["Contract verification"]
    D --> E["Task-declared scorer"]
    E --> F["Scores and coverage"]
~~~

1. A task defines the research goal, inputs, prompts, and required artifacts.
2. An agent works in its native environment and produces a submission bundle.
3. BrainPilotBench verifies that the bundle satisfies the task contract.
4. The task-declared grader evaluates the submitted artifacts.
5. Scores retain coverage and run-state information so missing measurements are not
   silently converted to zero.

## Evaluate your agent

BrainPilotBench provides three adapters:

| Adapter | Use case |
|---|---|
| <code>brainpilot</code> | A running BrainPilot deployment |
| <code>command</code> | A local agent command |
| <code>manual</code> | Any other harness using a prepared workspace and resume step |

For an agent-independent manual handoff:

~~~bash
bp-bench run <task-id> --adapter manual --agent my-agent@1
~~~

Run your agent in the printed workspace, then execute the printed resume command. Verify
and score the resulting bundle:

~~~bash
bp-bench submit verify "runs/<run-id>"
bp-bench score "runs/<run-id>"
~~~

To run against BrainPilot:

~~~bash
bp-bench run <task-id> \
  --adapter brainpilot \
  --base-url http://127.0.0.1:9001 \
  --workspace-root /absolute/path/to/workspaces \
  --agent brainpilot@<commit>
~~~

The built-in adapters all produce the same submission-bundle contract. This keeps task
scoring independent of the agent language, model provider, and orchestration framework.

## Scoring and integrity

- Each task declares its required artifacts and grader.
- Deterministic metrics, held-out evaluation, and expert rubrics are used where appropriate.
- A valid score of <code>0.00</code>, an unscored run, and a metric that does not apply are
  represented as different states.
- Public inputs are pinned by content hash; evaluator-only inputs remain outside the agent
  workspace.
- Official results are produced from preserved artifacts and run metadata rather than
  accepted as self-reported numbers.

Maintainers with gated evaluator access follow the task-specific instructions; for example,
<code>bp-bench fetch tops-fmri --private</code>. Private inputs are never staged in the agent
workspace.

## Documentation and contributing

- Start with the [task-specific READMEs](#task-suite) for setup and evaluation instructions.
- See [CONTRIBUTING.md](CONTRIBUTING.md) to propose tasks or contribute framework changes.
- See [SECURITY.md](SECURITY.md) to report a vulnerability.
- Open a [Task Proposal](https://github.com/NeuroAIHub/BrainPilotBench/issues/new?template=task-proposal.yml)
  for a new brain science workflow.

BrainPilotBench is a curated benchmark. Maintainers review scientific construct validity,
data provenance, scoring design, and contamination risk before adding a task.

## Citation

If BrainPilotBench has helped your work, we welcome you to cite our work!

If you use BrainPilotBench-v0 or its reference evaluation, cite the technical report:

~~~bibtex
@misc{li2026brainpilotautomatingbraindiscovery,
  title={BrainPilot: Automating Brain Discovery with Agentic Research},
  author={Haoxuan Li and Tianci Gao and Jianhe Li and Yang Fan and Runze Shi
    and Weiran Wang and Tianxiang Zhao and Zezhao Wu and Xiaoyang Jiang
    and Qihui Zhang and Jia Li and Xiao Xiao and Kai Du and Xiaoxuan Jia
    and Chao Xie and Lu Mi},
  year={2026},
  eprint={2607.15079},
  archivePrefix={arXiv},
  primaryClass={cs.AI},
  url={https://arxiv.org/abs/2607.15079}
}
~~~

For v1 tasks, also cite the source datasets listed in each task README.
For reproducibility, report the repository commit, task IDs and scientific protocol versions, and the
evaluated harness–model configuration.

## Community

Questions, ideas, or just want to say hi? Join the BrainPilot community:

- 💬 **[Join the BrainPilot Slack →](https://join.slack.com/t/brainpilot/shared_invite/zt-43pbjtuz5-AiuRez0RIYkzhIsmDQtv8A)**
- 🪶 **[Join the BrainPilot Feishu group →](https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=0far82db-f790-412e-9217-58ae67df4313)**
- 📧 **Contact:** [thu_neuroai@mail.tsinghua.edu.cn](mailto:thu_neuroai@mail.tsinghua.edu.cn)

You can also [open an issue](https://github.com/NeuroAIHub/BrainPilot/issues/new/choose)
or start a discussion.

## License

The framework package is licensed under MIT.

---

<div align="center">

**Build, evaluate, and share agents for brain and behavioral research.**

</div>
