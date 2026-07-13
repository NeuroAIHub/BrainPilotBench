/**
 * data/fetch.ts — scheme → fetcher 开放注册表（对称于 scorer 注册表）+ 内置 fetcher。
 * 内置：file://（本地复制）、https://（Node 全局 fetch）、hf://（Hugging Face Hub）。
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

/** 取 uri 的 scheme（"https://x" → "https"）。 */
export function schemeOf(uri: string): string {
  const m = /^([a-zA-Z][a-zA-Z0-9+.-]*):\/\//.exec(uri);
  if (!m) throw new Error(`uri has no scheme: ${uri}`);
  return m[1].toLowerCase();
}

/** https 下载到 destPath（流式，避免大文件进内存）。 */
async function httpsFetch(req: FetchRequest): Promise<void> {
  const res = await fetch(req.uri);
  if (!res.ok || !res.body) throw new Error(`fetch ${req.uri} → ${res.status}`);
  await pipeline(Readable.fromWeb(res.body as any), createWriteStream(req.destPath));
}

/** hf://datasets/<owner>/<repo>[@<revision>]/<path>   (数据集)
 *  hf://<owner>/<repo>[@<revision>]/<path>            (模型，不带 datasets/ 前缀)
 *  → https://<endpoint>/[datasets/]<owner>/<repo>/resolve/<revision>/<path>
 *  revision 缺省 "main"；强烈建议 pin 到 commit sha(分支可变、sha 不变;sha256 也会兜底)。
 *  私有/gated: 设 HF_TOKEN 或 HUGGING_FACE_HUB_TOKEN → Authorization: Bearer(永不进 git)。
 *  自建镜像/企业版: 用 HF_ENDPOINT 覆盖(默认 https://huggingface.co)。 */
export function hfResolve(uri: string): { url: string; headers: Record<string, string> } {
  const rest = uri.slice("hf://".length);
  const isDataset = rest.startsWith("datasets/");
  const body = isDataset ? rest.slice("datasets/".length) : rest;
  const m = /^([^/]+)\/([^/@]+)(?:@([^/]+))?\/(.+)$/.exec(body);
  if (!m) throw new Error(`hf uri must be hf://[datasets/]<owner>/<repo>[@<rev>]/<path>: ${uri}`);
  const [, owner, repo, rev = "main", path] = m;
  const endpoint = (process.env.HF_ENDPOINT || "https://huggingface.co").replace(/\/+$/, "");
  const prefix = isDataset ? "datasets/" : "";
  const url = `${endpoint}/${prefix}${owner}/${repo}/resolve/${rev}/${path}`;
  const headers: Record<string, string> = {};
  const tok = process.env.HF_TOKEN || process.env.HUGGING_FACE_HUB_TOKEN;
  if (tok) headers.Authorization = `Bearer ${tok}`;
  return { url, headers };
}

/** https 下载(带自定义 headers,给 hf:// 复用)。 */
async function httpsFetchWithHeaders(url: string, destPath: string, headers: Record<string, string>): Promise<void> {
  const res = await fetch(url, { headers, redirect: "follow" });
  if (!res.ok || !res.body) throw new Error(`fetch ${url} → ${res.status}`);
  await pipeline(Readable.fromWeb(res.body as any), createWriteStream(destPath));
}

// 内置 fetcher 注册（模块加载即注册一次）。
registerFetcher("file", async (req) => {
  const srcPath = req.uri.startsWith("file://") ? fileURLToPath(req.uri) : req.uri.slice("file://".length);
  await copyFile(srcPath, req.destPath);
});
registerFetcher("https", httpsFetch);
registerFetcher("hf", async (req) => {
  const { url, headers } = hfResolve(req.uri);
  await httpsFetchWithHeaders(url, req.destPath, headers);
});
