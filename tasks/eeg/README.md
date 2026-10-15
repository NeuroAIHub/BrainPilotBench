# EEG tasks

Agents develop classifiers for motor imagery, evoked responses, sleep stages,
and other EEG conditions. Each task defines its own input representation, data
split, and scoring profile.

The EEG category in BrainPilotBench v1 includes 23 new public-validation tasks and the two retained
BrainPilotBench-v0 EEG tasks. The v1 additions cover 21 imported AgentEEGBench
protocols, a native BCI-IV-2a protocol, and full Sleep-EDF sleep staging.

> [!NOTE]
> **Agent benchmark results for the 23 v1 additions: not yet available.**
>
> Public data and evaluation code are available. Reference implementation checks are separate from agent results.
> The two original EEG tasks retain their published v0 results and distinct protocols.

| EEG collection status | Count | Boundary |
| --- | ---: | --- |
| v1 additions | 23 | Public train and validation only. No imported private Test score. |
| Retained v0 tasks | 2 | Included in v1, with their own data and scoring protocols. |
| Preparation candidates | 4 | Not registered as runnable tasks. |
| Withheld candidate | 1 | Not activated in this collection. |

## Browse the v1 additions

**Motor imagery**

- [AlexMI / Barachant2012](eeg-mi-barachant2012/README.md) — trigger-index split with non-overlapping same-timeline windows.
- [BCI-IV-2a native subject-grouped](eeg-mi-bnci2014/README.md) — different from the legacy session T/E task.
- [Cho2017](eeg-mi-cho2017/README.md), [EEGMMIDB](eeg-mi-eegmmidb/README.md), and [OpenBMI MI](eeg-mi-openbmi2019/README.md) — subject-disjoint splits.
- [Zhou2016](eeg-mi-zhou2016/README.md) — session-disjoint split.

**Event-related EEG and P3**

- [ERN](eeg-erp-ern/README.md), [LRP](eeg-erp-lrp/README.md), [MMN](eeg-erp-mmn/README.md), and [N170](eeg-erp-n170/README.md).
- [N2pc](eeg-erp-n2pc/README.md), [N400](eeg-erp-n400/README.md), [Kappenman2021 P3](eeg-erp-p3/README.md), and [OpenBMI P3](eeg-p3-openbmi2019/README.md).

**Other paradigms**

- [Thielen2015 cVEP](eeg-cvep-thielen2015/README.md).
- [High-Gamma motor execution](eeg-me-highgamma2017/README.md) and [Ofner2017 motor execution](eeg-me-ofner2017/README.md).
- [Zyma2019 mental arithmetic](eeg-mental-arithmetic-zyma2019/README.md).
- [OpenBMI SSVEP](eeg-ssvep-openbmi2019/README.md) and [Wang2017 SSVEP](eeg-ssvep-wang2017/README.md).
- [SpanishBCBL EEG typing](eeg-typing-spanishbcbl/README.md) — sparse-macro scoring with sentence-cluster separation.
- [DICE EEG classification](eeg-dementia-dice/README.md).
- [Sleep-EDF cassette sleep staging](eeg-sleep-stage-sleepedf/README.md) — a new BrainPilotBench source spec.

The shared scorer serves 22 new tasks: 21 use complete-class balanced accuracy, and SpanishBCBL typing uses sparse-macro balanced accuracy. The native BCI-IV-2a task uses its own scorer.

## Run one public task

From the repository root, choose a task ID from its page:

```sh
node dist/cli.js fetch <task-id> --public
node dist/cli.js prepare <task-id> --workspace /absolute/new-workspace
```

Each task page gives its input shape, split, class count, metric, submission files, and source version. The [shared EEG guide](_shared/README.md) explains the isolated inference path. The public download does not include private Test data or labels.

## Other EEG entries

The legacy [BCI-IV-2a](bciciv-2a/README.md) and [Sleep-EDF](sleep-edf/README.md) tasks keep their original protocols. Do not combine their results with the new native BCI-IV-2a or Sleep-EDF stage tasks.

Four candidates remain preparation-only: [HMC sleep staging](eeg-sleep-stage-hmc/README.md), [Sleep-EDF sleep onset](eeg-sleep-onset-sleepedf/README.md), [HMC sleep onset](eeg-sleep-onset-hmc/README.md), and [CHB-MIT seizure](eeg-seizure-chbmit/README.md). The [Thielen2021 cVEP candidate](eeg-cvep-thielen2021/candidate.json) remains withheld. None of these five entries has a runnable `task.yaml` in this collection.
