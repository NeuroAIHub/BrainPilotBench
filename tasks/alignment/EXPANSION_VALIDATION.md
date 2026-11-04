# Expansion validation — 2026-11-04

All A–F experimental implementations now have real-data reference execution,
isolated Docker scoring, positive/negative cases and complete CLI lifecycle
evidence. Development followed A → B → F → E → C → D. Scientific acceptance and
independent Agent benchmark results remain pending. Llama downloading remains deferred.
Canonical inventory remains 112 runnable tasks and 6 candidates.

All large inputs, submissions, predictions and logs are outside Git in
`/tmp/bpb-alignment-expansion-20261104` (`RUN` below). These are local temporary
artifacts, not a durable/public dataset release. Code and protocol are described
in [EXPANSION_RUNBOOK.md](EXPANSION_RUNBOOK.md) and
[INCREMENTAL_CONTRACT.md](INCREMENTAL_CONTRACT.md).
The executed implementation and contract are copied into
`RUN/implementation-snapshot`; `RUN/implementation-sha256.json` binds 17 source
files and records base commit `3b96218`. The snapshot includes working-tree
changes and is not represented as a committed revision.

## Environment and source data

Reused the verified cache and Python 3.11 environment from
[SERVER_VALIDATION.md](SERVER_VALIDATION.md): Pereira384, distilgpt2 revision
`2290a62682d06624634c1f46a6ad5be0f47f38aa`, final block `transformer.h.5`, NumPy
1.26.4, scikit-learn 1.7.2, pinned Brain-Score Language commit
`3b4fde5d6f53a69c652c7a1128397549995547b0`. No additional model download occurred.
Task B ran inference on CPU using the existing local weights.

Source cache:
`/tmp/bpb-alignment-server-20261102/distilgpt2-cache-v3`;
manifest SHA-256 `f6cc1194d94a9b3022c866fa0e503a984db5114a120d8a4f83ab6eeea0fe4e32`.

Docker worker reused the existing local image
`bpb-alignment-server-validation:20261102-py311-final`, immutable ID
`sha256:14d8fd6c25a24acc3eb72a7e45986ac8bab4699d831d6257997b290f9a814eaa`.
The worker image contains neither the new Task A reference/grader package nor its
reference results. The explicit maintainer submission contains its own baseline
source. No new network-based image build was validated.

The data audit found 18 identically-zero response columns, all in subject `018`.
Task A's first attempted R² computation rejected their zero denominators. The
public protocol now explicitly excludes exactly constant columns during owner
preparation, before fitting, recording every ID and reason in provenance. This
uses the full supplied dataset for target-set QC, not a train-only selection
procedure. The remaining data have 384 sentences, 96 four-sentence passages,
24 upstream `story` groups, 9 subjects and 12,137 neuroids. Here `story` is
`384sentences.` plus passage category, rather than a continuous narrative.

## Task A — current protocol v2

Current ID/profile/version:
`alignment-incremental-explanation` /
`pereira384-incremental-ridge-v2` / `0.2-server-draft`.

Agent analysis choices are word count, sentence position, or both, with a stated
rationale. Model layer, nested story splits, train-only feature scaling,
shared-alpha selection, metric aggregation and uncertainty calculation are fixed.
All analysis responses are visible; this is not a hidden-response decision task.

Current artifacts:

- Input packet: `RUN/task-a-inputs-v3` (directory iteration 3, scientific protocol 2).
  Manifest SHA-256 `dc82c07caa08934190a5ef715abca9f704cfd5ae457fd9d13efaa824db60d1fc`.
- Reference source/results: `RUN/task-a-reference-submission-v3`,
  `RUN/task-a-reference-v3`.
- Staged task/workspace: `RUN/task-a-v3`, `RUN/task-a-workspace-v2`.
- Actual CLI bundle: `RUN/runs/task-a-real-002`; agent label
  `maintainer-reference-not-agent`.
- False-causal-claim submission/grade:
  `RUN/task-a-wrong-conclusion-submission-v2`, `RUN/task-a-docker-negative-v2`.

For the `word_count+position` baseline:

