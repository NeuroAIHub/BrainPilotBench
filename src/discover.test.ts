import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { discoverTaskDirs } from "./discover.js";

function scratch(): string {
  return mkdtempSync(join(tmpdir(), "bpb-disc-"));
}
function task(root: string, rel: string): void {
  const dir = join(root, rel);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "task.yaml"), "id: x\n");
}

test("discoverTaskDirs: 找到嵌套任务", () => {
  const root = scratch();
  try {
    task(root, "neuro/survey-attention");
    task(root, "top-level");
    const found = discoverTaskDirs([root]).map((d) => d.slice(root.length + 1)).sort();
    assert.deepEqual(found, ["neuro/survey-attention", "top-level"]);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("discoverTaskDirs: 下划线目录默认排除,includeExamples 纳入", () => {
  const root = scratch();
  try {
    task(root, "real");
    task(root, "_example/exec-task");
    const def = discoverTaskDirs([root]).map((d) => d.slice(root.length + 1)).sort();
    assert.deepEqual(def, ["real"]);
    const all = discoverTaskDirs([root], { includeExamples: true }).map((d) => d.slice(root.length + 1)).sort();
    assert.deepEqual(all, ["_example/exec-task", "real"]);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("discoverTaskDirs: 不下钻进任务内部(checks/ 不算任务)", () => {
  const root = scratch();
  try {
    task(root, "t1");
    mkdirSync(join(root, "t1", "checks"), { recursive: true }); // 任务内子目录,无 task.yaml
    const found = discoverTaskDirs([root]).map((d) => d.slice(root.length + 1));
    assert.deepEqual(found, ["t1"]); // 只 t1,不会因下钻产生重复或误判
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("discoverTaskDirs: 多根合并去重", () => {
  const a = scratch(), b = scratch();
  try {
    task(a, "ta");
    task(b, "tb");
    const found = discoverTaskDirs([a, b]);
    assert.equal(found.length, 2);
    assert.ok(found.some((d) => d.endsWith("/ta")));
    assert.ok(found.some((d) => d.endsWith("/tb")));
  } finally { rmSync(a, { recursive: true, force: true }); rmSync(b, { recursive: true, force: true }); }
});

test("discoverTaskDirs: 跳过 node_modules 与 dot 目录", () => {
  const root = scratch();
  try {
    task(root, "real");
    task(root, "node_modules/pkg");
    task(root, ".hidden/t");
    const found = discoverTaskDirs([root]).map((d) => d.slice(root.length + 1));
    assert.deepEqual(found, ["real"]);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("discoverTaskDirs: 不存在的根 → 跳过不抛", () => {
  const root = scratch();
  try {
    task(root, "real");
    const found = discoverTaskDirs([root, join(root, "nope-not-here")]);
    assert.equal(found.length, 1);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
