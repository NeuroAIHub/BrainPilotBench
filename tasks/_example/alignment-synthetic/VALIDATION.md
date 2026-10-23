# Offline validation record — 2026-10-23

Scope: P0/P1 offline scaffolding and synthetic P3–P5 workflow checks only.
This is an engineering record, not a scientific acceptance or Agent benchmark result.

Environment actually used: local Python 3.12.14, NumPy 2.3.5, Node 24.14.1.
No packages were installed. The system Python lacks NumPy; an existing bundled
Python was selected with `BPB_ALIGNMENT_PYTHON`. Existing Node dependencies were reused.

| Check | Observed result |
|---|---|
| `npm run build` | Passed |
| `npm run test:alignment` | 34 Python checks: 33 passed, 1 Docker integration check skipped; real CLI lifecycle passed |
| Correct synthetic reference | Saved outputs and reruns agree with augmented-least-squares oracle; `analysis_success=1` |
| Negative submissions | Wrong stimulus pairing, wrong aggregation, training scoring, test-Y leakage, canned public results, corrupt/missing runtime output, source mutation and stdout score spoofing rejected with zero |
| Submission contract | Missing artifacts/wrong version rejected; empty NOP emits no score |
| Invariance/reproducibility | Repeated calculation, byte-identical fixture regeneration, input/output permutations and fold-0 test-Y prediction invariance passed |
| Low model score | Noise-response fixture passes correctness despite low raw alignment |
| Infrastructure separation | Damaged inputs/reference, missing image and worker staging failures produce no score; worker timeout produces analysis failure |
| Docker contract (mock/static) | Mount allowlist, no-network/read-only/resource flags, timeout cleanup checked; no reference mount |
| CLI | prepare (including repeat) → manual run → analyze → resume/artifact collection → verify → score → leaderboard, schema and example Oracle/NOP gates passed |
| `npm test` | 226 existing checks: 223 passed, 3 skipped; no failures |
| Collection/catalog | Passed: 118 entries, 112 runnable, 6 candidates; Alignment real task remains a candidate |
| `validate all --schema-only` | Passed, including the synthetic example |
| `npm run test:docs` | Passed |
| `npm run test:invasive-metadata` | 7 passed |
| Canary / `git diff --check` | Passed |

Existing regression skips: two Docker isolation tests (no prepared daemon/images)
and one RSC numerical-reference test (SciPy/scikit-learn absent in the selected
Python environment). Nothing was installed to enable them.

Docker availability was checked read-only. The configured local OrbStack socket
was absent. No image was built, pulled or published. The new optional real-Docker
integration check was not enabled. Process-mode tests use only trusted local test
submissions; they do not prove filesystem isolation or enforce network denial.
The worker Dockerfile/interface remains unverified in a live container.

Synthetic JSON schemas/protocol, numerical comparisons, failure handling and CLI
integration are implemented. The official task's numerical protocol is still a
blocked draft with explicit null bindings. Official Brain-Score, model/tokenizer
revisions, data/ceiling provenance, trace equivalence, live/cache equivalence,
scientific tolerances, production resource calibration and real Agent runs remain
pending. NumPy 2.1.3 portability on CI is configured, but has not been executed in
this local environment. No claim of official-method equivalence follows from the
synthetic checks.

All generated arrays, reference answers and scored CLI bundles were temporary and
removed. No real data, weights, remote samples, cached model outputs, paid models,
formal benchmark scores, pushes, PRs or uploaded artifacts were produced.

Reproduction: use the commands in [README.md](README.md). The parent scoring
report records fixture seeds, input hashes and evaluator/runtime provenance;
`evaluate.py <bundle> --seed <recorded-seed>` replays the synthetic rerun selection.
Real-data entry points and promotion prerequisites are listed in the
[candidate README](../../alignment/alignment-pereira2018-analysis/README.md).
