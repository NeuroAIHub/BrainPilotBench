import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTask } from "./loader.js";

function makeTask(extraYaml: string): string {
  const dir = mkdtempSync(join(tmpdir(), "bpb-ver-"));
  writeFileSync(join(dir, "task.yaml"),
    "id: t\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: \"*.md\"\ntimeout_min: 5\nbudget_tokens: 1000\n" + extraYaml);
  mkdirSync(join(dir, "prompt"), { recursive: true });
  writeFileSync(join(dir, "prompt", "turns.yaml"), "- send: hi\n");
  return dir;
}

test("loadTask: 解析 version", () => {
  const dir = makeTask("version: \"0.2\"\n");
  try { assert.equal(loadTask(dir).meta.version, "0.2"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: 数字 version 字符串化", () => {
  const dir = makeTask("version: 3\n");
  try { assert.equal(loadTask(dir).meta.version, "3"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: 无 version → unversioned", () => {
  const dir = makeTask("");
  try { assert.equal(loadTask(dir).meta.version, "unversioned"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});
