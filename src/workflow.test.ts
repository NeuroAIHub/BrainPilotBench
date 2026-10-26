import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, lstatSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { pathToFileURL } from "node:url";
import { assertAgentDataBoundary, buildSubmissionBundle, prepareWorkspace, readManualRunState, syntheticRunResult, writeManualRunState } from "./workflow.js";
import type { Task } from "./task.js";

function task(dir: string): Task {
  return {
    meta: { id: "workflow-task", domain: "d", summary: "summary", expectedArtifacts: [{ workspace: "output/*.txt" }], timeoutMin: 1, budgetTokens: 1, requires: {}, version: "0.1" },
    turns: [{ send: "first" }, { send: "second" }], askUser: {}, rubric: { dimensions: ["x"] },
    scorers: [{ kind: "exec-script" }], datasets: [], dir,
  };
}

test("prepareWorkspace writes the prompt and runs task setup", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-prepare-"));
  try {
    const taskDir = join(root, "task");
    const workspace = join(root, "workspace");
    mkdirSync(join(taskDir, "env"), { recursive: true });
    writeFileSync(join(taskDir, "env", "setup.sh"), "#!/bin/bash\nset -eu\nprintf staged > setup.marker\n");
    const prepared = prepareWorkspace(task(taskDir), workspace);
    assert.equal(prepared.setupRan, true);
    assert.ok(existsSync(join(workspace, "setup.marker")));
    assert.match(readFileSync(prepared.promptPath, "utf8"), /Turn 2[\s\S]*second/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("prepareWorkspace resolves a relative task root before changing cwd", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-relative-prepare-"));
  try {
    const taskDir = join(root, "task");
    const workspace = join(root, "elsewhere", "workspace");
    mkdirSync(join(taskDir, "env"), { recursive: true });
    writeFileSync(join(taskDir, "env", "setup.sh"), "#!/bin/bash\nset -eu\nprintf staged > relative.marker\n");
    const prepared = prepareWorkspace(task(relative(process.cwd(), taskDir)), workspace);
    assert.equal(prepared.setupRan, true);
    assert.ok(existsSync(join(workspace, "relative.marker")));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("prepareWorkspace refuses a dangling task prompt symlink", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-prompt-link-"));
  try {
    const workspace = join(root, "workspace");
    const hidden = join(workspace, ".bpb");
    const outside = join(root, "outside.md");
    mkdirSync(hidden, { recursive: true });
    symlinkSync(outside, join(hidden, "TASK_PROMPT.md"));
    assert.throws(() => prepareWorkspace(task(root), workspace), /unsafe task prompt path/);
    assert.equal(existsSync(outside), false);
    assert.equal(lstatSync(join(hidden, "TASK_PROMPT.md")).isSymbolicLink(), true);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("prepareWorkspace copies verified public cache files and passes the generic root to setup", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "bpb-public-prepare-")));
  const oldCache = process.env.BPB_CACHE_ROOT;
  try {
    const body = Buffer.from("public atlas");
    const sha256 = createHash("sha256").update(body).digest("hex");
    const taskDir = join(root, "task"), workspace = join(root, "workspace"), cache = join(root, "cache");
    process.env.BPB_CACHE_ROOT = cache;
    mkdirSync(join(cache, sha256), { recursive: true });
    writeFileSync(join(cache, sha256, "data"), body);
    mkdirSync(join(taskDir, "env"), { recursive: true });
    writeFileSync(join(taskDir, "env", "setup.sh"), "#!/bin/bash\nset -eu\nprintf '%s' \"$BPB_PUBLIC_DATA_ROOT\" > setup-root.txt\n");
    const t = task(taskDir);
    t.datasets = [{ name: "atlas", uri: "hf://owner/repo/atlas", sha256, bytes: body.length, scope: "public", path: "atlas/data.csv" }];
    const prepared = prepareWorkspace(t, workspace);
    assert.equal(prepared.publicDataRoot, join(workspace, ".bpb", "public-data"));
    assert.equal(readFileSync(join(prepared.publicDataRoot!, "atlas", "data.csv"), "utf8"), body.toString());
    assert.equal(readFileSync(join(workspace, "setup-root.txt"), "utf8"), prepared.publicDataRoot);
    assert.equal(lstatSync(join(prepared.publicDataRoot!, "atlas", "data.csv")).nlink, 1);
    assert.equal(prepareWorkspace(t, workspace).publicDataRoot, prepared.publicDataRoot);
  } finally {
    if (oldCache === undefined) delete process.env.BPB_CACHE_ROOT; else process.env.BPB_CACHE_ROOT = oldCache;
    rmSync(root, { recursive: true, force: true });
  }
});

test("prepareWorkspace handles many mapped files with a low file-descriptor limit", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "bpb-public-fd-")));
  try {
    const cache = join(root, "cache"), workspace = join(root, "workspace");
    const t = task(root);
    for (let i = 0; i < 80; i++) {
      const body = Buffer.from(`public-${i}`);
      const sha256 = createHash("sha256").update(body).digest("hex");
      mkdirSync(join(cache, sha256), { recursive: true });
      writeFileSync(join(cache, sha256, "data"), body);
      t.datasets.push({ name: `part-${i}`, uri: `hf://repo/part-${i}`, sha256, bytes: body.length, scope: "public", path: `part-${i}.txt` });
    }
    const moduleUrl = pathToFileURL(join(process.cwd(), "dist", "workflow.js")).href;
    const script = `import { prepareWorkspace } from ${JSON.stringify(moduleUrl)}; prepareWorkspace(${JSON.stringify(t)}, ${JSON.stringify(workspace)});`;
    const child = spawnSync("/bin/bash", ["-c", "ulimit -n 48; exec node --input-type=module -e \"$BPB_TEST_SCRIPT\""], {
      cwd: process.cwd(),
      env: { ...process.env, BPB_CACHE_ROOT: cache, BPB_TEST_SCRIPT: script },
      encoding: "utf8",
    });
    assert.equal(child.status, 0, child.stderr);
    assert.equal(readFileSync(join(workspace, ".bpb", "public-data", "part-79.txt"), "utf8"), "public-79");
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("prepareWorkspace refuses missing or tampered public cache and unsafe destinations", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "bpb-public-tamper-")));
  const oldCache = process.env.BPB_CACHE_ROOT;
  try {
    const body = Buffer.from("verified public data");
    const sha256 = createHash("sha256").update(body).digest("hex");
    const taskDir = join(root, "task"), workspace = join(root, "workspace"), cache = join(root, "cache");
    process.env.BPB_CACHE_ROOT = cache;
    mkdirSync(taskDir);
    const t = task(taskDir);
    t.datasets = [{ name: "data", uri: "hf://owner/repo/data", sha256, bytes: body.length, scope: "public", path: "nested/data.csv" }];
    assert.throws(() => prepareWorkspace(t, workspace), /missing or unsafe in cache/);
    mkdirSync(join(cache, sha256), { recursive: true });
    writeFileSync(join(cache, sha256, "data"), Buffer.from("x".repeat(body.length)));
    assert.throws(() => prepareWorkspace(t, workspace), /cache size\/SHA-256 verification/);
    writeFileSync(join(cache, sha256, "data"), body);
    mkdirSync(join(workspace, ".bpb", "public-data"), { recursive: true });
    symlinkSync(root, join(workspace, ".bpb", "public-data", "nested"));
    assert.throws(() => prepareWorkspace(t, workspace), /plain directory/);
    unlinkSync(join(workspace, ".bpb", "public-data", "nested"));
    mkdirSync(join(workspace, ".bpb", "public-data", "nested"));
    symlinkSync(join(root, "outside"), join(workspace, ".bpb", "public-data", "nested", "data.csv"));
    assert.throws(() => prepareWorkspace(t, workspace), /EEXIST|unsafe/);
    assert.equal(existsSync(join(root, "outside")), false);
  } finally {
    if (oldCache === undefined) delete process.env.BPB_CACHE_ROOT; else process.env.BPB_CACHE_ROOT = oldCache;
    rmSync(root, { recursive: true, force: true });
  }
});