| Readout | Mean held-out R² |
|---|---:|
| Declared controls | 0.008714534098196081 |
| Fixed model representation | 0.016252767726416976 |
| Controls plus model | 0.01671782068763015 |
| Joint minus controls | 0.008003286589434068 |

The paired story-bootstrap descriptive interval for the increment is
`[-0.0016021353721136697, 0.017616629206574922]`, crossing zero. It conditions on
the fitted OOF predictions and does not account for refitting uncertainty. The
bounded conclusion is `interval_includes_zero`, not evidence of equivalence,
causality, complete confound removal or new-participant generalization.

All five outer training folds selected alpha 100 for controls, and 10,000 for
model and joint readouts. These are interior grid points in v2. The reference
run took 16.11 s and peaked at 435,536 KiB host RSS; other jobs overlapped, so this
is not resource calibration or a container peak measurement.

The actual prepare/manual/resume/verify/score CLI workflow passed through Docker:
`analysis_success=1`. Saved artifacts and isolated source replay matched the
owner's reference, including full OOF predictions and inner tuning diagnostics.
The real Docker negative submission computed correct numbers but asserted
`causal_effect_established=true`: score 0 with `conclusion.json mismatch`.
See `RUN/task-a-cli-score-v2.log` and
`RUN/task-a-docker-negative-v2/grade.json`.

### Why v2 exists

The initial v1 grid ended at alpha 1000. Every model/joint inner-validation
selection reached that maximum. V1 produced a negative increment of
`-0.07807210359032485`, interval `[-0.0996146890099145, -0.05785138200596246]`.
This limited-grid result and its positive/negative grader checks are retained in
`task-a-reference-v2`, `task-a-docker-positive`, `task-a-docker-negative` and
`runs/task-a-real-001`.

Based on the **training-fold selection diagnostics**, v2 extended the frozen
grid to 10,000, 100,000 and 1,000,000. Both versions remain development analyses
on previously inspected data. The changed result demonstrates readout sensitivity;
it does not establish that the new result is an independent confirmation. V1
packets are archived evidence, not inputs to the current v2 grader.

## Task B — current short-context pilot v2

The first extraction evaluated 192 position-3/4 targets with sentence-only,
normal prior-prefix and reversed prior-prefix contexts. All contexts exclude
future sentences. Normal-prefix features matched the verified cache exactly:
maximum absolute difference 0. No input was truncated (maximum 77 tokens).
The first extraction took 108.58 s and peaked at 1,283,140 KiB host RSS, with
overlapping jobs; it is not a resource limit.

Preserving the preceding sentences did not preserve token count in 32 cases.
V2 explicitly removes these input-defined mismatches and uses the **same 160
targets, 24 groups and 9 subjects in all three conditions**. It replays the
verified extracted features, using the expanded v2 ridge grid; no second model
download or inference pass was required.

Current artifact: `RUN/task-b-pilot-v2`;
manifest SHA-256 `c2c0def1a53f0154ee3a3662b0d3798c0b53615afcd63ef2a0003521d2714714`.
Source extraction and first exploratory result: `RUN/task-b-pilot`.

| Condition | Mean held-out R² |
|---|---:|
| Sentence only | 0.007674357398050312 |
| Normal prefix | 0.008295041988453529 |
| Reversed prefix | 0.007913251319673544 |

| Paired difference | Mean ΔR² | Conditional descriptive interval |
|---|---:|---|
| Normal − sentence only | 0.0006206845904032166 | [-0.0030329045675626725, 0.004278351263789175] |
| Normal − reversed | 0.0003817906687799844 | [-0.0003093836343705536, 0.0011648602653226382] |

Both intervals cross zero. This pilot does not establish a reliable context
advantage, equivalence, long-term memory or a corresponding human intervention
effect. Reversal changes the complete preceding sentence order, including the
most recent sentence; it is not a long-history experiment preserving a recent
window. Data-dependent protocol development is labeled exploratory.

The feature files retain all 192 candidates; `analysis_selection.json` records
the 160 analyzed IDs and 32 exclusions. Predictions and final folds use the
160-ID subset. The complete Task B below imports these verified features into a
public analysis packet and adds isolated grading. Canonical registration remains pending.

