import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildRelease, addRelease, loadRegistry, saveRegistry, verifyRegistry } from "./registry.js";
import type { Registry } from "./registry.js";
import type { Task } from "./task.js";

function fakeTask(id: string, version: string, category: string, createdAt?: string): Task {
  return {
    meta: { id, domain: "d", summary: "s", expectedArtifacts: [{ workspace: "*.md" }], timeoutMin: 5, budgetTokens: 1, requires: {}, version, createdAt, category },
    turns: [{ send: "hi" }], askUser: {}, rubric: { dimensions: ["x"] }, scorers: [{ kind: "rubric-judge" }], datasets: [], dir: `tasks/${id}`,
  };
}

test("buildRelease: Task → FrozenTask 投影", () => {
  const rel = buildRelease("BrainPilotBench-v1", "abc123", "tested/x", "2026-06-18", [
    fakeTask("t1", "0.1", "survey-writing", "2026-06-15"),
    fakeTask("t2", "0.2", "exec-data-analysis", "2026-06-16"),
  ]);
  assert.equal(rel.name, "BrainPilotBench-v1");
  assert.equal(rel.commit, "abc123");
  assert.equal(rel.ref, "tested/x");
  assert.equal(rel.frozenAt, "2026-06-18");
  assert.deepEqual(rel.tasks, [
    { id: "t1", version: "0.1", category: "survey-writing", createdAt: "2026-06-15" },
    { id: "t2", version: "0.2", category: "exec-data-analysis", createdAt: "2026-06-16" },
  ]);
});

test("addRelease: 追加;重名 throw(不可变)", () => {
  let reg: Registry = { releases: [] };
  const r1 = buildRelease("v1", "c1", undefined, "2026-06-18", [fakeTask("t1", "0.1", "survey-writing", "2026-06-15")]);
  reg = addRelease(reg, r1);
  assert.equal(reg.releases.length, 1);
  const r2 = buildRelease("v2", "c2", undefined, "2026-06-18", [fakeTask("t1", "0.2", "survey-writing", "2026-06-15")]);
  reg = addRelease(reg, r2);
  assert.equal(reg.releases.length, 2);
  // 重名拒绝
  assert.throws(() => addRelease(reg, buildRelease("v1", "c3", undefined, "2026-06-18", [])), /已存在|exists|不可变|immutable/i);
});

test("verifyRegistry: 全绿 → ok", () => {
  const reg: Registry = { releases: [buildRelease("v1", "c1", undefined, "2026-06-18", [fakeTask("t1", "0.1", "survey-writing", "2026-06-15")])] };
  const results = verifyRegistry(reg, {
    taskById: new Map([["t1", fakeTask("t1", "0.1", "survey-writing", "2026-06-15")]]),
    commitExists: () => true,
    categoryExists: () => true,
  });
  assert.equal(results.length, 1);
  assert.equal(results[0].ok, true);
  assert.deepEqual(results[0].problems, []);
});

test("verifyRegistry: 任务消失 → problem", () => {
  const reg: Registry = { releases: [buildRelease("v1", "c1", undefined, "2026-06-18", [fakeTask("t1", "0.1", "survey-writing", "2026-06-15")])] };
  const results = verifyRegistry(reg, { taskById: new Map(), commitExists: () => true, categoryExists: () => true });
  assert.equal(results[0].ok, false);
  assert.ok(results[0].problems.some((p) => /t1/.test(p) && /missing|缺|不存在/i.test(p)));
});

test("verifyRegistry: version 漂移 → problem", () => {
  const reg: Registry = { releases: [buildRelease("v1", "c1", undefined, "2026-06-18", [fakeTask("t1", "0.1", "survey-writing", "2026-06-15")])] };
  const results = verifyRegistry(reg, {
    taskById: new Map([["t1", fakeTask("t1", "0.9", "survey-writing", "2026-06-15")]]), // 现版本 0.9 ≠ 冻结 0.1
    commitExists: () => true, categoryExists: () => true,
  });
  assert.equal(results[0].ok, false);
  assert.ok(results[0].problems.some((p) => /version|版本/i.test(p)));
});

test("verifyRegistry: commit 不可达 → problem", () => {
  const reg: Registry = { releases: [buildRelease("v1", "deadbeef", undefined, "2026-06-18", [fakeTask("t1", "0.1", "survey-writing", "2026-06-15")])] };
  const results = verifyRegistry(reg, {
    taskById: new Map([["t1", fakeTask("t1", "0.1", "survey-writing", "2026-06-15")]]),
    commitExists: () => false, categoryExists: () => true,
  });
  assert.equal(results[0].ok, false);
  assert.ok(results[0].problems.some((p) => /commit/i.test(p)));
});

test("verifyRegistry: 未知 category → problem", () => {
  const reg: Registry = { releases: [buildRelease("v1", "c1", undefined, "2026-06-18", [fakeTask("t1", "0.1", "no-such", "2026-06-15")])] };
  const results = verifyRegistry(reg, {
    taskById: new Map([["t1", fakeTask("t1", "0.1", "no-such", "2026-06-15")]]),
    commitExists: () => true, categoryExists: () => false,
  });
  assert.equal(results[0].ok, false);
  assert.ok(results[0].problems.some((p) => /category|类别/i.test(p)));
});

test("loadRegistry/saveRegistry: round-trip;不存在→空", () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-reg-"));
  try {
    const p = join(dir, "registry.json");
    assert.deepEqual(loadRegistry(p), { releases: [] }); // 不存在
    const reg = addRelease({ releases: [] }, buildRelease("v1", "c1", "tested/x", "2026-06-18", [fakeTask("t1", "0.1", "survey-writing", "2026-06-15")]));
    saveRegistry(p, reg);
    assert.deepEqual(loadRegistry(p), reg);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
