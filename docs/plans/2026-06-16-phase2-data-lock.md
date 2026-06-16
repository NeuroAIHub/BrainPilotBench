# Phase 2 — data.lock 数据子系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让任务能声明大数据集（`data.lock`，内容寻址），harness 按 scheme 懒拉取、sha256 校验、落到本地内容寻址缓存——git 仓零数据膨胀，零新依赖，可完整离线测试。

**Architecture:** 新增 `src/data/` 子包：`manifest`（解析+校验 `data.lock`）+ `cache`（XDG `$XDG_CACHE_HOME/brainpilot-bench/<sha256>/` 内容寻址缓存）+ `fetch`（`scheme→fetcher` 开放注册表，对称于 scorer 注册表）+ `resolve`（编排：查缓存命中则返回、未命中则 fetch→校验 sha256→落缓存）。先实现 `file://`/`https://` fetcher（可离线/可联网测），`oss://` 走"公开桶 = 重写成公共 https 端点"的**零依赖**路径。`loadTask` 解析出 `task.datasets`（仅元数据，不触发下载）；实际 resolve 由 CLI 显式触发或新 `bp-bench fetch` 命令。**本期不把数据 stage 进被测 workspace**（当前协议无上传路由，留给 Phase 3 SUT adapter）。再加 CI 文件大小门（25MB/文件、100MB/PR）。

**Tech Stack:** TypeScript (NodeNext, strict) → `tsc` → `dist/`；`node --test` 跑 `dist/**/*.test.js`；`yaml` 解析；**零新运行时依赖**——`fetch`（Node 20+ 全局）拉 https、`node:fs`/`node:fs/promises` 拉 file+写缓存、`node:crypto` 算 sha256。Node ≥ 22（环境 v24）。CI = GitHub Actions（本仓暂无 workflow，本期新建）。

---

## 前置说明（执行者必读）

- 工作目录：`/Users/lucasli/Desktop/BrainPilot/repos/brainpilot-benchmark`。当前在 `main`。**第一步先开分支**（见下）。
- 跑命令前若 `node` 不在 PATH：先 `. "$HOME/.nvm/nvm.sh"`。Node v24，全局 `fetch` 可用。
- 构建 `npm run build`（tsc，rootDir `src`→`dist`，NodeNext strict）；测试 `npm test`（`node --test "dist/**/*.test.js"`）；typecheck `npm run typecheck`。
- **TS-TDD 约定**：测试 `.ts` 编译成 `dist/**/*.test.js` 再跑。引用不存在的导出 → `npm run build` 编译失败 = RED；逻辑未实现 → 编译过、`npm test` 断言失败 = RED。每步标明预期 RED 形态。
- **零新依赖纪律**：不得 `npm install` 任何新包（不引 `ali-oss`、不引 fetch polyfill）。只用 Node 内置 + 已有的 `yaml`。
- 提交信息结尾固定加：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- **不要把真实大数据写进仓**。测试用本地临时小文件（`node:os` tmpdir + 几十字节内容）验证 fetch/缓存/校验逻辑。

### 开分支（Task 0，必须先做）

- [ ] 运行：
```bash
cd /Users/lucasli/Desktop/BrainPilot/repos/brainpilot-benchmark
git checkout main && git pull
git checkout -b feat/phase2-data-lock
```

## 文件结构（本期落子）

| 文件 | 职责 |
|---|---|
| `src/data/types.ts` | 创建。`DatasetEntry`/`DataManifest`/`ResolvedDataset`/`Fetcher`/`FetchRequest` 接口 |
| `src/data/manifest.ts` | 创建。`parseDataManifest()`（解析 `data.lock` YAML→校验 name/uri/sha256/bytes/format） |
| `src/data/cache.ts` | 创建。`cacheDir()`/`cachePathFor(sha256)`/`isCached()`/`verifySha256()` 内容寻址缓存 |
| `src/data/fetch.ts` | 创建。`registerFetcher`/`getFetcher`/`hasFetcher`/`listFetchers` + 内置 `file`/`https` fetcher + `oss`→https 重写 |
| `src/data/resolve.ts` | 创建。`resolveDataset()`（查缓存→fetch→校验→落盘）+ `resolveManifest()` |
| `src/data/index.ts` | 创建。re-export + `import "./fetch.js"` 触发内置 fetcher 注册 |
| `src/data/*.test.ts` | 创建。manifest / cache / fetch / resolve 四组单测 |
| `src/task.ts` | 修改。新增 `DatasetEntry` 引用 + `Task.datasets: DatasetEntry[]`（loader 填充，可空） |
| `src/loader.ts` | 修改。`loadTask` 读 `data.lock`（存在则解析，不存在则 `[]`），填 `task.datasets` |
| `src/index.ts` | 修改。`export * from "./data/index.js"` |
| `src/cli.ts` | 修改。新增 `bp-bench fetch <taskId|all>` 子命令（显式拉取该任务数据集） |
| `package.json` | 修改。`exports` 加 `./data` |
| `.gitignore` | 修改。忽略本地缓存目录（仅当落在仓内时；默认 XDG 在仓外，加一条防御性 `.cache/`） |
| `.github/workflows/task-size.yml` | 创建。CI 文件大小门（25MB/文件、100MB/PR diff） |
| `scripts/check-task-size.mjs` | 创建。大小门脚本（被 workflow 调用，也可本地跑） |

