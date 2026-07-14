import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTask } from "./loader.js";

function makeTask(withDataLock: boolean): string {
  const dir = mkdtempSync(join(tmpdir(), "bpb-task-"));
  writeFileSync(join(dir, "task.yaml"),
    "id: t-data\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: \"*.md\"\ntimeout_min: 5\nbudget_tokens: 1000\n");
  mkdirSync(join(dir, "prompt"), { recursive: true });
  writeFileSync(join(dir, "prompt", "turns.yaml"), "- send: hi\n");
  if (withDataLock) {
    writeFileSync(join(dir, "data.lock"),
      "datasets:\n  - name: ds-a\n    uri: https://example.org/a.parquet\n    sha256: " + "a".repeat(64) + "\n    bytes: 42\n    format: parquet\n    scope: private\n");
  }
  return dir;
}

test("loadTask: 有 data.lock → task.datasets 被解析填充", () => {
  const dir = makeTask(true);
  try {
    const t = loadTask(dir);
    assert.equal(t.datasets.length, 1);
    assert.equal(t.datasets[0].name, "ds-a");
    assert.equal(t.datasets[0].uri, "https://example.org/a.parquet");
    assert.equal(t.datasets[0].bytes, 42);
    assert.equal(t.datasets[0].scope, "private");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("loadTask: 无 data.lock → task.datasets 为空数组", () => {
  const dir = makeTask(false);
  try {
    assert.deepEqual(loadTask(dir).datasets, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("loadTask: fixture task without data.lock still has datasets=[]", () => {
  const fixture = join(process.cwd(), "test", "fixtures", "rubric-task");
  assert.deepEqual(loadTask(fixture).datasets, []);
});
