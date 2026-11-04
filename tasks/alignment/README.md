# Alignment analysis

Task one evaluates whether an Agent performs the specified analysis correctly and
reproducibly. A fixed representation's high brain score is not the Agent metric.

- [Pereira2018 candidate](alignment-pereira2018-analysis/README.md): offline scaffold;
  real server execution/equivalence validated separately; canonical promotion and
  scientific/Agent acceptance pending; not in the runnable collection.
- [Synthetic workflow example](../_example/alignment-synthetic/README.md): generated
  data, actual calculations, parent-owned scoring and local end-to-end checks.

The real integration now has a [Linux server runbook](SERVER_RUNBOOK.md), explicit
environment/bootstrap files under `_env/`, and a lazy server backend under
`_shared/real_brainscore/`. It covers model revision resolution, real cache
preparation, official fixed-layer scoring/tracing, a Docker submission comparator,
and a separately split Task2 profile. `server.py stage-task1/stage-task2` can create
experimental task roots outside Git for server testing. Canonical promotion is
still blocked pending acceptance.

The [2026-11-02 Linux validation record](SERVER_VALIDATION.md) covers actual
Pereira384 data and distilgpt2 inference, official score/trace equivalence and
the derived Task2 MCP workflow. It also records compatibility fixes found during
execution. Llama validation, scientific acceptance and actual Agent runs remain
separate requirements; canonical promotion is still pending.

Task A now has an [incremental-prediction contract](INCREMENTAL_CONTRACT.md),
[preparation/scoring runbook](EXPANSION_RUNBOOK.md) and
[real-data validation record](EXPANSION_VALIDATION.md). It reuses the verified
Pereira384/distilgpt2 cache, offers three declared control sets and checks nested
story-CV predictions in Docker. `incremental_cli.py stage` generates an explicit
experimental task outside Git; canonical counts are unchanged.

All six expansion tasks now have executable experimental implementations, real
input preparation, explicit task staging, submission replay and grading. The
implementation order was A → B → F → E → C → D. B–F use `expansion_cli.py` and
the [B–F contract](EXPANSION_CONTRACT.md); A retains `incremental_cli.py`.

| Task | Implemented first profile | Agent metric |
|---|---|---|
| A | Pereira incremental prediction beyond declared controls | Analysis correctness |
| B | Token-matched short-context conditions on the same 160 targets | Analysis correctness |
| F | 988 training sentences; select 10+10 from 500 hidden-response candidates | Actual held-out response difference |
| E | Real human schedules and derived feedback-once/replay100 linear baselines | Analysis and experience-audit correctness |
| C | THINGS IT/behavior; concept-label representation comparison | Analysis correctness |
| D | THINGS-EEG2 full curves, disjoint subject/concept confirmation, permutation correction | Analysis correctness |

C/D compare frozen language representations of concept names, not image-derived
vision models. C's confirmation behavior sample is small; D uses EEG rather than
the original MEG proposal. E's baselines are explicitly derived simulations, not
an exact replication of the paper. See the contract and validation record for
these scientific scope limits. All real reference submissions passed Docker and
the CLI lifecycle; deliberate errors were rejected. These are maintainer script
results, not independent Agent results. Canonical promotion and scientific review
remain pending. Llama downloading remains deferred.
