/**
 * data/resolve.ts — 编排：查缓存命中→直接返回；未命中→按 scheme fetch 到临时文件→
 * 流式 sha256 校验→原子重命名进内容寻址缓存。校验失败删临时文件、不留半截缓存。
 */
import { mkdir, rename, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { DataManifest, DatasetEntry, ResolvedDataset } from "./types.js";
import { cachePathFor, isCached, verifySha256 } from "./cache.js";
import { getFetcher, schemeOf } from "./fetch.js";

/** resolve 一个数据集到本地缓存（命中则不下载）。 */
export async function resolveDataset(entry: DatasetEntry): Promise<ResolvedDataset> {
  const finalPath = cachePathFor(entry.sha256);
  if (await isCached(entry.sha256)) {
    return { entry, path: finalPath, fetched: false };
  }
  const dir = dirname(finalPath);
  await mkdir(dir, { recursive: true });
  const tmp = join(dir, `.tmp-${process.pid}-${entry.name}`);
  try {
    await getFetcher(schemeOf(entry.uri))({ uri: entry.uri, destPath: tmp });
    if (!(await verifySha256(tmp, entry.sha256))) {
      throw new Error(`sha256 mismatch for ${entry.name} (${entry.uri}); expected ${entry.sha256}`);
    }
    await rename(tmp, finalPath);
    return { entry, path: finalPath, fetched: true };
  } catch (e) {
    await rm(tmp, { force: true }).catch(() => {});
    throw e;
  }
}

/** resolve 整个清单（顺序，避免并发把同一桶打爆；多任务共享缓存已去重）。 */
export async function resolveManifest(manifest: DataManifest): Promise<ResolvedDataset[]> {
  const out: ResolvedDataset[] = [];
  for (const entry of manifest.datasets) {
    out.push(await resolveDataset(entry));
  }
  return out;
}