## Initial A/pilot checks (retained historical record)

- 15 offline Task A/context checks passed, including full nested-CV agreement
  with an independent scikit-learn implementation, test-response perturbation,
  explicit QC, alternative controls, negative outcomes, ID permutations,
  falsified predictions/conclusions and worker error classification.
- Existing Task1 Python suite: 34/34, including actual Docker execution.
- Existing Task2 suite: 37/37 plus MCP and CLI lifecycle passed on the host.
  The default filesystem sandbox's leaderboard subprocess returned empty output;
  host replay passed without a product change. Both logs are retained.
- Task A schema validation passed with explicit `tasks,<staged-task>` roots.
- Canonical collection/catalog checks passed: 112 runnable, 6 candidates.
- Documentation command checks passed on the host; TypeScript typecheck passed.
- Build and Node suite passed: 248 tests passed, 3 skipped, no failures.
- The new offline suite is included in the Linux/macOS validation workflow.

Actual independent Agent/owner isolation, Agent-generated analyses, expert review
of the scientific protocol and prose, resource/tolerance calibration, and human
or Agent capability comparisons are still pending. Numerical reference success
is not an Agent capability result. The complete fixed script baseline already
satisfies the automatic contract; rationale quality and autonomous discovery are
not certified by `analysis_success`. No canonical promotion, commit, push or
publication has been performed.

## Completed B–F implementation and real acceptance checks

The continuation implements B → F → E → C → D. Its files are in
`/tmp/bpb-alignment-suite-20261104` (`SUITE` below), currently about 2.6 GB including
the downloaded EEG archives. [The B–F contract](EXPANSION_CONTRACT.md) defines every
input, output, numerical procedure and interpretation check. Source downloads are
pinned in [_shared/expansion/sources.json](_shared/expansion/sources.json): OSF
SHA256 checks, Figshare's supplied MD5 plus a content SHA256, and the fixed GitHub
blob identity were verified. Nothing required a new model or Llama download.

The source pipeline supports explicit bounded/resumable downloads, verification,
archive extraction, owner-only EEG dictionary conversion in Docker, and fresh
packet creation. Neither task setup nor scoring downloads data. The EEG converter
exports only numerical arrays/JSON. It does not unpickle author data on the host.

| Task | Current public packet | Manifest SHA256 |
|---|---|---|
| B | `SUITE/task-b-inputs-v2` | `e5488c299fed320f5a43586fd58b52d6de891d412d87097deedbc935517fd6ed` |
| F | `SUITE/task-f-inputs-v2` | `b406d11bb6de43372607fa8c8ac03ee126cc98a9ca3e72548e2fe10d883bcfba` |
| E | `SUITE/task-e-inputs` | `91619c3a0255323a3bf4eb1167db88aa451d3575ab121d0864d7619d95d48281` |
| C | `SUITE/task-c-inputs` | `81b8c59947954b311fe71f202bf25275dc5818245a357db2b35468e7893ee967` |
| D | `SUITE/task-d-inputs-v2` | `456c09b1062609a1d80a1c553755929dafee6ab8a03fdb472eeaf336cd1820e3` |

Directory suffixes identify preparation iterations; the manifest is authoritative
for protocol versions (current B is v2, other B–F profiles are v1). The
first F packet retained source condition ordering despite opaque IDs; the final
packet sorts by opaque IDs and binds a correspondingly reordered hidden packet.
The first D packet retained numeric directory prefixes in concept prompts; the
final preparation strips them and verifies concept/image correspondence before
feature extraction. Those first packets are superseded development artifacts,
not the current evaluation inputs. No score-driven tuning was used for either fix.

Current task roots are `SUITE/task-b-v2` and `SUITE/task-{f,e,c,d}`. The exact CLI
bundles are `SUITE/runs/task-b-real-002` and
`SUITE/runs/task-{f,e,c,d}-real-001`, each labelled
`maintainer-reference-not-agent`. Schema validation, manual workspace preparation,
artifact collection/resume, `submit verify`, and Docker `score` all succeeded.
Setup copied only public inputs and the contract, with no baseline solution.
Each task also has direct `task-LETTER-docker-positive/grade.json` and
`task-LETTER-docker-negative/grade.json` outputs (B's current grade directories
carry a `-v2` suffix).

