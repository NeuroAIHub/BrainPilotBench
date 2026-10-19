import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, linkSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { Task } from "./task.js";
import type { DatasetEntry } from "./data/types.js";
import { cachePathFor } from "./data/cache.js";
import { assertEvaluatorLocation, evaluatorCacheRoot, evaluatorDatasets, fetchEvaluatorData, prepareEvaluatorData, readEvaluatorLock, verifyEvaluatorData, type EvaluatorLock } from "./evaluator.js";

const REVISION = "a".repeat(40);
const REPO = "BrainPilot-Bench/Tasks-Data-Private";
const hash = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");

function fixture() {
  // macOS may expose /var through /private/var; use real paths for overlap tests.
  const base = realpathSync(mkdtempSync(join(tmpdir(), "bpb-evaluator-test-")));
  const taskDir = join(base, "task");
  const publicCache = join(base, "public-cache");
  const privateCache = join(base, "private-cache");
  const bundle = join(base, "bundle");
  const workspace = join(base, "workspace");
  const output = join(base, "owner", "evaluator");
  for (const dir of [taskDir, publicCache, bundle, join(base, "owner"), join(workspace, ".bpb")])
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  mkdirSync(join(bundle, "artifacts"));
  writeFileSync(join(bundle, "meta.json"), "{}\n");
  writeFileSync(join(workspace, ".bpb", "TASK_PROMPT.md"), "fixture\n");
  const body = Buffer.from("held-out fixture bytes\n");
  const entry: DatasetEntry = {
    name: "evaluator__test__labels.bin", scope: "private",
    uri: `hf://datasets/${REPO}@${REVISION}/tasks/eeg/fixture-task/evaluator/test/labels.bin`,
    sha256: hash(body), bytes: body.length, format: "bin",
  };
  const rawPrivate: DatasetEntry = {
    name: "legacy-raw.bin", scope: "private", uri: "https://example.org/legacy-raw.bin",
    sha256: "b".repeat(64), bytes: 99,
  };
  const publicEntry: DatasetEntry = {
    name: "train.bin", scope: "public", uri: "https://example.org/public.bin",
    sha256: "c".repeat(64), bytes: 101,
  };
  const task = { meta: { id: "fixture-task", domain: "eeg" },
    datasets: [publicEntry, rawPrivate, entry], dir: taskDir } as Task;
  const lock: EvaluatorLock = {
    schema: "bpb-evaluator-data/1", task_id: task.meta.id, repo_id: REPO, revision: REVISION,
    files: [{ name: entry.name, path: "test/labels.bin", sha256: entry.sha256, bytes: entry.bytes }],
  };
  const writeLock = () => writeFileSync(join(taskDir, "evaluator.lock"), JSON.stringify(lock));
  const seedCache = () => {
    const source = cachePathFor(entry.sha256, privateCache);
    mkdirSync(join(privateCache, entry.sha256), { recursive: true, mode: 0o700 });
    writeFileSync(source, body, { mode: 0o600 });
    return source;
  };
  writeLock();
  return { base, taskDir, publicCache, privateCache, bundle, workspace, output, body,
    entry, rawPrivate, task, lock, writeLock, seedCache,
    cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

test("evaluator mapping selects only exact pinned private entries", () => {
  const f = fixture();
  try {
    assert.deepEqual(readEvaluatorLock(f.task), f.lock);
    assert.deepEqual(evaluatorDatasets(f.task), [f.entry]);
    const original = f.lock.files[0];
    for (const wrong of [
      { ...original, name: "train.bin" },
      { ...original, name: "legacy-raw.bin" },
      { ...original, sha256: "d".repeat(64) },
      { ...original, bytes: original.bytes + 1 },
    ]) {
      f.lock.files = [wrong]; f.writeLock();
      assert.throws(() => readEvaluatorLock(f.task), /does not match/);
    }
    f.lock.files = [original];
    f.task.datasets = f.task.datasets.map((entry) => entry.name === original.name
      ? { ...entry, uri: entry.uri.replace("/evaluator/", "/public/") } : entry);
    f.writeLock();
    assert.throws(() => readEvaluatorLock(f.task), /does not match/);
    f.task.datasets = f.task.datasets.map((entry) => entry.name === original.name
      ? { ...entry, uri: f.entry.uri.replace("/tasks/eeg/", "/tasks/psychology/") } : entry);
    assert.throws(() => readEvaluatorLock(f.task), /does not match/);
  } finally { f.cleanup(); }
});

test("evaluator lock rejects unsafe and overlapping paths", () => {
  const f = fixture();
  try {
    const original = f.lock.files[0];
    for (const path of ["../labels.bin", "/labels.bin", "test//labels.bin", "test/../labels.bin",
      "test\\labels.bin", ".bpb-evaluator.json"]) {
      f.lock.files = [{ ...original, path }]; f.writeLock();
      assert.throws(() => readEvaluatorLock(f.task), /unsafe|does not match/, path);
    }
    f.lock.files = [original, original]; f.writeLock();
    assert.throws(() => readEvaluatorLock(f.task), /duplicate or colliding/);
    f.lock.files = [original, { ...original, path: "test" }]; f.writeLock();
    assert.throws(() => readEvaluatorLock(f.task), /duplicate or colliding/);
  } finally { f.cleanup(); }
});

test("source-only task has no hosted evaluator package", () => {
  const f = fixture();
  try {
    rmSync(join(f.taskDir, "evaluator.lock"));
    assert.throws(() => readEvaluatorLock(f.task), /no hosted evaluator package/);
    assert.throws(() => evaluatorDatasets(f.task), /no hosted evaluator package/);
  } finally { f.cleanup(); }
});

test("private cache and evaluator output are separate from public and bundle locations", async () => {
  const f = fixture();
  const previous = process.env.BPB_CACHE_ROOT;
  try {
    process.env.BPB_CACHE_ROOT = f.publicCache;
    assert.throws(() => evaluatorCacheRoot(f.task, join(f.publicCache, "private")), /must be separate/);
    assert.throws(() => assertEvaluatorLocation(join(f.bundle, "evaluator"), f.task, [f.bundle]), /must be separate/);
    assert.throws(() => assertEvaluatorLocation(join(f.taskDir, "evaluator"), f.task), /must be separate/);
    await assert.rejects(prepareEvaluatorData(f.task, join(f.publicCache, "evaluator"),
      { cacheRoot: f.privateCache }), /must be separate/);
    assert.equal(evaluatorCacheRoot(f.task, f.privateCache), f.privateCache);
    const source = f.seedCache();
    const resolved = await fetchEvaluatorData(f.task, f.privateCache);
    assert.deepEqual(resolved.map((item) => item.path), [source]);
    assert.deepEqual(resolved.map((item) => item.entry.name), [f.entry.name]);
    assert.equal(existsSync(cachePathFor(f.entry.sha256, f.publicCache)), false);
    assert.equal(existsSync(cachePathFor(f.rawPrivate.sha256, f.privateCache)), false);
  } finally {
    if (previous === undefined) delete process.env.BPB_CACHE_ROOT;
    else process.env.BPB_CACHE_ROOT = previous;
    f.cleanup();
  }
});

test("prepare refuses evaluator output inside an existing bundle or Agent workspace", async () => {
  const f = fixture();
  try {
    f.seedCache();
    for (const parent of [f.bundle, f.workspace]) {
      const output = join(parent, "evaluator");
      await assert.rejects(prepareEvaluatorData(f.task, output,
        { cacheRoot: f.privateCache }), /bundle|workspace|separate/i);
      assert.equal(existsSync(output), false);
    }
  } finally { f.cleanup(); }
});

test("prepare copies verified bytes with private permissions and does not overwrite", async () => {
  const f = fixture();
  try {
    const source = f.seedCache();
    const result = await prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache });
    assert.equal(result.root, f.output);
    assert.equal(result.files, 1);
    assert.equal(result.bytes, f.body.length);
    assert.equal(result.revision, REVISION);
    const prepared = join(f.output, "test", "labels.bin");
    assert.deepEqual(readFileSync(prepared), f.body);
    assert.equal(hash(readFileSync(prepared)), f.entry.sha256);
    assert.equal(statSync(prepared).mode & 0o777, 0o600);
    assert.equal(statSync(f.output).mode & 0o777, 0o700);
    assert.equal(lstatSync(prepared).nlink, 1);
    assert.equal(statSync(source).mode & 0o777, 0o600);
    const marker = readFileSync(join(f.output, ".bpb-evaluator.json"), "utf8");
    assert.equal(JSON.parse(marker).revision, REVISION);
    assert.equal(JSON.parse(marker).evaluator_lock_sha256,
      hash(readFileSync(join(f.taskDir, "evaluator.lock"))));
    await verifyEvaluatorData(f.task, f.output, [f.bundle]);
    await prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache });
    assert.equal(readFileSync(join(f.output, ".bpb-evaluator.json"), "utf8"), marker);
    writeFileSync(prepared, "wrong bytes");
    await assert.rejects(prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache }), /verification/);
    assert.equal(readFileSync(prepared, "utf8"), "wrong bytes");
  } finally { f.cleanup(); }
});

