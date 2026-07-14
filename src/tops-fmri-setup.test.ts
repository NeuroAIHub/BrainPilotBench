import { test } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync, spawnSync } from "node:child_process";

const SETUP = join(process.cwd(), "tasks", "tops-fmri", "env", "setup.sh");
const PUBLIC_SHAS = [
  "17ca43dbc6ec53f9d9a1ae7b5ad234160d1dfee96dc5d83c714dd4cf87ae7366",
  "051316b32ffe0b39d32ef1a577d82f6c18e5a90425d9082367566cd7b83204d2",
];
const PRIVATE_SHAS = [
  "e709d9c3fa5ab067dd58d0ad205185423dad7e531bba8c7466e1d24bef924c56",
  "95bc997c345fbe7429a5f5f4d850f782faaf9616c3a9074b8e34efa0b5aabb58",
];

function seed(cache: string, shas: string[]): void {
  for (const sha of shas) {
    const dir = join(cache, sha);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "data"), sha);
  }
}

function fakeTools(root: string): string {
  const bin = join(root, "bin");
  mkdirSync(bin);
  const zstd = join(bin, "zstd");
  writeFileSync(zstd, "#!/bin/bash\nexit 0\n");
  chmodSync(zstd, 0o755);
  const tar = join(bin, "tar");
  writeFileSync(tar, `#!/bin/bash
set -eu
dest=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-C" ]; then dest="$2"; shift 2; else shift; fi
done
mkdir -p "$dest/public_support/atlas" "$dest/public_support/example_participant"
mkdir -p "$dest/private_features/features" "$dest/private_labels/labels"
touch "$dest/public_support/atlas/atlas.txt" "$dest/public_support/example_participant/example.txt"
touch "$dest/private_features/features/study4_features.npz" "$dest/private_labels/labels/study4_labels.npz"
`);
  chmodSync(tar, 0o755);
  return bin;
}

test("tops-fmri setup: agent role needs public cache only; evaluator is explicit and external", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-tops-setup-"));
  try {
    const cache = join(root, "cache");
    const workspace = join(root, "agent-workspace");
    const evaluator = join(root, "evaluator-private");
    mkdirSync(workspace);
    seed(cache, PUBLIC_SHAS);
    const bin = fakeTools(root);
    const env = { ...process.env, PATH: `${bin}:${process.env.PATH ?? ""}`, BPB_CACHE_ROOT: cache };

    execFileSync("/bin/bash", [SETUP], { cwd: workspace, env, stdio: "pipe" });
    assert.ok(existsSync(join(workspace, "public_data", "whole_participants", "FC_and_pain", "study3_train.mat")));
    assert.ok(existsSync(join(workspace, "public_data", "atlas", "atlas.txt")));
    assert.equal(existsSync(join(root, ".tops-fmri.env")), false);
    assert.equal(existsSync(join(workspace, "private_eval")), false);

    const noPrivate = spawnSync("/bin/bash", [SETUP, "--role", "evaluator"], {
      cwd: workspace,
      env: { ...env, BPB_TOPS_PRIVATE_EVAL_DIR: evaluator },
      encoding: "utf8",
    });
    assert.notEqual(noPrivate.status, 0);
    assert.match(noPrivate.stderr, /bp-bench fetch tops-fmri --private/);

    seed(cache, PRIVATE_SHAS);
    execFileSync("/bin/bash", [SETUP, "--role", "evaluator"], {
      cwd: workspace,
      env: { ...env, BPB_TOPS_PRIVATE_EVAL_DIR: evaluator },
      stdio: "pipe",
    });
    assert.ok(existsSync(join(evaluator, "features", "study4_features.npz")));
    assert.ok(existsSync(join(evaluator, "labels", "study4_labels.npz")));

    const inside = spawnSync("/bin/bash", [SETUP, "--role", "evaluator"], {
      cwd: workspace,
      env: { ...env, BPB_TOPS_PRIVATE_EVAL_DIR: join(workspace, "private") },
      encoding: "utf8",
    });
    assert.notEqual(inside.status, 0);
    assert.match(inside.stderr, /must be outside the agent workspace/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
