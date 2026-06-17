/**
 * data/manifest.ts — 解析 + 校验 data.lock。
 */
import type { DataManifest, DatasetEntry } from "./types.js";

const SHA256_RE = /^[0-9a-f]{64}$/;
/** name 用作缓存临时文件名的一部分；限制安全字符集，杜绝路径穿越(../、/、\)。 */
const NAME_RE = /^[A-Za-z0-9._-]+$/;

/** 把解析过的 data.lock 原始对象校验成 DataManifest。 */
export function parseDataManifest(raw: any): DataManifest {
  const list = raw?.datasets;
  if (list == null) return { datasets: [] };
  if (!Array.isArray(list)) throw new Error("data.lock: 'datasets' must be a list");
  const datasets: DatasetEntry[] = list.map((d: any, i: number) => {
    if (d == null || typeof d !== "object" || Array.isArray(d))
      throw new Error(`data.lock: datasets[${i}] must be a mapping`);
    if (typeof d.name !== "string" || !d.name) throw new Error(`data.lock: datasets[${i}]: missing 'name'`);
    if (!NAME_RE.test(d.name) || d.name === "." || d.name === "..")
      throw new Error(`data.lock: datasets[${i}]: name must match [A-Za-z0-9._-] (no path separators)`);
    if (typeof d.uri !== "string" || !d.uri) throw new Error(`data.lock: datasets[${i}]: missing 'uri'`);
    if (typeof d.sha256 !== "string" || !SHA256_RE.test(d.sha256))
      throw new Error(`data.lock: datasets[${i}]: sha256 must be 64 hex chars`);
    if (!Number.isInteger(d.bytes) || d.bytes < 0)
      throw new Error(`data.lock: datasets[${i}]: bytes must be a non-negative integer`);
    return {
      name: d.name,
      uri: d.uri,
      sha256: d.sha256,
      bytes: d.bytes,
      format: typeof d.format === "string" ? d.format : undefined,
    };
  });
  return { datasets };
}
