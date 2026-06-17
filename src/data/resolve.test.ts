import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { resolveDataset, resolveManifest } from "./resolve.js";
import { cachePathFor } from "./cache.js";
import type { DatasetEntry } from "./types.js";

function withTmpXdg<T>(fn: (dir: string) => Promise<T>): Promise<T> {
  const prev = process.env.XDG_CACHE_HOME;
  const dir = mkdtempSync(join(tmpdir(), "bpb-resolve-"));
  process.env.XDG_CACHE_HOME = dir;
  return fn(dir).finally(() => {
    rmSync(dir, { recursive: true, force: true });
    if (prev === undefined) delete process.env.XDG_CACHE_HOME; else process.env.XDG_CACHE_HOME = prev;
  });
}

test("resolveDataset: 未命中→file fetch→校验→落缓存；再次→命中", async () => {
  await withTmpXdg(async (dir) => {
    const body = "neuro-payload";
    const sha = createHash("sha256").update(body).digest("hex");
    const src = join(dir, "src.bin");
    writeFileSync(src, body);
    const entry: DatasetEntry = { name: "ds", uri: "file://" + src, sha256: sha, bytes: body.length };

    const r1 = await resolveDataset(entry);
    assert.equal(r1.fetched, true);
    assert.equal(r1.path, cachePathFor(sha));
    assert.ok(existsSync(r1.path));

    const r2 = await resolveDataset(entry);
    assert.equal(r2.fetched, false); // 命中
    assert.equal(r2.path, r1.path);
  });
});

test("resolveDataset: sha256 不匹配→报错且不留半截缓存", async () => {
  await withTmpXdg(async (dir) => {
    const body = "real-body";
    const wrongSha = "c".repeat(64);
    const src = join(dir, "s.bin");
    writeFileSync(src, body);
    const entry: DatasetEntry = { name: "ds", uri: "file://" + src, sha256: wrongSha, bytes: body.length };
    await assert.rejects(() => resolveDataset(entry), /sha256 mismatch/);
    assert.equal(existsSync(cachePathFor(wrongSha)), false); // 没留下损坏缓存
  });
});

test("resolveManifest: 解析多条并全部 resolve", async () => {
  await withTmpXdg(async (dir) => {
    const mk = (name: string, body: string) => {
      const sha = createHash("sha256").update(body).digest("hex");
      const src = join(dir, name + ".bin");
      writeFileSync(src, body);
      return { name, uri: "file://" + src, sha256: sha, bytes: body.length };
    };
    const manifest = { datasets: [mk("a", "aaa"), mk("b", "bbbb")] };
    const out = await resolveManifest(manifest);
    assert.equal(out.length, 2);
    assert.ok(out.every((r) => existsSync(r.path)));
  });
});
