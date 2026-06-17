import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadRunScores, buildLeaderboard } from "./leaderboard.js";
import type { CategoryRegistry } from "./categories.js";

const REG: CategoryRegistry = {
  "survey-writing": { metrics: ["correctness", "completeness"] },
  "exec-data-analysis": { metrics: ["rows_ok"] },
};
const catOf = (id: string) => (id === "ex" ? "exec-data-analysis" : "survey-writing");

test("buildLeaderboard: rubric 归一 + 跨 run 中位数 + coverage", () => {
  const runs = [
    { taskId: "t1", runId: "t1-v1-a", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", value: { correctness: 5, completeness: 3 } }] },
    { taskId: "t1", runId: "t1-v1-b", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", value: { correctness: 3, completeness: 3 } }] },
  ] as any;
  const tables = buildLeaderboard(runs, catOf, REG);
  const sw = tables.find((t) => t.category === "survey-writing")!;
  assert.deepEqual(sw.metrics, ["correctness", "completeness"]);
  const row = sw.rows.find((r) => r.taskId === "t1" && r.version === "v1")!;
  const corr = row.cells.find((c) => c.metric === "correctness")!;
  // correctness: 5→1.0, 3→0.5;中位数 0.75
  assert.equal(corr.value, 0.75);
  assert.deepEqual(corr.coverage, { scored: 2, total: 2 });
  const comp = row.cells.find((c) => c.metric === "completeness")!;
  assert.equal(comp.value, 0.5); // 3→0.5, 3→0.5 → 0.5
});

test("buildLeaderboard: unscored 排除出聚合,≠0", () => {
  const runs = [
    { taskId: "t1", runId: "a", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", value: { correctness: 5, completeness: 5 } }] },
    { taskId: "t1", runId: "b", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", unscored: true, value: { correctness: 0, completeness: 0 } }] },
  ] as any;
  const sw = buildLeaderboard(runs, catOf, REG).find((t) => t.category === "survey-writing")!;
  const corr = sw.rows[0].cells.find((c) => c.metric === "correctness")!;
  assert.equal(corr.value, 1); // 只算 scored 那条(5→1);unscored 不拉低成 0.5
  assert.deepEqual(corr.coverage, { scored: 1, total: 2 });
});

test("buildLeaderboard: exec 指标透传(不归一),not-applicable 不成列", () => {
  const runs = [
    { taskId: "ex", runId: "a", version: "v1", scoredAt: "x", results: [{ kind: "exec-script", value: { rows: 3, rows_ok: 1 } }] },
  ] as any;
  const ex = buildLeaderboard(runs, catOf, REG).find((t) => t.category === "exec-data-analysis")!;
  assert.deepEqual(ex.metrics, ["rows_ok"]); // rows 不在必备集 → 不成列
  const cell = ex.rows[0].cells.find((c) => c.metric === "rows_ok")!;
  assert.equal(cell.value, 1); // 透传,不归一
});

test("buildLeaderboard: 全 unscored 格子 value=null(不是 0)", () => {
  const runs = [
    { taskId: "t1", runId: "a", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", unscored: true, value: { correctness: 0, completeness: 0 } }] },
  ] as any;
  const sw = buildLeaderboard(runs, catOf, REG).find((t) => t.category === "survey-writing")!;
  const corr = sw.rows[0].cells.find((c) => c.metric === "correctness")!;
  assert.equal(corr.value, null);
  assert.deepEqual(corr.coverage, { scored: 0, total: 1 });
});

test("loadRunScores: 读 runs/*/scores.json,坏的跳过", () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-runs-"));
  try {
    mkdirSync(join(dir, "r1"), { recursive: true });
    writeFileSync(join(dir, "r1", "scores.json"), JSON.stringify({ taskId: "t1", runId: "r1", version: "v1", scoredAt: "x", results: [] }));
    mkdirSync(join(dir, "r2"), { recursive: true });
    writeFileSync(join(dir, "r2", "scores.json"), "not json");
    mkdirSync(join(dir, "r3"), { recursive: true }); // 无 scores.json
    const runs = loadRunScores(dir);
    assert.equal(runs.length, 1);
    assert.equal(runs[0].taskId, "t1");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
