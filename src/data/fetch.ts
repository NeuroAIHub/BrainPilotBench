/**
 * data/fetch.ts — scheme → fetcher 开放注册表（对称于 scorer 注册表）+ 内置 fetcher。
 * 内置：file://（本地复制）、https://（Node 全局 fetch）、oss://（公开桶=重写成公共 https，零依赖）。
 * 私有 OSS 桶不在本期（公开只读桶决策）；要私有再注册一个走 ossutil 的 fetcher 即可，不碰 core。
 */
import { createWriteStream } from "node:fs";
import { copyFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { Fetcher, FetchRequest } from "./types.js";

const REGISTRY = new Map<string, Fetcher>();

export function registerFetcher(scheme: string, f: Fetcher): void {
  REGISTRY.set(scheme, f);
}
export function getFetcher(scheme: string): Fetcher {
  const f = REGISTRY.get(scheme);
  if (!f) throw new Error(`unknown uri scheme: ${scheme} (registered: ${[...REGISTRY.keys()].join(", ") || "none"})`);
  return f;
}
export function hasFetcher(scheme: string): boolean {
  return REGISTRY.has(scheme);
}
export function listFetchers(): string[] {
  return [...REGISTRY.keys()];
}

/** 取 uri 的 scheme（"oss://x" → "oss"）。 */
export function schemeOf(uri: string): string {
  const m = /^([a-zA-Z][a-zA-Z0-9+.-]*):\/\//.exec(uri);
  if (!m) throw new Error(`uri has no scheme: ${uri}`);
  return m[1].toLowerCase();
}

/** 公开桶 oss://<bucket>/<key> → https://<bucket>.<endpoint>/<key>。
 *  默认端点 = 传输加速 oss-accelerate.aliyuncs.com(全球就近,无需 AK/SK,公开读直下)。
 *  可用环境 OSS_PUBLIC_ENDPOINT 覆盖(如区域端点或 CDN 自定义域名)。 */
export function ossToHttps(uri: string): string {
  const rest = uri.slice("oss://".length);
  const slash = rest.indexOf("/");
  if (slash < 0) throw new Error(`oss uri must be oss://<bucket>/<key>: ${uri}`);
  const bucket = rest.slice(0, slash);
  const key = rest.slice(slash + 1);
  const endpoint = process.env.OSS_PUBLIC_ENDPOINT || "oss-accelerate.aliyuncs.com";
  return `https://${bucket}.${endpoint}/${key}`;
}

/** https 下载到 destPath（流式，避免大文件进内存）。 */
async function httpsFetch(req: FetchRequest): Promise<void> {
  const res = await fetch(req.uri);
  if (!res.ok || !res.body) throw new Error(`fetch ${req.uri} → ${res.status}`);
  await pipeline(Readable.fromWeb(res.body as any), createWriteStream(req.destPath));
}

// 内置 fetcher 注册（模块加载即注册一次）。
registerFetcher("file", async (req) => {
  const srcPath = req.uri.startsWith("file://") ? fileURLToPath(req.uri) : req.uri.slice("file://".length);
  await copyFile(srcPath, req.destPath);
});
registerFetcher("https", httpsFetch);
registerFetcher("oss", async (req) => {
  await httpsFetch({ uri: ossToHttps(req.uri), destPath: req.destPath });
});
