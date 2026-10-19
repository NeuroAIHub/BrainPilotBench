import test from "node:test";
import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { assertNoEvaluatorWorkspace } from "./workflow.js";
import { writePrivateScores } from "./private-score.js";
import type { RunScores } from "./score.js";

test("Agent preparation rejects evaluator roots, descendants, parent mounts, and links", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "bpb-owner-isolation-")));
  try {
    for (const marker of [".bpb-evaluator.json", ".bpb-preparing.json", ".bpb-private-cache.json", "PRIVATE_PREPARED.json"]) {
      const owner = join(root, marker.replaceAll(".", "_"));
      const research = join(root, "research");
      mkdirSync(owner); mkdirSync(research, { recursive: true });
      writeFileSync(join(owner, marker), "{}");
      writeFileSync(join(owner, "private.bin"), "private fixture");
      assert.throws(() => assertNoEvaluatorWorkspace(owner), /evaluator data/);
      assert.throws(() => assertNoEvaluatorWorkspace(join(owner, "child")), /evaluator data/);
      assert.throws(() => assertNoEvaluatorWorkspace(root), /evaluator data/);
      symlinkSync(join(owner, "private.bin"), join(research, "hidden.bin"));
      assert.throws(() => assertNoEvaluatorWorkspace(research), /evaluator data/);
      rmSync(join(research, "hidden.bin"));
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("private score writer refuses dangling links and publishes owner-only JSON", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "bpb-owner-output-")));
  try {
    const output = join(root, "scores.private.json"), other = join(root, "outside.json");
    const scores = { taskId: "fixture", state: "scored", results: [] } as unknown as RunScores;
    symlinkSync(other, output);
    assert.throws(() => writePrivateScores(output, scores), /regular independent file/);
    assert.equal(existsSync(other), false);
    unlinkSync(output);
    writeFileSync(output, "old", { mode: 0o644 }); chmodSync(output, 0o644);
    writePrivateScores(output, scores);
    assert.equal(statSync(output).mode & 0o777, 0o600);
    assert.deepEqual(JSON.parse(readFileSync(output, "utf8")), scores);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
