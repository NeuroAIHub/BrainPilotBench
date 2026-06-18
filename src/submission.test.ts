import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadSubmissionMeta, verifySubmission } from "./submission.js";
import type { Task } from "./task.js";

function fakeTask(id: string, globs: string[]): Task {
  return {
    meta: { id, domain: "d", summary: "s", expectedArtifacts: globs.map((g) => ({ workspace: g })), timeoutMin: 5, budgetTokens: 1, requires: {}, version: "0.1", createdAt: "2026-01-01", category: "exec-data-analysis" },
    turns: [{ send: "hi" }], askUser: {}, rubric: { dimensions: ["x"] }, scorers: [{ kind: "exec-script" }], datasets: [], dir: `tasks/${id}`,
  };
}

/** 造一个 bundle 目录:meta(对象或 raw 字符串/undefined)+ artifacts 文件名列表 + 可选 events 行。 */
function makeBundle(opts: { meta?: unknown; metaRaw?: string; artifacts?: string[]; events?: string[] }): string {
  const dir = mkdtempSync(join(tmpdir(), "bpb-sub-"));
  if (opts.metaRaw !== undefined) writeFileSync(join(dir, "meta.json"), opts.metaRaw);
  else if (opts.meta !== undefined) writeFileSync(join(dir, "meta.json"), JSON.stringify(opts.meta));
  mkdirSync(join(dir, "artifacts"), { recursive: true });
  for (const f of opts.artifacts ?? []) writeFileSync(join(dir, "artifacts", f), "x");
  if (opts.events) writeFileSync(join(dir, "events.jsonl"), opts.events.join("\n"));
  return dir;
}

test("loadSubmissionMeta: 解析;不存在→null;坏 JSON→throw", () => {
  const ok = makeBundle({ meta: { taskId: "t", agent: "a@1" } });
  try { assert.deepEqual(loadSubmissionMeta(ok), { taskId: "t", agent: "a@1" }); } finally { rmSync(ok, { recursive: true, force: true }); }
  const none = mkdtempSync(join(tmpdir(), "bpb-sub-"));
  try { assert.equal(loadSubmissionMeta(none), null); } finally { rmSync(none, { recursive: true, force: true }); }
  const bad = makeBundle({ metaRaw: "not json{" });
  try { assert.throws(() => loadSubmissionMeta(bad), /meta\.json|解析/i); } finally { rmSync(bad, { recursive: true, force: true }); }
});

test("verifySubmission: 好 bundle(产物满足 glob)→ 无 error", () => {
  const dir = makeBundle({ meta: { taskId: "t", agent: "a@1" }, artifacts: ["results.csv"] });
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv"]), dir);
    assert.equal(issues.filter((i) => i.level === "error").length, 0, JSON.stringify(issues));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verifySubmission: 缺 meta.json → error", () => {
  const dir = makeBundle({ artifacts: ["results.csv"] }); // 无 meta
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv"]), dir);
    assert.ok(issues.some((i) => i.level === "error" && /meta/i.test(i.msg)));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verifySubmission: meta.taskId 与任务不符 → error", () => {
  const dir = makeBundle({ meta: { taskId: "other", agent: "a@1" }, artifacts: ["results.csv"] });
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv"]), dir);
    assert.ok(issues.some((i) => i.level === "error" && /taskId/i.test(i.msg)));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verifySubmission: 缺 agent → error", () => {
  const dir = makeBundle({ meta: { taskId: "t" }, artifacts: ["results.csv"] });
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv"]), dir);
    assert.ok(issues.some((i) => i.level === "error" && /agent/i.test(i.msg)));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verifySubmission: 缺某 expected_artifact → error 含该 glob", () => {
  const dir = makeBundle({ meta: { taskId: "t", agent: "a@1" }, artifacts: ["results.csv"] }); // 缺 *.png
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv", "*.png"]), dir);
    assert.ok(issues.some((i) => i.level === "error" && /\*\.png/.test(i.msg)));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verifySubmission: 坏 events.jsonl 行 → warn 非 error", () => {
  const dir = makeBundle({ meta: { taskId: "t", agent: "a@1" }, artifacts: ["results.csv"], events: ['{"ok":1}', "not json"] });
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv"]), dir);
    assert.equal(issues.filter((i) => i.level === "error").length, 0, JSON.stringify(issues));
    assert.ok(issues.some((i) => i.level === "warn" && /events/i.test(i.msg)));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verifySubmission: 匹配 glob 的是目录而非文件 → 不算满足(防假性通过)", () => {
  const dir = makeBundle({ meta: { taskId: "t", agent: "a@1" } });
  mkdirSync(join(dir, "artifacts", "notreally.csv"), { recursive: true }); // 目录名匹配 *.csv,但无真 CSV 文件
  writeFileSync(join(dir, "artifacts", "notreally.csv", "inside.txt"), "x");
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv"]), dir);
    assert.ok(issues.some((i) => i.level === "error" && /\*\.csv/.test(i.msg)), JSON.stringify(issues));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("verifySubmission: notes 含省略号(..)不应误判为路径穿越", () => {
  const dir = makeBundle({ meta: { taskId: "t", agent: "a@1", notes: "see fig 2... results are great" }, artifacts: ["results.csv"] });
  try {
    const issues = verifySubmission(fakeTask("t", ["*.csv"]), dir);
    assert.equal(issues.filter((i) => i.level === "error").length, 0, JSON.stringify(issues));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
