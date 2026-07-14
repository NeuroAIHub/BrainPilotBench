/**
 * data/fetch.ts — scheme → fetcher 开放注册表（对称于 scorer 注册表）+ 内置 fetcher。
 * 内置：file://（本地复制）、https://（Node 全局 fetch）、hf://（Hugging Face Hub）。
 */
import { createWriteStream, readFileSync } from "node:fs";
import { copyFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import type { Fetcher, FetchRequest } from "./types.js";

const REGISTRY = new Map<string, Fetcher>();

export type DataFetchErrorKind = "authentication" | "authorization" | "proxy" | "network" | "disk" | "http";

export class DataFetchError extends Error {
  constructor(
    message: string,
    public readonly kind: DataFetchErrorKind,
    public readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "DataFetchError";
  }
}

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

function errorForStatus(status: number): DataFetchError {
  if (status === 401) return new DataFetchError("authentication required (HTTP 401)", "authentication", status);
  if (status === 403) return new DataFetchError("access denied (HTTP 403)", "authorization", status);
  if (status === 407) return new DataFetchError("proxy authentication required (HTTP 407)", "proxy", status);
  return new DataFetchError(`download failed (HTTP ${status})`, "http", status);
}

function classifyIoError(error: unknown): DataFetchError {
  if (error instanceof DataFetchError) return error;
  const code = (error as NodeJS.ErrnoException)?.code;
  if (code === "ENOSPC" || code === "EDQUOT") {
    return new DataFetchError("download failed: insufficient disk space", "disk", undefined, { cause: error });
  }
  const proxyConfigured = Boolean(
    process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy,
  );
  return new DataFetchError(
    proxyConfigured ? "download failed while using the configured proxy" : "download failed: network unavailable",
    proxyConfigured ? "proxy" : "network",
    undefined,
    { cause: error },
  );
}

async function existingSize(path: string): Promise<number> {
  try { return (await stat(path)).size; } catch { return 0; }
}

/** HTTP download with Range resume and streaming progress. */
async function download(url: string, req: FetchRequest, headers: Record<string, string> = {}): Promise<void> {
  const resumedFrom = await existingSize(req.destPath);
  const requestHeaders = { ...headers };
  if (resumedFrom > 0) requestHeaders.Range = `bytes=${resumedFrom}-`;
  try {
    const response = await fetch(url, { headers: requestHeaders, redirect: "follow" });
    if (response.status === 416 && resumedFrom > 0) return; // verifySha256 decides whether it was complete.
    if (!response.ok || !response.body) throw errorForStatus(response.status);
    const append = resumedFrom > 0 && response.status === 206;
    let downloadedBytes = append ? resumedFrom : 0;
    const actualResume = append ? resumedFrom : 0;
    const meter = new Transform({
      transform(chunk, _encoding, callback) {
        downloadedBytes += chunk.length;
        req.onProgress?.({ downloadedBytes, totalBytes: req.expectedBytes, resumedFrom: actualResume });
        callback(null, chunk);
      },
    });
    req.onProgress?.({ downloadedBytes, totalBytes: req.expectedBytes, resumedFrom: actualResume });
    await pipeline(
      Readable.fromWeb(response.body as any),
      meter,
      createWriteStream(req.destPath, { flags: append ? "a" : "w" }),
    );
  } catch (error) {
    throw classifyIoError(error);
  }
}

/** https 下载到 destPath（流式，避免大文件进内存）。 */
async function httpsFetch(req: FetchRequest): Promise<void> {
  await download(req.uri, req);
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
  const tok = resolveHfToken();
  if (tok) headers.Authorization = `Bearer ${tok}`;
  return { url, headers };
}

/** Resolve the standard Hugging Face token without ever logging it. */
export function resolveHfToken(): string | undefined {
  const fromEnv = process.env.HF_TOKEN || process.env.HUGGING_FACE_HUB_TOKEN;
  if (fromEnv) return fromEnv.trim() || undefined;
  if (process.env.BPB_NO_HF_TOKEN_FILE) return undefined;
  const home = process.env.HF_HOME || join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "huggingface");
  try { return readFileSync(join(home, "token"), "utf8").trim() || undefined; }
  catch { return undefined; }
}

// 内置 fetcher 注册（模块加载即注册一次）。
registerFetcher("file", async (req) => {
  const srcPath = req.uri.startsWith("file://") ? fileURLToPath(req.uri) : req.uri.slice("file://".length);
  await copyFile(srcPath, req.destPath);
});
registerFetcher("https", httpsFetch);
registerFetcher("hf", async (req) => {
  const { url, headers } = hfResolve(req.uri);
  await download(url, req, headers);
});
