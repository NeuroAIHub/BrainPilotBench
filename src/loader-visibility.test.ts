import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTask } from "./loader.js";

function makeTask(extraYaml: string): string {
  const dir = mkdtempSync(join(tmpdir(), "bpb-vis-"));
  writeFileSync(join(dir, "task.yaml"),
    "id: t\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: \"*.md\"\ntimeout_min: 5\nbudget_tokens: 1000\n" + extraYaml);
  mkdirSync(join(dir, "prompt"), { recursive: true });
  writeFileSync(join(dir, "prompt", "turns.yaml"), "- send: hi\n");
  return dir;
}

test("loadTask: visibility heldout", () => {
  const dir = makeTask("visibility: heldout\n");
  try { assert.equal(loadTask(dir).meta.visibility, "heldout"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: visibility public", () => {
  const dir = makeTask("visibility: public\n");
  try { assert.equal(loadTask(dir).meta.visibility, "public"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: 无 visibility → public(缺省)", () => {
  const dir = makeTask("");
  try { assert.equal(loadTask(dir).meta.visibility, "public"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: 非法 visibility → 规范化回落 public(校验交 validate)", () => {
  const dir = makeTask("visibility: bogus\n");
  try { assert.equal(loadTask(dir).meta.visibility, "public"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});
