# Alignment analysis

Task one evaluates whether an Agent performs the specified analysis correctly and
reproducibly. A fixed representation's high brain score is not the Agent metric.

- [Pereira2018 candidate](alignment-pereira2018-analysis/README.md): offline scaffold;
  real inputs, official backend and equivalence acceptance pending; not runnable.
- [Synthetic workflow example](../_example/alignment-synthetic/README.md): generated
  data, actual calculations, parent-owned scoring and local end-to-end checks.

The real integration now has a [Linux server runbook](SERVER_RUNBOOK.md), explicit
environment/bootstrap files under `_env/`, and a lazy server backend under
`_shared/real_brainscore/`. It covers model revision resolution, real cache
preparation, official fixed-layer scoring/tracing, a Docker submission comparator,
and a separately split Task2 profile. `server.py stage-task1/stage-task2` can create
experimental task roots outside Git for server testing. Canonical promotion is
still blocked pending acceptance.

No real-data execution or formal Agent results are added by this work. The
2026-11-02 server implementation has only static checks; dependencies, data,
numerics, containers and actual Agent runs remain to be tested on the server.
