import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DataFetchError, registerFetcher, getFetcher, hasFetcher, listFetchers, schemeOf, hfResolve, resolveHfToken } from "./fetch.js";
import "./fetch.js";

test("schemeOf: 取 uri 的 scheme", () => {
  assert.equal(schemeOf("hf://datasets/owner/repo/path"), "hf");
  assert.equal(schemeOf("https://h/k"), "https");
  assert.equal(schemeOf("file:///tmp/x"), "file");
  assert.throws(() => schemeOf("no-scheme"), /uri has no scheme/);
});

test("内置 fetcher 已注册：file / https / hf", () => {
  assert.equal(hasFetcher("file"), true);
  assert.equal(hasFetcher("https"), true);
  assert.equal(hasFetcher("hf"), true);
  assert.equal(hasFetcher("oss"), false);
  assert.ok(listFetchers().includes("file"));
});

test("getFetcher: 未知 scheme 报清晰错误", () => {
  assert.throws(() => getFetcher("ftp"), /unknown uri scheme: ftp/);
});

test("file fetcher: 复制本地文件到 destPath", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-fetch-"));
  try {
    const src = join(dir, "src.bin");
    const dest = join(dir, "dest.bin");
    writeFileSync(src, "payload-123");
    await getFetcher("file")({ uri: "file://" + src, destPath: dest });
    assert.equal(readFileSync(dest, "utf8"), "payload-123");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("hfResolve: dataset uri 重写到 /resolve/main/", () => {
  const prevEp = process.env.HF_ENDPOINT, prevTok = process.env.HF_TOKEN, prevTok2 = process.env.HUGGING_FACE_HUB_TOKEN, prevNoFile = process.env.BPB_NO_HF_TOKEN_FILE;
  try {
    delete process.env.HF_ENDPOINT; delete process.env.HF_TOKEN; delete process.env.HUGGING_FACE_HUB_TOKEN;
    process.env.BPB_NO_HF_TOKEN_FILE = "1";
    const { url, headers } = hfResolve("hf://datasets/openai/gsm8k/main/train.parquet");
    assert.equal(url, "https://huggingface.co/datasets/openai/gsm8k/resolve/main/main/train.parquet");
    assert.deepEqual(headers, {});
  } finally {
    if (prevEp !== undefined) process.env.HF_ENDPOINT = prevEp;
    if (prevTok !== undefined) process.env.HF_TOKEN = prevTok;
    if (prevTok2 !== undefined) process.env.HUGGING_FACE_HUB_TOKEN = prevTok2;
    if (prevNoFile === undefined) delete process.env.BPB_NO_HF_TOKEN_FILE; else process.env.BPB_NO_HF_TOKEN_FILE = prevNoFile;
  }
});

test("resolveHfToken: supports the standard hf auth login token file", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-hf-token-"));
  const prevHome = process.env.HF_HOME, prevToken = process.env.HF_TOKEN, prevNoFile = process.env.BPB_NO_HF_TOKEN_FILE;
  try {
    mkdirSync(root, { recursive: true });
    writeFileSync(join(root, "token"), "hf_from_login\n");
    process.env.HF_HOME = root;
    delete process.env.HF_TOKEN;
    delete process.env.BPB_NO_HF_TOKEN_FILE;
    assert.equal(resolveHfToken(), "hf_from_login");
  } finally {
    rmSync(root, { recursive: true, force: true });
    if (prevHome === undefined) delete process.env.HF_HOME; else process.env.HF_HOME = prevHome;
    if (prevToken === undefined) delete process.env.HF_TOKEN; else process.env.HF_TOKEN = prevToken;
    if (prevNoFile === undefined) delete process.env.BPB_NO_HF_TOKEN_FILE; else process.env.BPB_NO_HF_TOKEN_FILE = prevNoFile;
  }
});

test("https fetcher resumes a partial file with Range and reports progress", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-http-resume-"));
  const dest = join(root, "partial");
  writeFileSync(dest, "abc");
  const originalFetch = globalThis.fetch;
  let range = "";
  const seen: number[] = [];
  try {
    globalThis.fetch = async (_input, init) => {
      range = new Headers(init?.headers).get("range") ?? "";
      return new Response("def", { status: 206 });
    };
    await getFetcher("https")({
      uri: "https://example.test/data",
      destPath: dest,
      expectedBytes: 6,
      onProgress: (progress) => seen.push(progress.downloadedBytes),
    });
    assert.equal(range, "bytes=3-");
    assert.equal(readFileSync(dest, "utf8"), "abcdef");
    assert.equal(seen.at(-1), 6);
  } finally {
    globalThis.fetch = originalFetch;
    rmSync(root, { recursive: true, force: true });
  }
});

