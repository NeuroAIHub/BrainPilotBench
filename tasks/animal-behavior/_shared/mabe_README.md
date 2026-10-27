# MABe22 data access, source regeneration, and role boundary

Both MABe22 tasks have public HF mirrors and separate private evaluator packages.
For normal use, install the task environment and follow the [hosted CLI workflow](../../../docs/mouse-task-preparation.md).
The active data locks pin immutable HF revisions. Original-source regeneration is optional and does not override those locks.

## Optional source regeneration

This runbook creates local, ignored data under
`.cache/mouse-closeout-20261026/mabe`. It does not publish the data or run
private Test scoring. Source object NPY files are never opened with
`allow_pickle=True` on the host. The three extraction scripts must run in a
no-network container. The preparation scripts read only numeric H5 and NPZ
data on the host. The original source and pose dataset hashes are checked
before derived files are written.

From the repository root, install the host preparation dependencies and fetch
the exact public assets. On the current macOS Python install, set
`SSL_CERT_FILE=/etc/ssl/cert.pem` if the Python certificate store is empty.

```sh
python3 -m venv .cache/mouse-closeout-20261026/mabe/venv
.cache/mouse-closeout-20261026/mabe/venv/bin/pip install -r tasks/animal-behavior/_shared/mabe_prepare_requirements.txt
.cache/mouse-closeout-20261026/mabe/venv/bin/python tasks/animal-behavior/_shared/mabe_fetch_sources.py --root .cache/mouse-closeout-20261026/mabe
.cache/mouse-closeout-20261026/mabe/venv/bin/python tasks/animal-behavior/_shared/mabe_prepare.py resolve --root .cache/mouse-closeout-20261026/mabe
.cache/mouse-closeout-20261026/mabe/venv/bin/python tasks/animal-behavior/_shared/mabe_prepare.py fetch --root .cache/mouse-closeout-20261026/mabe
.cache/mouse-closeout-20261026/mabe/venv/bin/python tasks/animal-behavior/_shared/mabe_prepare.py prepare --root .cache/mouse-closeout-20261026/mabe
docker build -f tasks/animal-behavior/_shared/mabe_extract_Dockerfile -t bpb-mabe-extract:local .
```

Run each extraction script with the same isolated container settings. Replace
`SCRIPT` with `mabe_trusted_extract.py`, `mabe_probe_trusted_extract.py`, and
`mabe_usertrain_trusted_extract.py`, one at a time. The data mount is the only
writeable mount; the container has no network and cannot write to its own
filesystem.

```sh
SCRIPT=mabe_trusted_extract.py
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" -e MABE_ISOLATED_EXTRACTION=1 \
  -v "$PWD/.cache/mouse-closeout-20261026/mabe:/data:rw" \
  -v "$PWD/tasks/animal-behavior/_shared/$SCRIPT:/src/$SCRIPT:ro" \
  --entrypoint python bpb-mabe-extract:local "/src/$SCRIPT"
```

Repeat that isolated command for the three named scripts. Then materialize
the exact revisioned local packets from the numeric preparation files.
A clone already has `contract.json`, `data.lock`, and `evaluator.lock`.
The materializer validates regenerated content against the accepted contract and recorded transport mapping.
It does not rewrite those files. It verifies and reuses an existing complete packet.
Partial or altered metadata and incomplete packet trees fail closed.

```sh
MABE_PREPARED=".cache/mouse-closeout-20261026/mabe"
MABE_LOCAL=".cache/mouse-closeout-20261026/mabe-local-source"
for TASK_ID in mabe22-supervised-segmentation mabe22-representation-classification; do
  "$MABE_PREPARED/venv/bin/python" tasks/animal-behavior/_shared/mabe_task_package.py \
    --task-dir "tasks/animal-behavior/$TASK_ID" \
    --prepared "$MABE_PREPARED" --local-root "$MABE_LOCAL" --materialize-only
done
```

## Hosted preparation after environment setup

The commands below fetch the hosted packets, independently of optional local regeneration.
The source-root environment variable does not override HF entries in a data lock.
First create `.cache/mouse-runtime` with the environment commands in the [mouse guide](../../../docs/mouse-task-preparation.md).

