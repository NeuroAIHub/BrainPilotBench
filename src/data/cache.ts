/**
 * data/cache.ts — 内容寻址缓存：$XDG_CACHE_HOME/brainpilot-bench/<sha256>/data。
 * 按 sha256 寻址 → 多任务/多次 run 天然去重；内容变了 sha 变了缓存自动失效。
 */
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

/** 缓存根目录：尊重 XDG_CACHE_HOME，否则 ~/.cache。 */
export function cacheDir(): string {
  const base = process.env.XDG_CACHE_HOME || join(homedir(), ".cache");
  return join(base, "brainpilot-bench");
}

/** 某 sha256 的内容寻址绝对路径（<cacheDir>/<sha256>/data）。 */
export function cachePathFor(sha256: string): string {
  return join(cacheDir(), sha256, "data");
}

/** 流式计算文件 sha256 并与期望比对（大文件不全读进内存）。 */
export async function verifySha256(path: string, expected: string): Promise<boolean> {
  const actual = await sha256File(path);
  return actual === expected;
}

/** 缓存命中 = 文件存在且 sha256 匹配（防止半截/损坏文件被当命中）。 */
export async function isCached(sha256: string): Promise<boolean> {
  const p = cachePathFor(sha256);
  try {
    const s = await stat(p);
    if (!s.isFile()) return false;
  } catch {
    return false;
  }
  return verifySha256(p, sha256);
}

/** 流式 sha256。 */
export function sha256File(path: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const h = createHash("sha256");
    const rs = createReadStream(path);
    rs.on("error", reject);
    rs.on("data", (chunk) => h.update(chunk));
    rs.on("end", () => resolve(h.digest("hex")));
  });
}