> 说明：`Task.datasets` 与 `DatasetEntry` 的类型放在 `src/data/types.ts`，`task.ts` 用 `import type` 引用，保持 `task.ts` 仍是叶子（不反向依赖 data 子系统的运行时代码）。

---

## Task 1: data 子系统类型 + manifest 解析

**Files:**
- Create: `src/data/types.ts`
- Create: `src/data/manifest.ts`
- Test: `src/data/manifest.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `src/data/manifest.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDataManifest } from "./manifest.js";

test("parseDataManifest: 解析合法 data.lock", () => {
  const m = parseDataManifest({
    datasets: [
      { name: "ds-a", uri: "oss://bucket/a.parquet", sha256: "a".repeat(64), bytes: 123, format: "parquet" },
    ],
  });
  assert.equal(m.datasets.length, 1);
  assert.equal(m.datasets[0].name, "ds-a");
  assert.equal(m.datasets[0].uri, "oss://bucket/a.parquet");
  assert.equal(m.datasets[0].sha256, "a".repeat(64));
  assert.equal(m.datasets[0].bytes, 123);
  assert.equal(m.datasets[0].format, "parquet");
});

test("parseDataManifest: 空/缺 datasets → 空清单", () => {
  assert.deepEqual(parseDataManifest(undefined).datasets, []);
  assert.deepEqual(parseDataManifest({}).datasets, []);
  assert.deepEqual(parseDataManifest({ datasets: [] }).datasets, []);
});

test("parseDataManifest: 缺字段报清晰错误", () => {
  assert.throws(() => parseDataManifest({ datasets: [{ uri: "x", sha256: "a".repeat(64), bytes: 1 }] }),
    /datasets\[0\]: missing 'name'/);
  assert.throws(() => parseDataManifest({ datasets: [{ name: "x", sha256: "a".repeat(64), bytes: 1 }] }),
    /datasets\[0\]: missing 'uri'/);
});

test("parseDataManifest: sha256 必须是 64 位十六进制", () => {
  assert.throws(() => parseDataManifest({ datasets: [{ name: "x", uri: "u", sha256: "zzz", bytes: 1 }] }),
    /datasets\[0\]: sha256 must be 64 hex chars/);
});

test("parseDataManifest: bytes 必须是非负整数", () => {
  assert.throws(() => parseDataManifest({ datasets: [{ name: "x", uri: "u", sha256: "a".repeat(64), bytes: -1 }] }),
    /datasets\[0\]: bytes must be a non-negative integer/);
});