### B

The complete Agent-facing task imports only the pilot's public features, original
responses, exact contexts/IDs and frozen folds. It excludes the pilot's reference
results. It reproduces the scores and descriptive intervals above. Docker and CLI
returned `analysis_success=1`. A source program emitting an unsupported causal
conclusion returned 0, even when its saved output contained the same false claim.
The final contract audit removed unused A-only control/increment fields inherited
by B's specification and explicitly named the two context contrasts. This is
`pereira384-context-v2` / task version `0.2-server-draft`. Both the positive/negative
Docker cases and full CLI were rerun; numerical results were unchanged. The v1
packet/task/bundle remain archived development evidence.

### F

The official Tuckute LH-language table contains five baseline-only training
subjects and five evaluation subjects. Candidate coverage is incomplete across
those five evaluation subjects. The chosen common pool has 500 sentences measured
in subjects 797, 841 and 880; the distinct training subjects are
848, 853, 865, 875 and 876. Twelve training sentences have a missing response for
subject 853, leaving 988 complete training sentences. No missing response is
imputed. Training/candidate text and identities are disjoint.

The final public pool removes author condition labels, predictions and other
response-related metadata; its rows are ordered by opaque IDs. Features are frozen
distilgpt2 final-token normalized states. Hidden response packet:
`SUITE/task-f-hidden-v2`; owner ledger: `SUITE/ledgers/maintainer-reference`.
Neither is mounted into the submission worker. The dataset is public: this alone
does not prevent a pretrained Agent from knowing labels, and a production Agent
needs separately enforced development isolation.

The fixed ridge maintainer selected 10 drive and 10 suppress sentences and obtained:

- Mean hidden response difference: **0.3473532235602182** author-normalized units.
- Subject differences: 797 = 0.15122021287679674;
  841 = 0.21846799500000003; 880 = 0.6723714628038578.
- Same-budget random selection mean: 0.0013661194792890625;
  2.5/97.5 percentiles: [-0.42812139361353235, 0.41767461468693506].
- Random-reference percentile: 0.94. This is **not** a population p value or
  evidence that a new human intervention was performed.

The submitted choice need not match the reference predictor; an offline test
checks an entirely different valid selection against independently constructed
hidden response means. Actual Docker evaluation rejects overlapping drive/suppress
sets with no effect score. A second source version against the same ledger is
rejected before revealing another effect (`SUITE/task-f-second-query`). Identical
frozen submissions were accepted again through the full CLI lifecycle. The operator
must reuse the Agent-assigned ledger; arbitrary fresh ledgers would defeat the limit.

### E

Uses the processed Holton table at commit
`dcd451046759ebbbfa2987031a64da8c773e750d`, selecting 18 participants independently
of response scores: three per study × same/near/far condition, six per mapping
condition in total. Each has 120 events per A1/B/A2 phase, 60 feature-1 responses.
No selected participant needed exclusion for missing required responses.

The two provided 12→50→4 linear networks use the actual noisy-feedback sequence
once or 100 times per phase; state persists and updates require feedback. Their
architecture is motivated by the author code but this is a **derived baseline**,
not exact original simulation replication: initialization, feedback targets and
learning rate are explicitly specified. Analysis includes feature-1 trials without
feedback, which is essential for A2 interference. Relative-progress bins do not
pretend that repeated-model and human experience counts match.

The structured experience audit identifies `linear50_feedback_once` as matched
in event/feedback counts and `linear50_feedback_replay100` as unmatched. Full
per-participant metrics/curves and paired intervals are saved. Docker/CLI return 1;
unsupported causal interpretation returns 0. No neural mechanism is inferred from
this behavioral dataset.

### C