test("existing output with wrong publication marker is rejected and preserved", async () => {
  const f = fixture();
  try {
    f.seedCache();
    await prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache });
    const markerPath = join(f.output, ".bpb-evaluator.json");
    const marker = JSON.parse(readFileSync(markerPath, "utf8")) as Record<string, unknown>;
    marker.evaluator_lock_sha256 = "0".repeat(64);
    const tampered = JSON.stringify(marker);
    writeFileSync(markerPath, tampered);
    await assert.rejects(verifyEvaluatorData(f.task, f.output), /marker|lock|manifest|publication/i);
    await assert.rejects(prepareEvaluatorData(f.task, f.output,
      { cacheRoot: f.privateCache }), /marker|lock|manifest|publication/i);
    assert.equal(readFileSync(markerPath, "utf8"), tampered);
    assert.deepEqual(readFileSync(join(f.output, "test", "labels.bin")), f.body);
  } finally { f.cleanup(); }
});

test("existing unrelated evaluator directory is never overwritten", async () => {
  const f = fixture();
  try {
    f.seedCache();
    mkdirSync(f.output);
    const sentinel = join(f.output, "owner-note.txt");
    writeFileSync(sentinel, "retain me\n");
    await assert.rejects(prepareEvaluatorData(f.task, f.output,
      { cacheRoot: f.privateCache }));
    assert.equal(readFileSync(sentinel, "utf8"), "retain me\n");
  } finally { f.cleanup(); }
});