```sh
unset BPB_LOCAL_DATA_ROOT
export BPB_MABE_PYTHON="$PWD/.cache/mouse-runtime/bin/python"
export BPB_CACHE_ROOT="$PWD/.cache/mouse-closeout-20261026/mabe-public-cache"
npm run build
node dist/cli.js fetch mabe22-supervised-segmentation --public
node dist/cli.js prepare mabe22-supervised-segmentation --workspace "$PWD/.cache/mouse-closeout-20261026/workspace-supervised"
node dist/cli.js fetch mabe22-representation-classification --public
node dist/cli.js prepare mabe22-representation-classification --workspace "$PWD/.cache/mouse-closeout-20261026/workspace-representation"
node dist/cli.js prepare-evaluator mabe22-supervised-segmentation --evaluator-root "$PWD/.cache/mouse-closeout-20261026/owner-supervised/evaluator" --cache-root "$PWD/.cache/mouse-closeout-20261026/mabe-owner-cache" --fetch
node dist/cli.js prepare-evaluator mabe22-representation-classification --evaluator-root "$PWD/.cache/mouse-closeout-20261026/owner-representation/evaluator" --cache-root "$PWD/.cache/mouse-closeout-20261026/mabe-owner-cache" --fetch
```

The two `prepare-evaluator` commands are maintainer-only and stage the
evaluator role outside Agent workspaces. They do not score Test. Use fresh,
owner-only evaluator destinations on a new machine.

Role directories matter more than their current names:

| Task | Agent packet whitelist | Trusted evaluator | Owner-only Test |
|---|---|---|---|
| Supervised pose | `public/pose/{train,val}/*.npz`, `public/train_labels.npz`, `public/val_labels.npz`, packet manifest | `public/pose/test/*.npz` and four source manifests in the evaluator packet | `owner/test_labels.npz` |
| Six-target representation | `public/probe_usertrain/*.npz`, `public/probe_profile.json`, packet manifest | `public/probe_pose/*.npz`, `evaluator/probe_labels/*_SubmissionTrain.npz`, profile and preparation manifest in the evaluator packet | `owner/probe_labels/*_publicTest.npz`, `*_privateTest.npz` |

The representation Agent receives no six-target probe-training labels. The
784 user-train NPZs contain keypoints only; source chases/lights annotations
are not exported. The preparation cache retains supervised Test pose and all
1,830 submission poses under historical `public/` paths; the final Agent
packet copies only the whitelist above. Never mount the preparation cache
root, source NPY files, or evaluator packet in an Agent development workspace.

Input/output array contracts:

- Supervised input: `pose` float32 `[1800,3,12,3]`, with source NaNs
  preserved, and `frame_index` int32 `0..1799`. The four class labels are
  `[chases,huddles,oral_contact,oral_genital_contact]`, where oral contact is
  the union of source oral-ear and oral-oral contact. The frozen model returns
  independent finite `probabilities` float `[1800,4]` in `[0,1]`; the owner
  serializes predictions for each Test video.
- Representation input: `keypoints` int32 `[1800,3,12,2]`. The frozen model
  returns finite `embedding` float `[1800,d]`, common `1<=d<=128`; the owner
  serializes embeddings for 1,830 submission IDs. The trusted evaluator fits
  the three frozen Ridge probes for each of six
  targets from its own labels and scores only after the owner Test gate.

The preparation QA commands below use public supervised train/validation data
or a maintainer-only internal holdout from the probe's SubmissionTrain role.
The latter is not an Agent-facing public Oracle. Neither reads Test labels:

```sh
.cache/mouse-closeout-20261026/mabe/venv/bin/python tasks/animal-behavior/_shared/mabe_reference.py --root .cache/mouse-closeout-20261026/mabe --report .cache/mouse-closeout-20261026/mabe/supervised-reference-local.json
.cache/mouse-closeout-20261026/mabe/venv/bin/python tasks/animal-behavior/_shared/mabe_probe.py --root .cache/mouse-closeout-20261026/mabe --internal-validation --report .cache/mouse-closeout-20261026/mabe/probe-internal-validation-local.json
```

The current supervised task is pose-only. Original videos were not downloaded, so visual pose/video alignment was not checked.
The [representation notice](../mabe22-representation-classification/NOTICE.md) and [supervised notice](../mabe22-supervised-segmentation/NOTICE.md) preserve the source licenses and attribution.
The [license audit](../../../reports/mouse-hf-20261027/license-audit.json) records permission for this noncommercial research mirror, not unrestricted commercial reuse.
The [HF publication record](../../../reports/mouse-hf-20261027/publication.json) binds delivery to the accepted content. It does not claim new Agent results.
