import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { cacheDir, cachePathFor, isCached, verifySha256 } from "./cache.js";

test("cacheDir: 尊重 XDG_CACHE_HOME，回落 ~/.cache", () => {
  const prev = process.env.XDG_CACHE_HOME;
  try {
    process.env.XDG_CACHE_HOME = "/tmp/xdg-test";
    assert.equal(cacheDir(), "/tmp/xdg-test/brainpilot-bench");
  } finally {
    if (prev === undefined) delete process.env.XDG_CACHE_HOME; else process.env.XDG_CACHE_HOME = prev;
  }
});

test("cachePathFor: 内容寻址路径含 sha256", () => {
  const sha = "a".repeat(64);
  const p = cachePathFor(sha);
  assert.ok(p.includes("brainpilot-bench"));
  assert.ok(p.endsWith(join(sha, "data")));
});

test("verifySha256: 正确内容通过、篡改内容拒绝", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-cache-"));
  try {
    const f = join(dir, "blob");
    const body = "hello-dataset";
    writeFileSync(f, body);
    const good = createHash("sha256").update(body).digest("hex");
    assert.equal(await verifySha256(f, good), true);
    assert.equal(await verifySha256(f, "b".repeat(64)), false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("isCached: 仅当文件存在且 sha256 匹配才算命中", async () => {
  const prev = process.env.XDG_CACHE_HOME;
  const dir = mkdtempSync(join(tmpdir(), "bpb-xdg-"));
  try {
    process.env.XDG_CACHE_HOME = dir;
    const body = "cached-body";
    const sha = createHash("sha256").update(body).digest("hex");
    assert.equal(await isCached(sha), false); // 还没写
    const p = cachePathFor(sha);
    const { mkdirSync } = await import("node:fs");
    mkdirSync(join(p, ".."), { recursive: true });
    writeFileSync(p, body);
    assert.equal(await isCached(sha), true);  // 写了且匹配
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (prev === undefined) delete process.env.XDG_CACHE_HOME; else process.env.XDG_CACHE_HOME = prev;
  }
});