test("parseDataManifest: null 列表项报清晰错误", () => {
  assert.throws(() => parseDataManifest({ datasets: [null] }), /datasets\[0\] must be a mapping/);
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './manifest.js'` 或 `./types.js`。

- [ ] **Step 3: 写 `src/data/types.ts`**

```ts
/**
 * data/types.ts — data.lock 数据子系统的承重墙接口。
 * 大数据集 body 永不进 git；data.lock 是内容寻址清单(name+uri+sha256+bytes+format)，
 * 按 scheme 懒拉取、sha256 校验、落本地内容寻址缓存。
 */

/** data.lock 里的一条数据集声明。 */
export interface DatasetEntry {
  /** 任务内唯一名（也用于 stage 时的目标文件名）。 */
  name: string;
  /** 内容来源；scheme 决定用哪个 fetcher：oss:// / https:// / file:// 。 */
  uri: string;
  /** 内容 sha256（64 位十六进制小写）——内容寻址 + 完整性校验的键。 */
  sha256: string;
  /** 期望字节数（用于进度/审计；下载后会与实际比对）。 */
  bytes: number;
  /** 格式标签（parquet/csv/nii.gz/...），仅元数据。 */
  format?: string;
}

/** 一个任务的 data.lock 解析结果。 */
export interface DataManifest {
  datasets: DatasetEntry[];
}

/** resolve 后的数据集：本地缓存绝对路径 + 原始声明。 */
export interface ResolvedDataset {
  entry: DatasetEntry;
  /** 内容寻址缓存里的绝对路径（已通过 sha256 校验）。 */
  path: string;
  /** 本次是否真的下载了（false = 缓存命中）。 */
  fetched: boolean;
}

/** fetcher 收到的请求：解析出的 uri + 目标落盘路径（由 cache 决定）。 */
export interface FetchRequest {
  uri: string;
  /** fetcher 应把内容写到这个绝对路径（cache 提供的临时路径）。 */
  destPath: string;
}

/** 一个 scheme 的拉取实现（对称于 scorer 注册表）。 */
export type Fetcher = (req: FetchRequest) => Promise<void>;
```

- [ ] **Step 4: 写 `src/data/manifest.ts`**

```ts
/**
 * data/manifest.ts — 解析 + 校验 data.lock。
 */
import type { DataManifest, DatasetEntry } from "./types.js";

const SHA256_RE = /^[0-9a-f]{64}$/;

/** 把解析过的 data.lock 原始对象校验成 DataManifest。 */
export function parseDataManifest(raw: any): DataManifest {
  const list = raw?.datasets;
  if (list == null) return { datasets: [] };
  if (!Array.isArray(list)) throw new Error("data.lock: 'datasets' must be a list");
  const datasets: DatasetEntry[] = list.map((d: any, i: number) => {
    if (d == null || typeof d !== "object" || Array.isArray(d))
      throw new Error(`data.lock: datasets[${i}] must be a mapping`);
    if (typeof d.name !== "string" || !d.name) throw new Error(`data.lock: datasets[${i}]: missing 'name'`);
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
```

- [ ] **Step 5: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`manifest.test.js` 6 个用例通过；总 `# fail 0`（含 Phase 1 的 13 个，共 19）。

- [ ] **Step 6: 提交**

```bash
git add src/data/types.ts src/data/manifest.ts src/data/manifest.test.ts
git commit -m "feat(data): data.lock 清单类型 + parseDataManifest 校验

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 内容寻址缓存（cache）

**Files:**
- Create: `src/data/cache.ts`
- Test: `src/data/cache.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `src/data/cache.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { cacheDir, cachePathFor, isCached, verifySha256 } from "./cache.js";

test("cacheDir: 尊重 XDG_CACHE_HOME，回落 ~/.cache", () => {
  const prev = process.env.XDG_CACHE_HOME;
  try {
    process.env.XDG_CACHE_HOME = "/tmp/xdg-test";
    assert.equal(cacheDir(), "/tmp/xdg-test/brainpilot-bench");
  } finally {
    if (prev === undefined) delete process.env.XDG_CACHE_HOME; else process.env.XDG_CACHE_HOME = prev;
  }
});

test("cachePathFor: 内容寻址路径含 sha256", () => {
  const sha = "a".repeat(64);
  const p = cachePathFor(sha);
  assert.ok(p.includes("brainpilot-bench"));
  assert.ok(p.endsWith(join(sha, "data")));
});

test("verifySha256: 正确内容通过、篡改内容拒绝", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-cache-"));
  try {
    const f = join(dir, "blob");
    const body = "hello-dataset";
    writeFileSync(f, body);
    const good = createHash("sha256").update(body).digest("hex");
    assert.equal(await verifySha256(f, good), true);
    assert.equal(await verifySha256(f, "b".repeat(64)), false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("isCached: 仅当文件存在且 sha256 匹配才算命中", async () => {
  const prev = process.env.XDG_CACHE_HOME;
  const dir = mkdtempSync(join(tmpdir(), "bpb-xdg-"));
  try {
    process.env.XDG_CACHE_HOME = dir;
    const body = "cached-body";
    const sha = createHash("sha256").update(body).digest("hex");
    assert.equal(await isCached(sha), false); // 还没写
    const p = cachePathFor(sha);
    const { mkdirSync } = await import("node:fs");
    mkdirSync(join(p, ".."), { recursive: true });
    writeFileSync(p, body);
    assert.equal(await isCached(sha), true);  // 写了且匹配
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (prev === undefined) delete process.env.XDG_CACHE_HOME; else process.env.XDG_CACHE_HOME = prev;
  }
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './cache.js'`。

- [ ] **Step 3: 写 `src/data/cache.ts`**

```ts
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
```

- [ ] **Step 4: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`cache.test.js` 4 个用例通过；总 `# fail 0`（共 23）。

- [ ] **Step 5: 提交**

```bash
git add src/data/cache.ts src/data/cache.test.ts
git commit -m "feat(data): 内容寻址缓存(XDG + 流式 sha256 校验 + 命中需匹配)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: fetcher 注册表 + file/https/oss fetcher

**Files:**
- Create: `src/data/fetch.ts`
- Test: `src/data/fetch.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `src/data/fetch.test.ts`：
```ts
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

test("ossToHttps: 公开桶 oss:// 重写成公共 https 端点", () => {
  // 约定：oss://<bucket>/<key> + 环境 OSS_PUBLIC_ENDPOINT(默认 oss-cn-hangzhou.aliyuncs.com)
  const prev = process.env.OSS_PUBLIC_ENDPOINT;
  try {
    delete process.env.OSS_PUBLIC_ENDPOINT;
    assert.equal(ossToHttps("oss://my-bucket/path/to/x.parquet"),
      "https://my-bucket.oss-cn-hangzhou.aliyuncs.com/path/to/x.parquet");
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
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './fetch.js'`。

- [ ] **Step 3: 写 `src/data/fetch.ts`**

```ts
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

/** 公开桶 oss://<bucket>/<key> → https://<bucket>.<endpoint>/<key>。 */
export function ossToHttps(uri: string): string {
  const rest = uri.slice("oss://".length);
  const slash = rest.indexOf("/");
  if (slash < 0) throw new Error(`oss uri must be oss://<bucket>/<key>: ${uri}`);
  const bucket = rest.slice(0, slash);
  const key = rest.slice(slash + 1);
  const endpoint = process.env.OSS_PUBLIC_ENDPOINT || "oss-cn-hangzhou.aliyuncs.com";
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
```

注意：`file fetcher` 的测试用 `file://` + 绝对路径。`fileURLToPath("file://" + "/tmp/x")` 在 POSIX 上等价 `/tmp/x`。若 `fileURLToPath` 对某些路径报错，回落到 `slice` 分支已覆盖。保持实现如上。

- [ ] **Step 4: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`fetch.test.js` 6 个用例通过；总 `# fail 0`（共 29）。

- [ ] **Step 5: 提交**

```bash
git add src/data/fetch.ts src/data/fetch.test.ts
git commit -m "feat(data): scheme→fetcher 注册表 + file/https/oss(公开桶重写) 零依赖

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: resolve 编排 + data/index 桶 + 公开 API

**Files:**
- Create: `src/data/resolve.ts`
- Create: `src/data/index.ts`
- Test: `src/data/resolve.test.ts`
- Modify: `src/index.ts`
- Modify: `package.json`

- [ ] **Step 1: 写失败测试**

创建 `src/data/resolve.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { resolveDataset, resolveManifest } from "./resolve.js";
import { cachePathFor } from "./cache.js";
import type { DatasetEntry } from "./types.js";

function withTmpXdg<T>(fn: (dir: string) => Promise<T>): Promise<T> {
  const prev = process.env.XDG_CACHE_HOME;
  const dir = mkdtempSync(join(tmpdir(), "bpb-resolve-"));
  process.env.XDG_CACHE_HOME = dir;
  return fn(dir).finally(() => {
    rmSync(dir, { recursive: true, force: true });
    if (prev === undefined) delete process.env.XDG_CACHE_HOME; else process.env.XDG_CACHE_HOME = prev;
  });
}

test("resolveDataset: 未命中→file fetch→校验→落缓存；再次→命中", async () => {
  await withTmpXdg(async (dir) => {
    const body = "neuro-payload";
    const sha = createHash("sha256").update(body).digest("hex");
    const src = join(dir, "src.bin");
    writeFileSync(src, body);
    const entry: DatasetEntry = { name: "ds", uri: "file://" + src, sha256: sha, bytes: body.length };

    const r1 = await resolveDataset(entry);
    assert.equal(r1.fetched, true);
    assert.equal(r1.path, cachePathFor(sha));
    assert.ok(existsSync(r1.path));

    const r2 = await resolveDataset(entry);
    assert.equal(r2.fetched, false); // 命中
    assert.equal(r2.path, r1.path);
  });
});

test("resolveDataset: sha256 不匹配→报错且不留半截缓存", async () => {
  await withTmpXdg(async (dir) => {
    const body = "real-body";
    const wrongSha = "c".repeat(64);
    const src = join(dir, "s.bin");
    writeFileSync(src, body);
    const entry: DatasetEntry = { name: "ds", uri: "file://" + src, sha256: wrongSha, bytes: body.length };
    await assert.rejects(() => resolveDataset(entry), /sha256 mismatch/);
    assert.equal(existsSync(cachePathFor(wrongSha)), false); // 没留下损坏缓存
  });
});

test("resolveManifest: 解析多条并全部 resolve", async () => {
  await withTmpXdg(async (dir) => {
    const mk = (name: string, body: string) => {
      const sha = createHash("sha256").update(body).digest("hex");
      const src = join(dir, name + ".bin");
      writeFileSync(src, body);
      return { name, uri: "file://" + src, sha256: sha, bytes: body.length };
    };
    const manifest = { datasets: [mk("a", "aaa"), mk("b", "bbbb")] };
    const out = await resolveManifest(manifest);
    assert.equal(out.length, 2);
    assert.ok(out.every((r) => existsSync(r.path)));
  });
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './resolve.js'`。

- [ ] **Step 3: 写 `src/data/resolve.ts`**

```ts
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
```

- [ ] **Step 4: 写 `src/data/index.ts`**

```ts
/**
 * data/index.ts — data 子系统公开 API（import 即触发内置 fetcher 注册副作用）。
 */
export * from "./types.js";
export * from "./manifest.js";
export * from "./cache.js";
export * from "./fetch.js";
export * from "./resolve.js";
```

注意：`./fetch.js` 的 `export *` 会带入其模块顶层的内置 fetcher 注册副作用——import `data/index.js` 即注册 file/https/oss。

- [ ] **Step 5: 改 `src/index.ts`**

在 `src/index.ts` 的 `export * from "./scorer/index.js";` 一行下方追加：
```ts
export * from "./data/index.js";
```

若 `tsc` 报 `ResolvedDataset`/`DatasetEntry` 等与其他模块的重复导出冲突，STOP 并报告（不应发生——data 的导出名都带 Data/Dataset/Fetcher/resolve 前缀，与 scorer/scoring/task 无重名）。

- [ ] **Step 6: 改 `package.json` exports 加 `./data`**

把：
```json
    "./scorer": "./dist/scorer/index.js"
  },
```
改成：
```json
    "./scorer": "./dist/scorer/index.js",
    "./data": "./dist/data/index.js"
  },
```

- [ ] **Step 7: 全量 typecheck + build + test 验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run typecheck && npm run build && npm test`
Expected: 三者全过；`resolve.test.js` 3 个用例通过；总 `# fail 0`（共 32）。

- [ ] **Step 8: 验证公开 API 解析**

Run:
```bash
. "$HOME/.nvm/nvm.sh"
node -e "import('./dist/index.js').then(m=>console.log('parseDataManifest:',typeof m.parseDataManifest,'| resolveManifest:',typeof m.resolveManifest,'| registerFetcher:',typeof m.registerFetcher,'| hasFetcher(oss):',m.hasFetcher('oss')))"
```
Expected: `parseDataManifest: function | resolveManifest: function | registerFetcher: function | hasFetcher(oss): true`

- [ ] **Step 9: 提交**

```bash
git add src/data/resolve.ts src/data/index.ts src/data/resolve.test.ts src/index.ts package.json
git commit -m "feat(data): resolve 编排(命中/校验/原子落缓存) + data 子系统公开 API + ./data 子路径

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: loader 读 data.lock → `task.datasets`

**Files:**
- Modify: `src/task.ts`（加 `Task.datasets`）
- Modify: `src/loader.ts`（读 `data.lock`）
- Test: `src/loader-data.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `src/loader-data.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTask } from "./loader.js";

function makeTask(withDataLock: boolean): string {
  const dir = mkdtempSync(join(tmpdir(), "bpb-task-"));
  writeFileSync(join(dir, "task.yaml"),
    "id: t-data\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: \"*.md\"\ntimeout_min: 5\nbudget_tokens: 1000\n");
  mkdirSync(join(dir, "prompt"), { recursive: true });
  writeFileSync(join(dir, "prompt", "turns.yaml"), "- send: hi\n");
  if (withDataLock) {
    writeFileSync(join(dir, "data.lock"),
      "datasets:\n  - name: ds-a\n    uri: oss://b/a.parquet\n    sha256: " + "a".repeat(64) + "\n    bytes: 42\n    format: parquet\n");
  }
  return dir;
}

test("loadTask: 有 data.lock → task.datasets 被解析填充", () => {
  const dir = makeTask(true);
  try {
    const t = loadTask(dir);
    assert.equal(t.datasets.length, 1);
    assert.equal(t.datasets[0].name, "ds-a");
    assert.equal(t.datasets[0].uri, "oss://b/a.parquet");
    assert.equal(t.datasets[0].bytes, 42);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("loadTask: 无 data.lock → task.datasets 为空数组", () => {
  const dir = makeTask(false);
  try {
    assert.deepEqual(loadTask(dir).datasets, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("loadTask: 种子任务(无 data.lock)仍 datasets=[]", () => {
  const SURVEY = join(process.cwd(), "tasks", "neuro-survey-attention");
  assert.deepEqual(loadTask(SURVEY).datasets, []);
});
```

注意：第三个测试用 `process.cwd()` + `tasks/neuro-survey-attention`，因此 `npm test` 必须在仓根跑（现状即如此）。不要在 ESM 测试里用 `require`（编译产物是 ESM，`require` 不可用）。

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Property 'datasets' does not exist on type 'Task'`。

- [ ] **Step 3: 在 `src/task.ts` 给 `Task` 加 `datasets`**

在 `src/task.ts` 顶部 import 区加（文件目前无 import；在文件最上方、首个 `export interface` 之前插入）：
```ts
import type { DatasetEntry } from "./data/types.js";
```

在 `Task` 接口里（`scorers: ScorerSpec[];` 一行下方）加：
```ts
  /** 该任务声明的数据集（来自 data.lock；无则空数组）。 */
  datasets: DatasetEntry[];
```

- [ ] **Step 4: 在 `src/loader.ts` 读 data.lock 并填 `datasets`**

在 `src/loader.ts` 顶部 import 追加（与现有 import 同区）：
```ts
import { parseDataManifest } from "./data/manifest.js";
```

在 `loadTask` 里、`const scorers = parseScorers(metaRaw.scoring);` 一行**下方**插入：
```ts
  const dataLockPath = join(dir, "data.lock");
  const datasets = existsSync(dataLockPath)
    ? parseDataManifest(readYaml(dataLockPath)).datasets
    : [];
```

把构造对象改成包含 `datasets`：
```ts
  const task: Task = { meta, turns, askUser, rubric, scorers, datasets, dir };
```

- [ ] **Step 5: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`loader-data.test.js` 3 个用例通过；**Phase 1 的 scoring golden 等全部仍绿**；总 `# fail 0`（共 35）。

- [ ] **Step 6: 提交**

```bash
git add src/task.ts src/loader.ts src/loader-data.test.ts
git commit -m "feat(loader): 读 data.lock 填充 task.datasets(无则空，种子任务不受影响)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `bp-bench fetch` 子命令

**Files:**
- Modify: `src/cli.ts`（新增 `fetch` 子命令）

- [ ] **Step 1: 读现有 cli.ts 结构**

Run: `. "$HOME/.nvm/nvm.sh"; sed -n '1,60p' src/cli.ts`
确认：`cmd = argv[0]`；已有 `if (cmd === "list")` / `if (cmd === "run")` / `if (cmd === "leaderboard")` 分支；`listTaskDirs()` 与 `loadTask` 已 import；末尾有用法行。

- [ ] **Step 2: 在 `src/cli.ts` 顶部 import 区加 resolveManifest**

把现有 import（含 `import { loadTask } from "./loader.js";`）那一段里，新增一行：
```ts
import { resolveManifest } from "./data/index.js";
```

- [ ] **Step 3: 在 `leaderboard` 分支之后、最后的"用法"行之前插入 `fetch` 分支**

```ts
  if (cmd === "fetch") {
    const which = argv[1];
    const dirs = which === "all" ? listTaskDirs() : listTaskDirs().filter((d) => d.endsWith("/" + which));
    if (!dirs.length) { console.error(`找不到任务：${which}`); process.exit(2); }
    for (const d of dirs) {
      const t = loadTask(d);
      if (!t.datasets.length) { console.log(`${B}${t.meta.id}${X}  (无 data.lock，跳过)`); continue; }
      console.log(`${B}— fetch ${t.meta.id}${X}  (${t.datasets.length} 数据集)`);
      const resolved = await resolveManifest({ datasets: t.datasets });
      for (const r of resolved) {
        const tag = r.fetched ? `${G}fetched${X}` : `${Y}cached${X}`;
        console.log(`  ${tag}  ${r.entry.name}  → ${r.path}`);
      }
    }
    return;
  }
```

- [ ] **Step 4: 更新末尾用法行**

把现有用法行（形如 `console.log("用法: bp-bench list | run ... | leaderboard <runsDir>");`）替换为包含 fetch：
```ts
  console.log("用法: bp-bench list | run <id|all> --base-url <url> [--version <tag>] | fetch <id|all> | leaderboard <runsDir>");
```

- [ ] **Step 5: 构建 + 烟测**

Run:
```bash
. "$HOME/.nvm/nvm.sh"; npm run build
node dist/cli.js fetch all
node dist/cli.js list | head -2
```
Expected: `fetch all` 对两个种子任务各打印 `(无 data.lock，跳过)`（它们没有 data.lock）；`list` 仍输出两行任务。退出码 0。

- [ ] **Step 6: 端到端验证 fetch 真能拉（用本地 file:// 临时任务）**

Run:
```bash
. "$HOME/.nvm/nvm.sh"
node -e '
const { mkdtempSync, mkdirSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const { createHash } = require("node:crypto");
(async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-e2e-"));
  const tasks = join(root, "tasks"); mkdirSync(tasks);
  const tdir = join(tasks, "e2e-data"); mkdirSync(join(tdir, "prompt"), { recursive: true });
  const body = "e2e-dataset-body";
  const sha = createHash("sha256").update(body).digest("hex");
  const src = join(root, "blob.bin"); writeFileSync(src, body);
  writeFileSync(join(tdir, "task.yaml"), "id: e2e-data\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: \"*.md\"\ntimeout_min: 5\nbudget_tokens: 1000\n");
  writeFileSync(join(tdir, "prompt", "turns.yaml"), "- send: hi\n");
  writeFileSync(join(tdir, "data.lock"), "datasets:\n  - name: blob\n    uri: file://" + src + "\n    sha256: " + sha + "\n    bytes: " + body.length + "\n");
  const xdg = join(root, "cache");
  const { execSync } = require("node:child_process");
  const out = execSync("node " + JSON.stringify(join(process.cwd(),"dist/cli.js")) + " fetch all --tasks " + JSON.stringify(tasks), { env: { ...process.env, XDG_CACHE_HOME: xdg }, encoding: "utf8" });
  console.log(out);
})();
'
```
Expected: 输出含 `fetched  blob  → .../cache/brainpilot-bench/<sha>/data`。

> 注：`fetch` 分支用了 `listTaskDirs()`，它依赖 `--tasks`（默认 `tasks`）。确认 cli 的 `tasksDir = arg("--tasks", "tasks")` 已存在（现状如此）。若 `fetch` 分支未读取 `--tasks`，本步会失败——`listTaskDirs` 已内部用全局 `tasksDir`，故 `--tasks` 自动生效，无需在 fetch 分支额外处理。

- [ ] **Step 7: 提交**

```bash
git add src/cli.ts
git commit -m "feat(cli): bp-bench fetch <id|all> 显式拉取任务数据集(缓存命中/下载分别标注)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: CI 文件大小门（25MB/文件、100MB/PR）

**Files:**
- Create: `scripts/check-task-size.mjs`
- Create: `.github/workflows/task-size.yml`
- Modify: `.gitignore`（防御性忽略仓内缓存）

- [ ] **Step 1: 写大小门脚本**

创建 `scripts/check-task-size.mjs`：
```js
#!/usr/bin/env node
/**
 * check-task-size.mjs — 大小门：tasks/ 下单文件 ≤25MB；一组改动文件总量 ≤100MB。
 * 用法：node scripts/check-task-size.mjs <file1> <file2> ...
 *   不带参数：扫描 tasks/ 下所有被 git 跟踪的文件。
 * 超限以非零退出码失败（CI 用）。data body 必须走 data.lock/OSS，不进 git。
 */
import { statSync } from "node:fs";
import { execSync } from "node:child_process";

const PER_FILE = 25 * 1024 * 1024;   // 25 MB
const TOTAL = 100 * 1024 * 1024;     // 100 MB

function trackedTaskFiles() {
  const out = execSync("git ls-files tasks/", { encoding: "utf8" });
  return out.split("\n").map((s) => s.trim()).filter(Boolean);
}

const args = process.argv.slice(2).filter(Boolean);
const files = (args.length ? args : trackedTaskFiles()).filter((f) => f.startsWith("tasks/"));

let total = 0;
const tooBig = [];
for (const f of files) {
  let size = 0;
  try { size = statSync(f).size; } catch { continue; } // 删除的文件忽略
  total += size;
  if (size > PER_FILE) tooBig.push([f, size]);
}

const MB = (n) => (n / 1024 / 1024).toFixed(1) + "MB";
let failed = false;
for (const [f, size] of tooBig) {
  console.error(`✗ ${f} = ${MB(size)} 超过单文件上限 25MB —— 大数据必须走 data.lock/OSS，不进 git`);
  failed = true;
}
if (total > TOTAL) {
  console.error(`✗ tasks/ 改动总量 ${MB(total)} 超过 100MB`);
  failed = true;
}
if (failed) process.exit(1);
console.log(`✓ 大小门通过（${files.length} 文件，合计 ${MB(total)}）`);
```

- [ ] **Step 2: 本地验证脚本（通过路径）**

Run: `. "$HOME/.nvm/nvm.sh"; node scripts/check-task-size.mjs`
Expected: `✓ 大小门通过（N 文件，合计 X.XMB）`，退出码 0（种子任务都是小文件）。

- [ ] **Step 3: 本地验证脚本（失败路径）**

Run:
```bash
. "$HOME/.nvm/nvm.sh"
node -e '
const { writeFileSync, mkdirSync } = require("node:fs");
mkdirSync("tasks/_sizecheck_tmp", { recursive: true });
writeFileSync("tasks/_sizecheck_tmp/big.bin", Buffer.alloc(26*1024*1024));
'
node scripts/check-task-size.mjs tasks/_sizecheck_tmp/big.bin; echo "exit=$?"
rm -rf tasks/_sizecheck_tmp
```
Expected: 打印 `✗ tasks/_sizecheck_tmp/big.bin = 26.0MB 超过单文件上限 25MB ...`，`exit=1`。

- [ ] **Step 4: 写 GitHub Actions workflow**

创建 `.github/workflows/task-size.yml`：
```yaml
name: task-size

on:
  pull_request:
    paths:
      - "tasks/**"
  push:
    branches: [main]
    paths:
      - "tasks/**"

jobs:
  size-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: 检查 tasks/ 改动文件大小（25MB/文件，100MB/总量）
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            BASE="${{ github.event.pull_request.base.sha }}"
            HEAD="${{ github.event.pull_request.head.sha }}"
            FILES=$(git diff --name-only --diff-filter=ACM "$BASE" "$HEAD" -- 'tasks/**' || true)
          else
            FILES=$(git diff --name-only --diff-filter=ACM "${{ github.event.before }}" "${{ github.sha }}" -- 'tasks/**' || true)
          fi
          if [ -z "$FILES" ]; then echo "无 tasks/ 改动"; exit 0; fi
          echo "$FILES" | tr '\n' ' '
          node scripts/check-task-size.mjs $FILES
```

- [ ] **Step 5: 校验 workflow YAML 合法**

Run:
```bash
. "$HOME/.nvm/nvm.sh"
node -e "const y=require('yaml');const fs=require('fs');y.parse(fs.readFileSync('.github/workflows/task-size.yml','utf8'));console.log('workflow YAML 合法')"
```
Expected: `workflow YAML 合法`。

- [ ] **Step 6: `.gitignore` 防御性忽略仓内缓存**

在 `.gitignore` 末尾追加：
```
# 内容寻址缓存默认在仓外(XDG)；防御性忽略意外落在仓内的缓存
.cache/
```

- [ ] **Step 7: 提交**

```bash
git add scripts/check-task-size.mjs .github/workflows/task-size.yml .gitignore
git commit -m "ci(data): tasks/ 文件大小门(25MB/文件,100MB/PR)强制大数据走 data.lock/OSS

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 文档 + data.lock 示例（贡献者参考）

**Files:**
- Create: `tasks/_example/data.lock.example`
- Modify: `README.md`（data.lock 一节）

- [ ] **Step 1: 写 data.lock 示例**

创建 `tasks/_example/data.lock.example`：
```yaml
# data.lock 示例 —— 大数据集 body 永不进 git，按 sha256 内容寻址懒拉取。
# 放在 tasks/<id>/data.lock。run/fetch 时按 uri scheme 拉取、校验 sha256、落本地缓存。
datasets:
  # 公开只读 OSS 桶（推荐）：oss://<bucket>/<key>，自动重写成公共 https 端点。
  # 端点默认 oss-cn-hangzhou.aliyuncs.com，可用环境 OSS_PUBLIC_ENDPOINT 覆盖。
  - name: connectome-mouse-v2
    uri: oss://brainpilot-bench/connectome/mouse-v2/slice-00.parquet
    sha256: 0000000000000000000000000000000000000000000000000000000000000000
    bytes: 87432119123
    format: parquet
  # 也支持任意公共 https：
  - name: atlas-regions
    uri: https://example.org/datasets/atlas/regions.csv
    sha256: 1111111111111111111111111111111111111111111111111111111111111111
    bytes: 1048576
    format: csv
  # 本地文件（开发/测试用）：
  - name: local-fixture
    uri: file:///abs/path/to/fixture.bin
    sha256: 2222222222222222222222222222222222222222222222222222222222222222
    bytes: 1024
```

> 注：示例放 `tasks/_example/` 且文件名带 `.example` 后缀，`listTaskDirs()` 只认含 `task.yaml` 的目录，故 `_example` 不会被当成任务加载。

- [ ] **Step 2: 验证示例不污染任务列表**

Run: `. "$HOME/.nvm/nvm.sh"; node dist/cli.js list`
Expected: 仍只两行（survey + trends），`_example` 不出现。

- [ ] **Step 3: README 加 data.lock 一节**

在 `README.md` 的「Contributing a task」表格之后追加一节：
```markdown
## Large datasets — `data.lock`

Dataset bodies are **never committed to git** (CI enforces ≤25MB/file under `tasks/`). A task that needs data ships a `data.lock` content-addressed manifest; the harness lazily fetches by `uri` scheme, verifies `sha256`, and caches under `$XDG_CACHE_HOME/brainpilot-bench/<sha256>/`.

| Field | Meaning |
|------|---------|
| `name` | unique-per-task dataset name |
| `uri` | `oss://bucket/key` (public read-only, rewritten to a public https endpoint), `https://…`, or `file://…` |
| `sha256` | 64-hex content hash — the cache key + integrity check |
| `bytes` | expected size (audit) |
| `format` | optional tag (parquet/csv/…) |

Pull a task's datasets explicitly:

```bash
bp-bench fetch <taskId|all>
```

See `tasks/_example/data.lock.example`. Public OSS endpoint defaults to `oss-cn-hangzhou.aliyuncs.com` (override with `OSS_PUBLIC_ENDPOINT`).
```

- [ ] **Step 4: 提交**

```bash
git add tasks/_example/data.lock.example README.md
git commit -m "docs(data): data.lock 示例 + README 大数据集一节

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 验收标准（Phase 2 完成定义）

- `npm run typecheck && npm run build && npm test` 全绿。测试总数 = Phase 1 的 13 + 本期新增（manifest 6 + cache 4 + fetch 6 + resolve 3 + loader-data 3 = 22）= **35**，`# fail 0`。
- **种子任务行为不变**：`bp-bench list` 仍两行；两个种子任务 `datasets=[]`；Phase 1 的 scoring golden 仍逐字节通过。
- **零新依赖**：`package.json` dependencies 仍只有 `@brainpilot/protocol` + `yaml`（没有 `ali-oss` 或任何 fetch polyfill）。
- **离线可测**：data 子系统全部用本地 tmp 文件 + `file://` 测试，不依赖网络。
- **端到端**：`bp-bench fetch` 能对一个 `file://` data.lock 真拉取→校验→落缓存（Task 6 Step 6 证明）；sha256 不匹配会报错且不留半截缓存（resolve.test 证明）。
- **大小门**：`scripts/check-task-size.mjs` 通过/失败路径都验证过；CI workflow YAML 合法。
- **公开 API**：`@brainpilot/bench` 主入口 + `./data` 子路径导出 `parseDataManifest`/`resolveManifest`/`resolveDataset`/`registerFetcher`/`getFetcher`/`hasFetcher`/`cachePathFor` 等。

## 自检记录（writing-plans self-review）

- **Spec 覆盖**：实现 spec §3（数据集分布）+ §9 Phase 2。`data.lock` 内容寻址清单(name/uri/sha256/bytes/format)=Task1；XDG sha256 缓存=Task2；scheme→fetcher(oss/https/file)=Task3；查缓存/校验/落盘编排=Task4；loader 填 `task.datasets`=Task5；显式拉取入口=Task6；25MB/100MB CI 门=Task7；示例+README=Task8。**明确不做**：把数据 stage 进被测 workspace（协议无上传路由，留 Phase 3 SUT adapter）——已在 Architecture 与决策中写明，非遗漏。私有 OSS 鉴权（决策=公开只读桶）——预留 `registerFetcher` 扩展点，不实现。
- **Placeholder 扫描**：无 TBD/TODO；每个改动步骤给完整代码 + 确切命令 + 预期输出。
- **类型一致性**：跨 Task 统一 `DatasetEntry{name,uri,sha256,bytes,format?}`、`DataManifest{datasets}`、`ResolvedDataset{entry,path,fetched}`、`FetchRequest{uri,destPath}`、`Fetcher`、`parseDataManifest`、`cacheDir/cachePathFor/isCached/verifySha256/sha256File`、`registerFetcher/getFetcher/hasFetcher/listFetchers/schemeOf/ossToHttps`、`resolveDataset/resolveManifest`、`Task.datasets`。Task1 先落 `DatasetEntry`，Task5 才在 `task.ts` 引用它（`import type`，无运行时反向依赖）——顺序无前向引用。`Task.datasets` 在 Task5 加入构造对象，与 loader 同步改，无破窗中间态。