test("prepareWorkspace rejects a symlink ancestor of a mapped workspace", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "bpb-public-ancestor-")));
  try {
    const outside = join(root, "outside");
    mkdirSync(outside);
    symlinkSync(outside, join(root, "link"));
    const t = task(root);
    t.datasets = [{ name: "data", uri: "hf://owner/repo/data", sha256: "a".repeat(64), bytes: 1, scope: "public", path: "data.csv" }];
    assert.throws(() => prepareWorkspace(t, join(root, "link", "workspace")), /symlink parent/);
    assert.equal(existsSync(join(outside, "workspace")), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("prepareWorkspace rejects private mapped paths and stale public root", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-public-boundary-"));
  const oldRoot = process.env.BPB_PUBLIC_DATA_ROOT;
  try {
    const t = task(root);
    t.datasets = [{ name: "labels", uri: "file:///private", sha256: "f".repeat(64), bytes: 0, scope: "private", path: "labels.csv" }];
    assert.throws(() => prepareWorkspace(t, join(root, "workspace")), /private dataset/);
    t.datasets = [];
    process.env.BPB_PUBLIC_DATA_ROOT = join(root, "stale");
    assert.throws(() => prepareWorkspace(t, join(root, "workspace")), /unset BPB_PUBLIC_DATA_ROOT/);
  } finally {
    if (oldRoot === undefined) delete process.env.BPB_PUBLIC_DATA_ROOT; else process.env.BPB_PUBLIC_DATA_ROOT = oldRoot;
    rmSync(root, { recursive: true, force: true });
  }
});

test("buildSubmissionBundle collects artifacts and produces a verifiable bundle", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-bundle-"));
  try {
    const workspace = join(root, "workspace");
    const runDir = join(root, "run");
    mkdirSync(join(workspace, "output"), { recursive: true });
    writeFileSync(join(workspace, "output", "answer.txt"), "answer");
    const built = await buildSubmissionBundle({
      task: task(root),
      result: syntheticRunResult("workflow-task", "workspace", true, Date.now()),
      workspaceDir: workspace,
      runDir,
      agent: "test-agent@1",
    });
    assert.deepEqual(built.artifacts, ["output/answer.txt"]);
    assert.equal(built.issues.filter((issue) => issue.level === "error").length, 0);
    assert.ok(existsSync(join(runDir, "meta.json")));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("manual run state round-trips for resume", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-manual-state-"));
  try {
    const state = { taskId: "workflow-task", taskVersion: "0.1", agent: "manual@1", adapter: "manual" as const, workspaceDir: "/tmp/ws", createdAt: "2026-01-01T00:00:00Z" };
    writeManualRunState(root, state);
    assert.deepEqual(readManualRunState(root), state);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("Agent boundary rejects archive roots and new task evaluator variables", () => {
  for (const key of ["BPB_LOCAL_DATA_ROOT", "BPB_BRAIN_AGE_EVALUATOR_DIR", "BPB_BRAIN_AGE_EVALUATOR_ARCHIVE"]) {
    const previous = process.env[key];
    try {
      process.env[key] = "/private/archives";
      assert.throws(() => assertAgentDataBoundary(task(".")), /unset BPB_LOCAL_DATA_ROOT|private evaluator environment/);
    } finally {
      if (previous === undefined) delete process.env[key]; else process.env[key] = previous;
    }
  }
});

test("assertAgentDataBoundary refuses private evaluator env or cache before Agent start", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-agent-boundary-"));
  const previousXdg = process.env.XDG_CACHE_HOME, previousEval = process.env.BPB_TOPS_PRIVATE_EVAL_DIR;
  try {
    process.env.XDG_CACHE_HOME = root;
    const t = task(root);
    t.datasets = [{ name: "labels", scope: "private", uri: "file:///labels", sha256: "b".repeat(64), bytes: 1 }];
    process.env.BPB_TOPS_PRIVATE_EVAL_DIR = "/private/eval";
    assert.throws(() => assertAgentDataBoundary(t), /private evaluator environment/);
    delete process.env.BPB_TOPS_PRIVATE_EVAL_DIR;
    const cache = join(root, "brainpilot-bench", "b".repeat(64));
    mkdirSync(cache, { recursive: true });
    writeFileSync(join(cache, "data"), "x");
    assert.throws(() => assertAgentDataBoundary(t), /private evaluator data exists/);
  } finally {
    if (previousXdg === undefined) delete process.env.XDG_CACHE_HOME; else process.env.XDG_CACHE_HOME = previousXdg;
    if (previousEval === undefined) delete process.env.BPB_TOPS_PRIVATE_EVAL_DIR; else process.env.BPB_TOPS_PRIVATE_EVAL_DIR = previousEval;
    rmSync(root, { recursive: true, force: true });
  }
});