Uses the author IT testset derivative (Figshare 23284622), three subjects × 100
images × 12 repetitions, and THINGS concept-level odd-one-out data. The source
preprocessing script proves that `trainset.txt` already addresses sorted zero-based
`unique_id`: applying `sortind` again would be an identity error. The implementation
keeps original image IDs and declares the single-exemplar/concept proxy.

Candidates are distilgpt2 first-block/final-block representations of concept
names, **not image-input vision models**. Train/discovery/confirmation have 40/30/30
concepts and only **44/16/17** retained within-partition behavioral judgments.
Temperatures selected on training concepts are 0.1 and 0.01; the latter is the
smallest allowed grid value, not a claim of an unrestricted optimum.

Confirmation neural RSA is 0.023666653545928184 versus 0.03414186239649802;
behavior NLL is 1.0145587132897353 versus 1.0905588010178549. Their descriptive
rankings point in opposite directions, but paired concept-jackknife SEs are
0.07882066699985445 for the neural contrast and 0.15963309199910533 for the behavior
contrast. **This small sample does not establish a reliable population dissociation.**
Docker/CLI analysis correctness is 1; false interpretation is rejected with 0.

### D

Uses THINGS-EEG2 author subjects 01/02, 200 test images, 80 repeats, 17 channels,
100 samples from -200 to 790 ms. Both approximately 1.07 GB subject archives were
resumed over the unstable connection and verified against OSF SHA256:
`f25d5ea30ba6811edd7ebd460d7b271edaf527b6920ab2d3d6e7950e9ee9639f`,
`e1eba2d74009c6dd41becf53d84b8d47532103b41110a5855e7e286bcca6fe41`.
The bounded Docker conversion is `SUITE/eeg2-converted`, manifest
`f037fd90dc43627b87905ae5a9d1b92d00d04ef17faf9c0a270c361858054123`.
Author code audited at commit `101997d4f14c41b615bcaf8c0907740106d260c5`.

The owner retains baseline and all post-onset times. Analysis uses subject 01
and 100 concepts for discovery, subject 02 and the other 100 for confirmation;
author MVNN preprocessing is explicitly acknowledged. The model candidates are
static concept-label representations, not model states evolving in time.

Discovery selected 150–200 ms for the first-minus-final-block contrast. Confirmation
difference is 0.05799043188998557, with selected-window stimulus-label permutation
p=0.116 (499 permutations). It does not reject that label-correspondence null and
does not test equality of population model performance. Every time point and
candidate also has a max-statistic corrected p value in the submitted arrays.
Docker/CLI analysis success is 1 despite the inconclusive result; false causal
interpretation returns 0. Direct positive replay took about 1.84 s in the worker,
3.54 s including owner checks/recomputation, with a 2-CPU/8-GB/900-s limit. These
measurements are not resource-limit calibration or a peak-memory estimate.

### Current checks and remaining acceptance

- A/context suite: 15 offline tests passed.
- B–F suite: 19 offline tests passed, including independent SciPy/logsumexp checks,
  finite-difference verification of the simulation gradient, held-out-label/window
  perturbations, disjoint-partition enforcement, paired effects, bounded arrays,
  source corruption and download resumption, source replay, hidden-choice grading, owner-ledger boundaries
  and one-submission behavior. Both suites run in CI without data/model downloads.
- Build and TypeScript typecheck passed. Host Node suite: 249 passed, 2 skipped,
  no failures. The default filesystem sandbox reported three subprocess-suite
  failures; host execution passed without changing those product tests.
- Documentation commands, reader documentation, collection/catalog and canary
  checks passed. Canonical counts remain 112 runnable / 6 candidates / 118 entries.
  Canary's subprocess also required host execution after sandbox `EPERM`.
- All five B–F real CLI bundles and Docker positive/negative cases passed as above.
  A's completed real bundle and negative case remain the evidence recorded earlier.
- No new model weights, canonical task promotion, commit or push. The unused
  `alignment-selection` metric category separates F's signed effect from correctness.

Full expert review, stronger scientific instances (long stories, larger behavior
samples, image-based model candidates, additional temporal subjects), independent
Agent runs and capability/resource calibration remain future acceptance work.
The six requested implementations are runnable experimental profiles; maintainer
script results are not evidence of independent research ability.
