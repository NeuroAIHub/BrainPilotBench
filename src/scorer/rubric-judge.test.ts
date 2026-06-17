import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { getScorerModule } from "./registry.js";
import { setJudgeClient, resetJudgeClient } from "./rubric.js";
import "./index.js"; // 注册 rubric-judge
import type { JudgeClient } from "../judge.js";
import type { Task } from "../task.js";

function surveyTask(dir: string): Task {
  return {
    meta: { id: "t", domain: "d", summary: "写综述提纲", expectedArtifacts: [{ workspace: "*.md" }], timeoutMin: 5, budgetTokens: 1, requires: {}, version: "test" },
    turns: [{ send: "hi" }], askUser: {},
    rubric: { dimensions: ["correctness", "presentation"] },
    scorers: [{ kind: "rubric-judge", rubric: "rubric.yaml" }], datasets: [], dir,
  };
}
function ctxWith(runDir: string, task: Task) {
  mkdirSync(join(runDir, "artifacts"), { recursive: true });
  writeFileSync(join(runDir, "artifacts", "outline.md"), "# 提纲\n注意力机制...");
  return {
    task, runDir, events: [], signals: {},
    workspaceFiles: (g: string) => (g === "*.md" ? [join(runDir, "artifacts", "outline.md")] : []),
  };
}

test("rubric-judge: 注入 fake client → 逐维聚合分", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-rj-"));
  const fake: JudgeClient = { complete: async () => '{"correctness": 4, "presentation": 3}' };
  setJudgeClient(fake);
  try {
    const t = surveyTask(dir);
    const scorer = getScorerModule("rubric-judge").build(t.scorers[0], t);
    const res = await scorer(ctxWith(dir, t) as any);
    assert.equal(res.unscored, undefined);
    assert.deepEqual(res.value, { correctness: 4, presentation: 3 });
    assert.ok(String(res.explanation).includes("votes"));
  } finally { resetJudgeClient(); rmSync(dir, { recursive: true, force: true }); }
});

test("rubric-judge: 无凭证(未注入且无 env)→ unscored", async () => {
  const prev = { k: process.env.ANTHROPIC_API_KEY, t: process.env.ANTHROPIC_AUTH_TOKEN, b: process.env.BPB_JUDGE_API_KEY };
  delete process.env.ANTHROPIC_API_KEY; delete process.env.ANTHROPIC_AUTH_TOKEN; delete process.env.BPB_JUDGE_API_KEY;
  resetJudgeClient();
  const dir = mkdtempSync(join(tmpdir(), "bpb-rj-"));
  try {
    const t = surveyTask(dir);
    const scorer = getScorerModule("rubric-judge").build(t.scorers[0], t);
    const res = await scorer(ctxWith(dir, t) as any);
    assert.equal(res.unscored, true);
    assert.ok(String(res.explanation).toLowerCase().includes("cred"));
  } finally {
    if (prev.k) process.env.ANTHROPIC_API_KEY = prev.k;
    if (prev.t) process.env.ANTHROPIC_AUTH_TOKEN = prev.t;
    if (prev.b) process.env.BPB_JUDGE_API_KEY = prev.b;
    rmSync(dir, { recursive: true, force: true });
  }
});

test("rubric-judge: 所有 judge 解析失败 → unscored", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-rj-"));
  setJudgeClient({ complete: async () => "I cannot produce a score." });
  try {
    const t = surveyTask(dir);
    const scorer = getScorerModule("rubric-judge").build(t.scorers[0], t);
    const res = await scorer(ctxWith(dir, t) as any);
    assert.equal(res.unscored, true);
  } finally { resetJudgeClient(); rmSync(dir, { recursive: true, force: true }); }
});

test("rubric-judge: 部分 judge 失败仍按成功票聚合", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-rj-"));
  let n = 0;
  setJudgeClient({ complete: async () => { n++; return n === 2 ? "garbage" : '{"correctness": 5, "presentation": 5}'; } });
  const prevVotes = process.env.BPB_JUDGE_VOTES;
  process.env.BPB_JUDGE_VOTES = "3";
  try {
    const t = surveyTask(dir);
    const scorer = getScorerModule("rubric-judge").build(t.scorers[0], t);
    const res = await scorer(ctxWith(dir, t) as any);
    assert.deepEqual(res.value, { correctness: 5, presentation: 5 }); // 2 张有效票
    assert.equal(res.unscored, undefined);
  } finally {
    resetJudgeClient();
    if (prevVotes === undefined) delete process.env.BPB_JUDGE_VOTES; else process.env.BPB_JUDGE_VOTES = prevVotes;
    rmSync(dir, { recursive: true, force: true });
  }
});