test("https fetcher classifies authentication and authorization failures", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-http-error-"));
  const originalFetch = globalThis.fetch;
  try {
    for (const [status, kind] of [[401, "authentication"], [403, "authorization"]] as const) {
      globalThis.fetch = async () => new Response("denied", { status });
      await assert.rejects(
        () => getFetcher("https")({ uri: "https://example.test/data", destPath: join(root, String(status)) }),
        (error: any) => error instanceof DataFetchError && error.kind === kind && error.status === status,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
    rmSync(root, { recursive: true, force: true });
  }
});

test("https fetcher distinguishes disk, proxy, and direct-network failures", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-http-io-error-"));
  const originalFetch = globalThis.fetch;
  const proxyKeys = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"];
  const previous = Object.fromEntries(proxyKeys.map((key) => [key, process.env[key]]));
  try {
    for (const key of proxyKeys) delete process.env[key];
    const fail = async (error: NodeJS.ErrnoException, kind: string) => {
      globalThis.fetch = async () => { throw error; };
      await assert.rejects(
        () => getFetcher("https")({ uri: "https://example.test/data", destPath: join(root, kind) }),
        (caught: any) => caught instanceof DataFetchError && caught.kind === kind,
      );
    };
    await fail(Object.assign(new Error("no space"), { code: "ENOSPC" }), "disk");
    await fail(Object.assign(new Error("offline"), { code: "ENETUNREACH" }), "network");
    process.env.https_proxy = "http://127.0.0.1:7890";
    await fail(Object.assign(new Error("proxy refused"), { code: "ECONNREFUSED" }), "proxy");
  } finally {
    globalThis.fetch = originalFetch;
    for (const key of proxyKeys) {
      if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key];
    }
    rmSync(root, { recursive: true, force: true });
  }
});

test("hfResolve: @revision 显式 pin 到 commit/tag/branch", () => {
  const { url } = hfResolve("hf://datasets/foo/bar@a1b2c3d/data.csv");
  assert.equal(url, "https://huggingface.co/datasets/foo/bar/resolve/a1b2c3d/data.csv");
});

test("hfResolve: 无 datasets/ 前缀 = 模型仓库", () => {
  const { url } = hfResolve("hf://meta-llama/Llama-3-8B@main/config.json");
  assert.equal(url, "https://huggingface.co/meta-llama/Llama-3-8B/resolve/main/config.json");
});

test("hfResolve: HF_TOKEN 注入 Bearer(私有/gated 用);HF_ENDPOINT 覆盖端点", () => {
  const prevEp = process.env.HF_ENDPOINT, prevTok = process.env.HF_TOKEN;
  try {
    process.env.HF_TOKEN = "hf_xxx";
    process.env.HF_ENDPOINT = "https://hf-mirror.example.com/";
    const { url, headers } = hfResolve("hf://datasets/o/r/x.parquet");
    assert.equal(url, "https://hf-mirror.example.com/datasets/o/r/resolve/main/x.parquet");
    assert.equal(headers.Authorization, "Bearer hf_xxx");
  } finally {
    if (prevEp === undefined) delete process.env.HF_ENDPOINT; else process.env.HF_ENDPOINT = prevEp;
    if (prevTok === undefined) delete process.env.HF_TOKEN; else process.env.HF_TOKEN = prevTok;
  }
});

test("hfResolve: 畸形 uri 报清晰错误", () => {
  assert.throws(() => hfResolve("hf://only-owner"), /hf uri must be/);
  assert.throws(() => hfResolve("hf://datasets/only-owner"), /hf uri must be/);
});

test("registerFetcher: 可注册自定义 scheme", async () => {
  let called = "";
  registerFetcher("memtest", async (req) => { called = req.uri; });
  await getFetcher("memtest")({ uri: "memtest://x", destPath: "/dev/null" });
  assert.equal(called, "memtest://x");
});
