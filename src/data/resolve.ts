/**
 * data/resolve.ts — 编排：查缓存命中→直接返回；未命中→按 scheme fetch 到临时文件→
 * 流式 sha256 校验→原子重命名进内容寻址缓存。校验失败删临时文件、不留半截缓存。
 */
import { mkdir, open, readFile, rename, rm, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { DataManifest, DatasetEntry, FetchProgress, ResolvedDataset } from "./types.js";
import { cachePathFor, isCached, verifySha256 } from "./cache.js";
import { DataFetchError, getFetcher, schemeOf } from "./fetch.js";

export interface ResolveOptions {
  onProgress?: (entry: DatasetEntry, progress: FetchProgress) => void;
}

const INFLIGHT = new Map<string, Promise<ResolvedDataset>>();
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function lockOwnerIsAlive(lockPath: string): Promise<boolean> {
  try {
    const pid = Number((await readFile(lockPath, "utf8")).trim());
    if (!Number.isInteger(pid) || pid <= 0) return false;
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

async function acquireCacheLock(dir: string): Promise<() => Promise<void>> {
  const path = join(dir, ".fetch.lock");
  const deadline = Date.now() + 5 * 60_000;
  while (Date.now() < deadline) {
    try {
      const handle = await open(path, "wx");
      await handle.writeFile(String(process.pid));
      return async () => { await handle.close().catch(() => {}); await rm(path, { force: true }); };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      // A second process can observe the file between open("wx") and the pid
      // write. Give a fresh unreadable lock a short grace period; once a pid
      // is readable, never evict a live owner just because a download is long.
      let stale = false;
      try {
        const ageMs = Date.now() - (await stat(path)).mtimeMs;
        stale = !(await lockOwnerIsAlive(path)) && ageMs > 2_000;
      } catch { /* lock disappeared; retry */ }
      if (stale) { await rm(path, { force: true }); continue; }
      await wait(250);
    }
  }
  throw new Error(`timed out waiting for dataset cache lock: ${dir}`);
}

/** resolve 一个数据集到本地缓存（命中则不下载）。 */
async function resolveDatasetOnce(entry: DatasetEntry, opts?: ResolveOptions): Promise<ResolvedDataset> {
  const finalPath = cachePathFor(entry.sha256);
  if (await isCached(entry.sha256)) {
    return { entry, path: finalPath, fetched: false };
  }
  const dir = dirname(finalPath);
  await mkdir(dir, { recursive: true });
  const release = await acquireCacheLock(dir);
  const partial = join(dir, ".partial");
  try {
    // Another process may have completed while this caller waited for the lock.
    if (await isCached(entry.sha256)) return { entry, path: finalPath, fetched: false };
    try {
      if ((await stat(partial)).size > entry.bytes) await rm(partial, { force: true });
    } catch { /* no partial */ }
    await getFetcher(schemeOf(entry.uri))({
      uri: entry.uri,
      destPath: partial,
      expectedBytes: entry.bytes,
      onProgress: (progress) => opts?.onProgress?.(entry, progress),
    });
    const actualBytes = (await stat(partial)).size;
    if (actualBytes !== entry.bytes) {
      throw new Error(`byte-size mismatch for ${entry.name}; expected ${entry.bytes}, got ${actualBytes}`);
    }
    if (!(await verifySha256(partial, entry.sha256))) {
      throw new Error(`sha256 mismatch for ${entry.name} (${entry.uri}); expected ${entry.sha256}`);
    }
    await rename(partial, finalPath);
    return { entry, path: finalPath, fetched: true };
  } catch (e) {
    const recoverable = e instanceof DataFetchError && ["network", "proxy", "disk"].includes(e.kind);
    if (!recoverable) await rm(partial, { force: true }).catch(() => {});
    if (e instanceof DataFetchError) {
      throw new DataFetchError(`${entry.name}: ${e.message}`, e.kind, e.status, { cause: e });
    }
    throw e;
  } finally {
    await release();
  }
}

/** resolve 一个数据集；同进程相同 hash 自动合并，跨进程用缓存锁协调。 */
export async function resolveDataset(entry: DatasetEntry, opts?: ResolveOptions): Promise<ResolvedDataset> {
  const current = INFLIGHT.get(entry.sha256);
  if (current) return current;
  const pending = resolveDatasetOnce(entry, opts).finally(() => INFLIGHT.delete(entry.sha256));
  INFLIGHT.set(entry.sha256, pending);
  return pending;
}

/** resolve 整个清单（顺序，避免并发把同一桶打爆；多任务共享缓存已去重）。 */
export async function resolveManifest(manifest: DataManifest, opts?: ResolveOptions): Promise<ResolvedDataset[]> {
  const out: ResolvedDataset[] = [];
  for (const entry of manifest.datasets) {
    out.push(await resolveDataset(entry, opts));
  }
  return out;
}
