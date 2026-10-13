# Psych-101 task collection

All 76 published experiment IDs now have individual public-validation task packages. Twenty-two use audited closed categorical response-space profiles: the original 12 plus ten same-family variants whose 283,625 public train/valid marked responses were checked against the existing profile with zero mismatches. The other 54 use a new, separately versioned `byte_next_v1` interface: a normalized distribution over 256 UTF-8 bytes plus explicit EOS at each causal step. `metadata-only.json` records that no published ID remains unregistered; it does not assert that 76 tasks have been scientifically accepted or run.

Each runnable task pins its own public `train.jsonl` and `valid.jsonl` at an immutable Hugging Face revision in `data.lock`. The setup helper checks the frozen split hashes, participant groups, and response counts. It reads the fetched splits and does not download the original 859,179,475-byte source during normal preparation. The gated official Test is not included or scored here. Historical research, controller, monitoring, frozen models and private Test remain in the original Psych101-Agent-Bench project. This collection's score is public validation only; prior Test results do not become BrainPilotBench acceptance.

Source provenance: `marcelbinz/Psych-101` revision `611565c66395e2787cd7e3305149bb75dc138024`, file `prompts_training.jsonl` (SHA-256 `7a370a94084acd6f73f20d6559214683cfadcab8a1f69e369df285ba75ccef01`), associated paper DOI `10.1038/s41586-025-09215-4`. The pinned source manifest records Apache-2.0 for this public file. The separately gated official Test has a different redistribution restriction and is intentionally absent from this collection.

The shared Python helpers in `_shared/contract.py` and `_shared/responses.py` are byte-identical copies of Psych101-Agent-Bench files (SHA-256 `de9ff85319bde7a20b2f12e26a57ac28ca1f7d7d589d7f4a901e93f901f72cc3` and `584cdecc0bb9f985b7a9a3b3039abd3690ccae165b1ad589ec91ed3a16aa7b52`). They use Python 3.11–3.13 standard library only. The public validation scorer is a new task-scoped implementation, not the historical private Test evaluator.

`checks/check.sh` invokes `_shared/score_isolated.py`: the trusted controller retains the current target answer while a pinned Docker worker receives one causal prefix at a time. Earlier completed responses and feedback remain visible in that prefix. Its only data mount contains the nine required model files. The worker has no network, host cache, Test mount, or credentials. `env/Dockerfile` pins the additional SciPy and scikit-learn inference dependencies; the tested arm64 image digest is recorded in the controller. This does not prove arbitrary historical frozen models work with that image. `BPB_OFFICIAL_SCORING=1` is rejected because these tasks have no authorized private-Test scoring path.

The `byte_next_v1` scorer teacher-forces only prior bytes of the current marked response. It never passes the next target byte or whole answer to the model. Per-response NLL includes EOS, making it a distinct metric version from historical model-token and closed categorical scores. It scores only literal `<<...>>` source spans; unmarked omissions such as Go/NoGo `press nothing` remain context, not additional targets. Raw numeric spellings are preserved, including Wu2018 `0` answers that conflict with its 1–30 instruction. This is a faithful, explicit *marked-response* target policy, not a claim to cover every scientific behavior in every source experiment.

Build the standalone inference image from the pinned Python base and pinned top-level numerical packages before public scoring on a new host. Use its immutable image ID, which may differ by CPU architecture:

```sh
docker build -f tasks/psychology/env/Dockerfile -t bpb-psych101-inference:local tasks/psychology/env
IMAGE_ID="$(docker image inspect bpb-psych101-inference:local --format '{{.Id}}')"
bp-bench score <submission-bundle> --isolation docker --inference-image "$IMAGE_ID"
```

From the repository root, run `node dist/cli.js fetch <task-id> --public`. Then run `node dist/cli.js prepare <task-id> --workspace /absolute/new-workspace`. If you have an existing verified experiment package, set `BPB_PSYCH101_PUBLIC_TASK_DIR` to its directory with `train.jsonl` and `valid.jsonl`. The setup helper checks both split hashes. The scorer checks those hashes again before any model code runs. The Docker worker runs under non-root UID, with no network, a read-only root filesystem, 2 CPU cores, 4 GiB memory, a small process limit, and finite per-query and total scoring deadlines. The host controller alone emits the BPB score sentinel. This is a bounded container boundary, not a claim of formal isolation proof.

## Public-only publication packet preparation

`public-source-index.json` pins 76 task IDs and 152 public train/valid files. It includes the public source revision and hashes. It excludes official Test counts, labels, controller records, and prior scores. `_shared/stage_public_packet.py` audits each source `spec.json`, file size, SHA-256, experiment ID, response count, and participant split. A public-only packet candidate was staged and independently verified on 2026-10-12. Its 152 split files total 859,179,475 bytes. Those same files are now published at commit `09240a63ce2ec96050313c59221291114ff8df6f` in `BrainPilot-Bench/Tasks-Data-Public`. They are under the frozen 101-task public data namespace `bpb-public-data-20261013-v1`. The packet manifest and frozen selection manifest retain their original candidate statuses. Those statuses describe preparation at the time, not the later Hub publication. Data publication does not imply scientific task acceptance.

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
