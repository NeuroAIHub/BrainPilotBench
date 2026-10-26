# MABe22 source-only tasks: preparation, materialization, and role boundary

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
the exact revisioned `local://` packets from the numeric preparation files.
A clone already has `contract.json`, `data.lock`, and `evaluator.lock`; the
materializer compares all three byte for byte with the pinned source and
does not rewrite them. It verifies and reuses an existing complete packet.
Partial or altered metadata and incomplete packet trees fail closed.

```sh
MABE_PREPARED=".cache/mouse-closeout-20261026/mabe"
MABE_LOCAL=".cache/mouse-closeout-20261026/mabe-local-source"
for TASK_ID in mabe22-supervised-segmentation mabe22-representation-classification; do
  "$MABE_PREPARED/venv/bin/python" tasks/animal-behavior/_shared/mabe_task_package.py \
    --task-dir "tasks/animal-behavior/$TASK_ID" \
    --prepared "$MABE_PREPARED" --local-root "$MABE_LOCAL" --materialize-only
done
unset BPB_LOCAL_DATA_ROOT
export BPB_MABE_PYTHON="$PWD/$MABE_PREPARED/venv/bin/python"
export BPB_CACHE_ROOT="$PWD/.cache/mouse-closeout-20261026/mabe-public-cache"
npm run build
BPB_LOCAL_DATA_ROOT="$PWD/$MABE_LOCAL" node dist/cli.js fetch mabe22-supervised-segmentation --public
node dist/cli.js prepare mabe22-supervised-segmentation --workspace "$PWD/.cache/mouse-closeout-20261026/workspace-supervised"
BPB_LOCAL_DATA_ROOT="$PWD/$MABE_LOCAL" node dist/cli.js fetch mabe22-representation-classification --public
node dist/cli.js prepare mabe22-representation-classification --workspace "$PWD/.cache/mouse-closeout-20261026/workspace-representation"
BPB_LOCAL_DATA_ROOT="$PWD/$MABE_LOCAL" node dist/cli.js prepare-evaluator mabe22-supervised-segmentation --evaluator-root "$PWD/.cache/mouse-closeout-20261026/owner-supervised/evaluator" --cache-root "$PWD/.cache/mouse-closeout-20261026/mabe-owner-cache" --fetch
BPB_LOCAL_DATA_ROOT="$PWD/$MABE_LOCAL" node dist/cli.js prepare-evaluator mabe22-representation-classification --evaluator-root "$PWD/.cache/mouse-closeout-20261026/owner-representation/evaluator" --cache-root "$PWD/.cache/mouse-closeout-20261026/mabe-owner-cache" --fetch
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

The pose-only supervised route is prepared. Original video input remains
optional and was not downloaded; visual pose/video alignment therefore has
not been checked. Provenance/licensing review is still required before data
publication; a local source-only preparation does not grant redistribution.
