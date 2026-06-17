import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { registerFetcher, getFetcher, hasFetcher, listFetchers, schemeOf, ossToHttps } from "./fetch.js";
import "./fetch.js";

test("schemeOf: 取 uri 的 scheme", () => {
  assert.equal(schemeOf("oss://bucket/k"), "oss");
  assert.equal(schemeOf("https://h/k"), "https");
  assert.equal(schemeOf("file:///tmp/x"), "file");
  assert.throws(() => schemeOf("no-scheme"), /uri has no scheme/);
});

test("内置 fetcher 已注册：file / https / oss", () => {
  assert.equal(hasFetcher("file"), true);
  assert.equal(hasFetcher("https"), true);
  assert.equal(hasFetcher("oss"), true);
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

test("registerFetcher: 可注册自定义 scheme", async () => {
  let called = "";
  registerFetcher("memtest", async (req) => { called = req.uri; });
  await getFetcher("memtest")({ uri: "memtest://x", destPath: "/dev/null" });
  assert.equal(called, "memtest://x");
});
