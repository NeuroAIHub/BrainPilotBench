import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { Task } from "./task.js";
import { evaluatorDatasets, prepareEvaluatorData, readEvaluatorLock, verifyEvaluatorData, type EvaluatorLock } from "./evaluator.js";
import { cachePathFor } from "./data/cache.js";
import { assertAgentDataBoundary } from "./workflow.js";

function fixture() {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "bpb-source-evaluator-")));
  const taskDir = join(root, "task");
  mkdirSync(taskDir);
  const bytes = Buffer.from("fixture, not research data\n");
  const sha = createHash("sha256").update(bytes).digest("hex");
  const revision = "d".repeat(64);
  const entry = { name: "owner/test.bin", scope: "private" as const, sha256: sha, bytes: bytes.length,
    uri: `local://tasks/animal-behavior/calms21-example/${revision}/evaluator/owner/test.bin`, format: "bin" };
  const task = { meta: { id: "calms21-example", domain: "animal-behavior" }, dir: taskDir, datasets: [entry] } as Task;
  const lock: EvaluatorLock = { schema: "bpb-evaluator-source/1", task_id: "calms21-example",
    repo_id: "local-prepared", revision, files: [{ name: entry.name, path: "owner/test.bin", sha256: sha, bytes: bytes.length }] };
  const save = () => writeFileSync(join(taskDir, "evaluator.lock"), JSON.stringify(lock));
  save();
  return { root, task, lock, entry, bytes, save, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

test("source-prepared evaluator locks bind exact local private paths without claiming HF publication", () => {
  const f = fixture();
  try {
    assert.deepEqual(readEvaluatorLock(f.task), f.lock);
    assert.deepEqual(evaluatorDatasets(f.task), [f.entry]);
    for (const uri of [f.entry.uri.replace("/evaluator/", "/public/"),
      f.entry.uri.replace("calms21-example/", "other-task/"), "https://example.org/test.bin"]) {
      f.task.datasets = [{ ...f.entry, uri }];
      assert.throws(() => readEvaluatorLock(f.task), /does not match/);
    }
    f.task.datasets = [f.entry];
    f.lock.repo_id = "BrainPilot-Bench/Tasks-Data-Private";
    f.save();
    assert.throws(() => readEvaluatorLock(f.task), /identity/);
    f.lock.repo_id = "local-prepared";
    f.lock.revision = "a".repeat(40);
    f.save();
    assert.throws(() => readEvaluatorLock(f.task), /identity/);
  } finally { f.cleanup(); }
});

test("source-prepared files use the same owner-only preparation and tamper checks", async () => {
  const f = fixture();
  try {
    const cache = join(f.root, "owner-cache");
    const cached = cachePathFor(f.entry.sha256, cache);
    mkdirSync(join(cache, f.entry.sha256), { recursive: true, mode: 0o700 });
    writeFileSync(cached, f.bytes, { mode: 0o600 });
    const output = join(f.root, "owner", "evaluator");
    const result = await prepareEvaluatorData(f.task, output, { cacheRoot: cache });
    assert.equal(result.revision, f.lock.revision);
    assert.deepEqual(readFileSync(join(output, "owner/test.bin")), f.bytes);
    await verifyEvaluatorData(f.task, output);
    writeFileSync(join(output, "owner/test.bin"), "changed");
    await assert.rejects(verifyEvaluatorData(f.task, output), /verification/);
  } finally { f.cleanup(); }
});

test("only explicitly reviewed, byte-identical public objects can share an Agent cache", () => {
  const f = fixture();
  const previous = process.env.BPB_CACHE_ROOT;
  try {
    const cache = join(f.root, "public-cache");
    process.env.BPB_CACHE_ROOT = cache;
    mkdirSync(join(cache, f.entry.sha256), { recursive: true });
    writeFileSync(cachePathFor(f.entry.sha256, cache), f.bytes);
    assert.throws(() => assertAgentDataBoundary(f.task), /private evaluator data exists/);
    f.lock.public_equivalent_sha256 = [f.entry.sha256];
    f.save();
    assert.throws(() => readEvaluatorLock(f.task), /public-equivalent/);
    f.task.datasets.push({ ...f.entry, name: "shared-metadata", scope: "public",
      uri: f.entry.uri.replace("/evaluator/", "/public/") });
    assertAgentDataBoundary(f.task);
    f.lock.public_equivalent_sha256 = ["0".repeat(64)];
    f.save();
    assert.throws(() => assertAgentDataBoundary(f.task), /public-equivalent/);
  } finally {
    if (previous === undefined) delete process.env.BPB_CACHE_ROOT;
    else process.env.BPB_CACHE_ROOT = previous;
    f.cleanup();
  }
});