test("prepare rejects bad cache bytes, symbolic links, and hard links", async () => {
  const f = fixture();
  try {
    const source = f.seedCache();
    writeFileSync(source, "wrong");
    await assert.rejects(prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache }), /verification/);
    assert.equal(existsSync(f.output), false);
    writeFileSync(source, f.body);
    const linked = join(f.base, "linked-private.bin");
    linkSync(source, linked);
    await assert.rejects(prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache }), /regular independent files/);
    rmSync(linked);
    rmSync(source);
    writeFileSync(linked, f.body);
    symlinkSync(linked, source);
    await assert.rejects(prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache }), /regular independent files/);
    assert.equal(existsSync(f.output), false);
  } finally { f.cleanup(); }
});

test("verify rejects symbolic and hard linked prepared files", async () => {
  const f = fixture();
  try {
    f.seedCache();
    await prepareEvaluatorData(f.task, f.output, { cacheRoot: f.privateCache });
    const prepared = join(f.output, "test", "labels.bin");
    const independent = join(f.base, "independent.bin");
    writeFileSync(independent, f.body);
    rmSync(prepared);
    symlinkSync(independent, prepared);
    await assert.rejects(verifyEvaluatorData(f.task, f.output), /regular independent files/);
    rmSync(prepared);
    linkSync(independent, prepared);
    await assert.rejects(verifyEvaluatorData(f.task, f.output), /regular independent files/);
  } finally { f.cleanup(); }
});
