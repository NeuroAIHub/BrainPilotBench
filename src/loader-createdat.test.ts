import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTask } from "./loader.js";

function makeTask(extraYaml: string): string {
  const dir = mkdtempSync(join(tmpdir(), "bpb-cat-"));
  writeFileSync(join(dir, "task.yaml"),
    "id: t\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: \"*.md\"\ntimeout_min: 5\nbudget_tokens: 1000\n" + extraYaml);
  mkdirSync(join(dir, "prompt"), { recursive: true });
  writeFileSync(join(dir, "prompt", "turns.yaml"), "- send: hi\n");
  return dir;
}

test("loadTask: 解析 created_at(不带引号的日期保持 YYYY-MM-DD)", () => {
  const dir = makeTask("created_at: 2026-06-15\n");
  try { assert.equal(loadTask(dir).meta.createdAt, "2026-06-15"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: 无 created_at → undefined", () => {
  const dir = makeTask("");
  try { assert.equal(loadTask(dir).meta.createdAt, undefined); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});
