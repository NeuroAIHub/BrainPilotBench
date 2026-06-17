import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runScorers, bundleWorkspaceFiles, type RunBundle } from "./score.js";
import { registerScorer } from "./scorer/registry.js";
import type { Task } from "./task.js";

function fakeTask(scorerKinds: string[]): Task {
  return {
    meta: { id: "t1", domain: "d", summary: "s", expectedArtifacts: [{ workspace: "*.md" }], timeoutMin: 5, budgetTokens: 1000, requires: {} },
    turns: [{ send: "hi" }],
    askUser: {},
    rubric: { dimensions: ["correctness"] },
    scorers: scorerKinds.map((kind) => ({ kind })),
    datasets: [],
    dir: "/tmp/x",
  };
}

test("bundleWorkspaceFiles: glob 落在 <runDir>/artifacts/ 返回绝对路径", () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-score-"));
  try {
    mkdirSync(join(dir, "artifacts"), { recursive: true });
    writeFileSync(join(dir, "artifacts", "outline.md"), "x");
    writeFileSync(join(dir, "artifacts", "other.txt"), "y");
    const wf = bundleWorkspaceFiles(dir);
    const md = wf("*.md");
    assert.equal(md.length, 1);
    assert.ok(md[0].endsWith(join("artifacts", "outline.md")));
    assert.ok(md[0].startsWith("/")); // 绝对路径
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runScorers: 跑注册的测试 scorer,收集其 ScoreResult", async () => {
  // 注册一个测试 scorer:读 workspaceFiles 数量当分数
  registerScorer("test-count", {
    outputs: () => ["count"],
    build: () => async (ctx) => ({ value: { count: ctx.workspaceFiles("*.md").length } }),
  });
  const dir = mkdtempSync(join(tmpdir(), "bpb-score-"));
  try {
    mkdirSync(join(dir, "artifacts"), { recursive: true });
    writeFileSync(join(dir, "artifacts", "a.md"), "x");
    const bundle: RunBundle = { runDir: dir, runId: "t1-v", version: "v", events: [], signals: {} };
    const out = await runScorers(fakeTask(["test-count"]), bundle, "2026-06-17T00:00:00.000Z");
    assert.equal(out.taskId, "t1");
    assert.equal(out.results.length, 1);
    assert.equal(out.results[0].kind, "test-count");
    assert.deepEqual(out.results[0].value, { count: 1 });
    assert.equal(out.scoredAt, "2026-06-17T00:00:00.000Z");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runScorers: rubric-judge 桩返回 unscored 被如实记录(score.js 自注册内置 scorer)", async () => {
  // 不显式 import scorer/index——score.js 自身的副作用 import 已注册 rubric-judge
  const dir = mkdtempSync(join(tmpdir(), "bpb-score-"));
  try {
    mkdirSync(join(dir, "artifacts"), { recursive: true });
    const bundle: RunBundle = { runDir: dir, runId: "t1-v", version: "v", events: [], signals: {} };
    const out = await runScorers(fakeTask(["rubric-judge"]), bundle, "ts");
    assert.equal(out.results[0].kind, "rubric-judge");
    assert.equal(out.results[0].unscored, true);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
