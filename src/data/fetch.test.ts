import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { registerFetcher, getFetcher, hasFetcher, listFetchers, schemeOf, ossToHttps, hfResolve } from "./fetch.js";
import "./fetch.js";

test("schemeOf: 取 uri 的 scheme", () => {
  assert.equal(schemeOf("oss://bucket/k"), "oss");
  assert.equal(schemeOf("https://h/k"), "https");
  assert.equal(schemeOf("file:///tmp/x"), "file");
  assert.throws(() => schemeOf("no-scheme"), /uri has no scheme/);
});

test("内置 fetcher 已注册：file / https / oss / hf", () => {
  assert.equal(hasFetcher("file"), true);
  assert.equal(hasFetcher("https"), true);
  assert.equal(hasFetcher("oss"), true);
  assert.equal(hasFetcher("hf"), true);
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

test("ossToHttps: 公开桶 oss:// 重写成传输加速 https 端点", () => {
  // 约定：oss://<bucket>/<key> + 环境 OSS_PUBLIC_ENDPOINT(默认 oss-accelerate.aliyuncs.com 全球传输加速)
  const prev = process.env.OSS_PUBLIC_ENDPOINT;
  try {
    delete process.env.OSS_PUBLIC_ENDPOINT;
    assert.equal(ossToHttps("oss://my-bucket/path/to/x.parquet"),
      "https://my-bucket.oss-accelerate.aliyuncs.com/path/to/x.parquet");
    process.env.OSS_PUBLIC_ENDPOINT = "oss-cn-beijing.aliyuncs.com";
    assert.equal(ossToHttps("oss://b/k"),
      "https://b.oss-cn-beijing.aliyuncs.com/k");
  } finally {
    if (prev === undefined) delete process.env.OSS_PUBLIC_ENDPOINT; else process.env.OSS_PUBLIC_ENDPOINT = prev;
  }
});

test("hfResolve: dataset uri 重写到 /resolve/main/", () => {
  const prevEp = process.env.HF_ENDPOINT, prevTok = process.env.HF_TOKEN, prevTok2 = process.env.HUGGING_FACE_HUB_TOKEN;
  try {
    delete process.env.HF_ENDPOINT; delete process.env.HF_TOKEN; delete process.env.HUGGING_FACE_HUB_TOKEN;
    const { url, headers } = hfResolve("hf://datasets/openai/gsm8k/main/train.parquet");
    assert.equal(url, "https://huggingface.co/datasets/openai/gsm8k/resolve/main/main/train.parquet");
    assert.deepEqual(headers, {});
  } finally {
    if (prevEp !== undefined) process.env.HF_ENDPOINT = prevEp;
    if (prevTok !== undefined) process.env.HF_TOKEN = prevTok;
    if (prevTok2 !== undefined) process.env.HUGGING_FACE_HUB_TOKEN = prevTok2;
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
