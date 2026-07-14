import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
