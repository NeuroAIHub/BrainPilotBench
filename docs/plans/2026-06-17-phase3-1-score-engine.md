# Phase 3-I — 产物回收 + `bp-bench score` 评分引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 agent 跑出的产物文件回收进 run bundle，并新增 `bp-bench score <runDir>` 命令——从 bundle 构造 `ScoreContext`、真跑任务声明的 scorer、把结果写成 `scores.json`。这是 Phase 3 两个真 scorer（exec-script / rubric-judge）共同的地基。

**Architecture:** 保留 SWE-bench 的 run/eval 分离：**run 阶段**捕获 bundle（events + 产物），**score 阶段**离线在 bundle 上跑 scorer。产物回收做成可插拔 `ArtifactSource`（先实现文件系统同机版：从 `--workspace-root/<sessionId>` 按 `expectedArtifacts` glob 拷进 `<runDir>/artifacts/`；HTTP 版留 seam）。`score` 命令读 bundle → 建 `ScoreContext`（`workspaceFiles` glob 落在 `<runDir>/artifacts/`）→ 跑 `task.scorers` → 写 `scores.json`。本计划不实现 exec/judge 评分体（Plan 3-II/3-III）；rubric scorer 仍返回 `unscored` 桩，但评分引擎的管道是真的、被测过的。

**Tech Stack:** TypeScript (NodeNext, strict) → `tsc` → `dist/`；`node --test` 跑 `dist/**/*.test.js`；**零新运行时依赖**——`node:fs/promises` 的 `glob`（Node 22+ 内置，环境 v24 已验证可用）+ `node:fs` 的 `globSync`/`cpSync` 拷贝。Node ≥ 22。

## Global Constraints

- **零新运行时依赖**：不得 `npm install` 任何新包。只用 Node 内置 + 已有 `yaml` + `@brainpilot/protocol`。
- 构建 `npm run build`（tsc，rootDir `src`→`dist`，NodeNext strict）；测试 `npm test`（`node --test "dist/**/*.test.js"`）；typecheck `npm run typecheck`。
- TS-TDD：测试 `.ts` 编译成 `dist/**/*.test.js` 再跑。引用不存在的导出 → `npm run build` 编译失败 = RED；逻辑未实现 → `npm test` 断言失败 = RED。
- 跑命令前若 `node` 不在 PATH：先 `. "$HOME/.nvm/nvm.sh"`（Node v24）。
- 提交信息结尾固定加：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 当前在 `main`。**Task 0 先开分支。** 现有 37 单测必须保持全绿（含 Phase 1 scoring golden 逐字节）。

### 开分支（Task 0，必须先做）

- [ ] 运行：
```bash
cd /Users/lucasli/Desktop/BrainPilot/repos/brainpilot-benchmark
git checkout main && git pull
git checkout -b feat/phase3-score-engine
```

## 文件结构（本计划落子）

| 文件 | 职责 |
|---|---|
| `src/artifacts.ts` | 创建。`ArtifactSource` 接口 + `filesystemArtifactSource(root)` + `captureArtifacts(source, sessionId, globs, destDir)` |
| `src/artifacts.test.ts` | 创建。filesystem source 按 glob 回收到 destDir |
| `src/score.ts` | 创建。`RunBundle`/`ScorerRunResult`/`RunScores` 类型 + `bundleWorkspaceFiles(runDir)` + `runScorers(task, bundle)` |
| `src/score.test.ts` | 创建。fixture bundle + 注册的测试 scorer → 结果；workspaceFiles glob 落 artifacts/ |
| `src/cli.ts` | 修改。`run` 加 `--workspace-root` 回收产物 + signals 加 taskId；新增 `score <runDir>` 子命令 |
| `src/index.ts` | 修改。`export * from "./artifacts.js"` + `export * from "./score.js"` |
| `package.json` | 修改。`exports` 加 `./artifacts` 与 `./score` |

> 说明：`ScoreContext`/`Scorer`/`getScorerModule` 已在 Phase 1 的 `src/scorer/` 就位，本计划复用，不改其接口。

---

## Task 1: 可插拔 ArtifactSource + 文件系统回收

**Files:**
- Create: `src/artifacts.ts`
- Test: `src/artifacts.test.ts`

**Interfaces:**
- Consumes: 无（叶子模块，只用 Node 内置）。
- Produces:
  - `interface ArtifactSource { collect(sessionId: string, globs: string[], destDir: string): Promise<string[]> }`
  - `function filesystemArtifactSource(workspaceRoot: string): ArtifactSource`
  - `function captureArtifacts(source: ArtifactSource, sessionId: string, globs: string[], destDir: string): Promise<string[]>`（薄封装，直接 `source.collect`，留给 CLI 调用点一个稳定名）
  - 均返回回收到的**相对路径数组**（相对 destDir）。

- [ ] **Step 1: 写失败测试**

创建 `src/artifacts.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { filesystemArtifactSource, captureArtifacts } from "./artifacts.js";

function withTmp<T>(fn: (dir: string) => Promise<T>): Promise<T> {
  const dir = mkdtempSync(join(tmpdir(), "bpb-art-"));
  return fn(dir).finally(() => rmSync(dir, { recursive: true, force: true }));
}

test("filesystem source: 按 glob 从 <root>/<sessionId> 回收到 destDir(保留相对路径)", async () => {
  await withTmp(async (dir) => {
    const root = join(dir, "ws");
    const sid = "sess-1";
    const ws = join(root, sid);
    mkdirSync(join(ws, "sub"), { recursive: true });
    writeFileSync(join(ws, "outline.md"), "# outline");
    writeFileSync(join(ws, "sub", "fig.png"), "PNG");
    writeFileSync(join(ws, "ignore.tmp"), "x"); // 不匹配,不该回收
    const dest = join(dir, "bundle", "artifacts");
    const got = await captureArtifacts(filesystemArtifactSource(root), sid, ["*.md", "sub/*.png"], dest);
    assert.deepEqual(got.sort(), ["outline.md", "sub/fig.png"]);
    assert.equal(readFileSync(join(dest, "outline.md"), "utf8"), "# outline");
    assert.ok(existsSync(join(dest, "sub", "fig.png")));
    assert.equal(existsSync(join(dest, "ignore.tmp")), false);
  });
});

test("filesystem source: 会话 workspace 不存在 → 回收空数组(不抛)", async () => {
  await withTmp(async (dir) => {
    const got = await captureArtifacts(filesystemArtifactSource(join(dir, "ws")), "nope", ["*.md"], join(dir, "art"));
    assert.deepEqual(got, []);
  });
});

test("filesystem source: 空 globs → 空数组", async () => {
  await withTmp(async (dir) => {
    const got = await captureArtifacts(filesystemArtifactSource(join(dir, "ws")), "s", [], join(dir, "art"));
    assert.deepEqual(got, []);
  });
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './artifacts.js'`。

- [ ] **Step 3: 写 `src/artifacts.ts`**

```ts
/**
 * artifacts.ts — 产物回收：把 agent 跑出的 workspace 文件按 expectedArtifacts glob
 * 收进 run bundle 的 artifacts/ 目录。可插拔 ArtifactSource(先实现文件系统同机版,
 * HTTP 版留 seam——bench 与引擎同机跑时直接读部署的 workspace 目录,不改协议)。
 */
import { glob, cp, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";

/** 一个产物来源(对称于 fetcher/scorer 的可插拔模式)。 */
export interface ArtifactSource {
  /** 把 sessionId 这次会话里匹配 globs 的产物拷进 destDir;返回相对 destDir 的路径数组。 */
  collect(sessionId: string, globs: string[], destDir: string): Promise<string[]>;
}

/** 文件系统同机版:产物在 <workspaceRoot>/<sessionId>/ 下。 */
export function filesystemArtifactSource(workspaceRoot: string): ArtifactSource {
  return {
    async collect(sessionId, globs, destDir) {
      if (!globs.length) return [];
      const ws = join(workspaceRoot, sessionId);
      if (!existsSync(ws)) return [];
      const rels: string[] = [];
      for await (const rel of glob(globs, { cwd: ws })) {
        const src = join(ws, rel);
        const dst = join(destDir, rel);
        await mkdir(dirname(dst), { recursive: true });
        await cp(src, dst, { recursive: true });
        rels.push(rel);
      }
      return rels.sort();
    },
  };
}

/** CLI 调用点的稳定封装。 */
export function captureArtifacts(
  source: ArtifactSource,
  sessionId: string,
  globs: string[],
  destDir: string,
): Promise<string[]> {
  return source.collect(sessionId, globs, destDir);
}
```

注意：`glob` 来自 `node:fs/promises`（Node 22+ 内置，v24 已验证），接受 `string[]` 模式和 `{ cwd }`，返回相对 cwd 的异步可迭代路径。若运行时打印 experimental 警告不影响功能；不要为此引入任何外部 glob 依赖。

- [ ] **Step 4: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`artifacts.test.js` 3 个用例通过；总 `# fail 0`（含既有 37，共 40）。

- [ ] **Step 5: 提交**

```bash
git add src/artifacts.ts src/artifacts.test.ts
git commit -m "feat(artifacts): 可插拔 ArtifactSource + 文件系统同机产物回收

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 评分引擎 `runScorers`(从 bundle 跑 scorer)

**Files:**
- Create: `src/score.ts`
- Test: `src/score.test.ts`

**Interfaces:**
- Consumes:
  - `Task`（来自 `./task.js`，有 `meta.id`、`scorers: ScorerSpec[]`、`meta.expectedArtifacts`）。
  - `getScorerModule(kind)` + `ScoreContext`/`ScoreResult`（来自 `./scorer/registry.js` / `./scorer/types.js`）。`ScoreContext = { task, runDir, events, signals, workspaceFiles: (glob: string) => string[] }`。`ScorerModule.build(spec, task)` 返回 `Scorer = (ctx) => Promise<ScoreResult>`。
- Produces:
  - `interface RunBundle { runDir: string; runId: string; version: string; events: unknown[]; signals: Record<string, unknown> }`
  - `interface ScorerRunResult { kind: string; value: Record<string, number> | number; verdict?: "pass"|"partial"|"fail"; explanation?: string; unscored?: boolean }`
  - `interface RunScores { taskId: string; runId: string; version: string; scoredAt: string; results: ScorerRunResult[] }`
  - `function bundleWorkspaceFiles(runDir: string): (glob: string) => string[]`（glob 落在 `<runDir>/artifacts/`，返回绝对路径）
  - `function runScorers(task: Task, bundle: RunBundle, scoredAt: string): Promise<RunScores>`

- [ ] **Step 1: 写失败测试**

创建 `src/score.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runScorers, bundleWorkspaceFiles, type RunBundle } from "./score.js";
import { registerScorer } from "./scorer/registry.js";
import type { Task } from "./task.js";

function fakeTask(scorerKinds: string[]): Task {
  return {
    meta: { id: "t1", domain: "d", summary: "s", expectedArtifacts: [{ workspace: "*.md" }], timeoutMin: 5, budgetTokens: 1000, requires: {} },
    turns: [{ send: "hi" }],
    askUser: {},
    rubric: { dimensions: ["correctness"] },
    scorers: scorerKinds.map((kind) => ({ kind })),
    datasets: [],
    dir: "/tmp/x",
  };
}

test("bundleWorkspaceFiles: glob 落在 <runDir>/artifacts/ 返回绝对路径", () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-score-"));
  try {
    mkdirSync(join(dir, "artifacts"), { recursive: true });
    writeFileSync(join(dir, "artifacts", "outline.md"), "x");
    writeFileSync(join(dir, "artifacts", "other.txt"), "y");
    const wf = bundleWorkspaceFiles(dir);
    const md = wf("*.md");
    assert.equal(md.length, 1);
    assert.ok(md[0].endsWith(join("artifacts", "outline.md")));
    assert.ok(md[0].startsWith("/")); // 绝对路径
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runScorers: 跑注册的测试 scorer,收集其 ScoreResult", async () => {
  // 注册一个测试 scorer:读 workspaceFiles 数量当分数
  registerScorer("test-count", {
    outputs: () => ["count"],
    build: () => async (ctx) => ({ value: { count: ctx.workspaceFiles("*.md").length } }),
  });
  const dir = mkdtempSync(join(tmpdir(), "bpb-score-"));
  try {
    mkdirSync(join(dir, "artifacts"), { recursive: true });
    writeFileSync(join(dir, "artifacts", "a.md"), "x");
    const bundle: RunBundle = { runDir: dir, runId: "t1-v", version: "v", events: [], signals: {} };
    const out = await runScorers(fakeTask(["test-count"]), bundle, "2026-06-17T00:00:00.000Z");
    assert.equal(out.taskId, "t1");
    assert.equal(out.results.length, 1);
    assert.equal(out.results[0].kind, "test-count");
    assert.deepEqual(out.results[0].value, { count: 1 });
    assert.equal(out.scoredAt, "2026-06-17T00:00:00.000Z");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runScorers: rubric-judge 桩返回 unscored 被如实记录", async () => {
  await import("./scorer/index.js"); // 触发 rubric 注册
  const dir = mkdtempSync(join(tmpdir(), "bpb-score-"));
  try {
    mkdirSync(join(dir, "artifacts"), { recursive: true });
    const bundle: RunBundle = { runDir: dir, runId: "t1-v", version: "v", events: [], signals: {} };
    const out = await runScorers(fakeTask(["rubric-judge"]), bundle, "ts");
    assert.equal(out.results[0].kind, "rubric-judge");
    assert.equal(out.results[0].unscored, true);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './score.js'`。

- [ ] **Step 3: 写 `src/score.ts`**

```ts
/**
 * score.ts — 离线评分引擎:从 run bundle 构造 ScoreContext、真跑任务声明的 scorer、
 * 收集结果成 RunScores。(SWE-bench run/eval 分离的 eval 侧。)
 */
import { globSync } from "node:fs";
import { join } from "node:path";
import type { Task } from "./task.js";
import { getScorerModule } from "./scorer/registry.js";
import type { ScoreContext } from "./scorer/types.js";

/** run 阶段产出的 bundle(score 阶段的输入)。 */
export interface RunBundle {
  runDir: string;
  runId: string;
  version: string;
  events: unknown[];
  signals: Record<string, unknown>;
}

/** 一个 scorer 跑出来的结果(扁平化自 ScoreResult,便于落 JSON)。 */
export interface ScorerRunResult {
  kind: string;
  value: Record<string, number> | number;
  verdict?: "pass" | "partial" | "fail";
  explanation?: string;
  unscored?: boolean;
}

/** 一次评分的全部 scorer 结果。 */
export interface RunScores {
  taskId: string;
  runId: string;
  version: string;
  scoredAt: string;
  results: ScorerRunResult[];
}

/** ScoreContext.workspaceFiles 实现:glob 落在 <runDir>/artifacts/,返回绝对路径。 */
export function bundleWorkspaceFiles(runDir: string): (glob: string) => string[] {
  const artifactsDir = join(runDir, "artifacts");
  return (pattern: string) =>
    globSync(pattern, { cwd: artifactsDir }).map((rel) => join(artifactsDir, rel));
}

/** 跑任务声明的全部 scorer,收集结果。 */
export async function runScorers(task: Task, bundle: RunBundle, scoredAt: string): Promise<RunScores> {
  const ctx: ScoreContext = {
    task,
    runDir: bundle.runDir,
    events: bundle.events,
    signals: bundle.signals,
    workspaceFiles: bundleWorkspaceFiles(bundle.runDir),
  };
  const results: ScorerRunResult[] = [];
  for (const spec of task.scorers) {
    const scorer = getScorerModule(spec.kind).build(spec, task);
    const r = await scorer(ctx);
    results.push({
      kind: spec.kind,
      value: r.value,
      verdict: r.verdict,
      explanation: r.explanation,
      unscored: r.unscored,
    });
  }
  return { taskId: task.meta.id, runId: bundle.runId, version: bundle.version, scoredAt, results };
}
```

注意：`globSync` 来自 `node:fs`（Node 22+ 内置）。`ScoreContext.workspaceFiles` 在 Phase 1 定义为 `(glob: string) => string[]`（单个 glob 字符串），本实现匹配该签名。

- [ ] **Step 4: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`score.test.js` 3 个用例通过；总 `# fail 0`（共 43）。

- [ ] **Step 5: 提交**

```bash
git add src/score.ts src/score.test.ts
git commit -m "feat(score): runScorers 评分引擎(从 bundle 建 ScoreContext 跑 scorer 收结果)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `run --workspace-root` 回收产物 + signals 记 taskId

**Files:**
- Modify: `src/cli.ts`（`run` 分支）

**Interfaces:**
- Consumes: `captureArtifacts` + `filesystemArtifactSource`（来自 `./artifacts.js`，Task 1）。task 的 globs = `task.meta.expectedArtifacts.map(a => a.workspace)`。
- Produces: 无新导出；行为变化——`run` 接受 `--workspace-root <dir>`，给定时把产物回收进 `<runDir>/artifacts/`，并在 `signals.json` 增 `taskId` 字段（score 命令靠它定位任务）。

- [ ] **Step 1: 读现有 cli.ts run 分支**

Run: `. "$HOME/.nvm/nvm.sh"; sed -n '39,64p' src/cli.ts`
确认 `run` 分支结构（`const res = await runner.run(t)`、写 events.jsonl/signals.json/scoresheet.json 的那几行）。

- [ ] **Step 2: 在 `src/cli.ts` 顶部 import 区加 artifacts**

在含 `import { resolveManifest } from "./data/index.js";` 那段后追加一行：
```ts
import { captureArtifacts, filesystemArtifactSource } from "./artifacts.js";
```

- [ ] **Step 3: 改 `run` 分支：signals 记 taskId + 可选回收产物**

把 `run` 分支里写 `signals.json` 的那一行：
```ts
      writeFileSync(join(runDir, "signals.json"), JSON.stringify({ ...res.signals, reason: res.reason, sessionId: res.sessionId, version }, null, 2));
```
改成（增 `taskId`）：
```ts
      writeFileSync(join(runDir, "signals.json"), JSON.stringify({ taskId: t.meta.id, ...res.signals, reason: res.reason, sessionId: res.sessionId, version }, null, 2));
```

在该 `run` 分支里、写完 `scoresheet.json` 之后、那行 `const tag = ...` 之前，插入产物回收：
```ts
      const wsRoot = arg("--workspace-root");
      if (wsRoot) {
        const globs = t.meta.expectedArtifacts.map((a) => a.workspace);
        const got = await captureArtifacts(filesystemArtifactSource(wsRoot), res.sessionId, globs, join(runDir, "artifacts"));
        console.log(`  artifacts: ${got.length} 个回收 → ${join(runDir, "artifacts")}`);
      }
```

- [ ] **Step 4: 构建 + 既有测试仍绿**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；总 `# fail 0`（仍 43——本任务无新单测，回收逻辑已在 Task 1 测过，CLI 接线靠 build + Task 4 端到端覆盖）。

- [ ] **Step 5: 提交**

```bash
git add src/cli.ts
git commit -m "feat(cli): run --workspace-root 回收产物进 bundle + signals 记 taskId

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

> 注：`run` 需要 `--base-url` 连真实部署，无法纯本地端到端;产物回收逻辑由 Task 1 单测保证，CLI 接线由 build 类型检查 + Task 4 的 score 端到端串联验证。

---

## Task 4: `bp-bench score <runDir>` 命令

**Files:**
- Modify: `src/cli.ts`（新增 `score` 分支）

**Interfaces:**
- Consumes: `runScorers` + `RunBundle`（来自 `./score.js`，Task 2）；`loadTask`（已 import）。从 `<runDir>/signals.json` 读 `{taskId, version}`，从 `<runDir>/events.jsonl` 读 events。
- Produces: 无新导出；`bp-bench score <runDir> [--tasks <dir>]` 写 `<runDir>/scores.json`(RunScores) 并打印每个 scorer 的结论。

- [ ] **Step 1: 在 `src/cli.ts` 顶部 import 区加 score**

在 Task 3 加的 artifacts import 后追加：
```ts
import { runScorers, type RunBundle } from "./score.js";
```

- [ ] **Step 2: 在 `leaderboard` 分支之后、`fetch` 分支之前(或任意命令分支之间)插入 `score` 分支**

```ts
  if (cmd === "score") {
    const runDir = argv[1];
    if (!runDir || !existsSync(join(runDir, "signals.json"))) {
      console.error("用法: bp-bench score <runDir>（需含 signals.json 的 run 目录）"); process.exit(2);
    }
    const signals = JSON.parse(readFileSync(join(runDir, "signals.json"), "utf8"));
    const taskId = signals.taskId;
    if (!taskId) { console.error("signals.json 缺 taskId（用新版 run 重跑，或手动补）"); process.exit(2); }
    const dir = listTaskDirs().find((d) => d.endsWith("/" + taskId));
    if (!dir) { console.error(`找不到任务：${taskId}`); process.exit(2); }
    const t = loadTask(dir);
    const evPath = join(runDir, "events.jsonl");
    const events = existsSync(evPath)
      ? readFileSync(evPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
      : [];
    const bundle: RunBundle = { runDir, runId: signals.runId ?? `${taskId}-${signals.version}`, version: signals.version ?? "unknown", events, signals };
    const scores = await runScorers(t, bundle, new Date().toISOString());
    writeFileSync(join(runDir, "scores.json"), JSON.stringify(scores, null, 2));
    console.log(`${B}— score ${taskId}${X}  → ${join(runDir, "scores.json")}`);
    for (const r of scores.results) {
      const v = r.unscored ? `${Y}unscored${X}` : (typeof r.value === "number" ? String(r.value) : JSON.stringify(r.value));
      console.log(`  ${r.kind}: ${v}${r.verdict ? ` [${r.verdict}]` : ""}`);
    }
    return;
  }
```

- [ ] **Step 3: 更新末尾用法行**

把现有用法行替换为含 `score`：
```ts
  console.log("用法: bp-bench list | run <id|all> --base-url <url> [--version <tag>] [--workspace-root <dir>] | fetch <id|all> | score <runDir> | leaderboard <runsDir>");
```

- [ ] **Step 4: 构建 + 端到端烟测(手搓 bundle，无需部署)**

Run:
```bash
. "$HOME/.nvm/nvm.sh"; npm run build
node -e '
const { mkdtempSync, mkdirSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const { execSync } = require("node:child_process");
const root = mkdtempSync(join(tmpdir(), "bpb-score-e2e-"));
// 用真实种子任务 neuro-survey-attention(scorers 缺省 rubric-judge)
const runDir = join(root, "run"); mkdirSync(join(runDir, "artifacts"), { recursive: true });
writeFileSync(join(runDir, "artifacts", "outline.md"), "# 注意力机制综述提纲\n...");
writeFileSync(join(runDir, "events.jsonl"), JSON.stringify({ type: "TEXT_MESSAGE_CONTENT", content: "草拟提纲" }) + "\n");
writeFileSync(join(runDir, "signals.json"), JSON.stringify({ taskId: "neuro-survey-attention", runId: "neuro-survey-attention-vTEST", version: "vTEST", sessionId: "s1" }));
const out = execSync("node " + JSON.stringify(join(process.cwd(),"dist/cli.js")) + " score " + JSON.stringify(runDir), { encoding: "utf8" });
process.stdout.write(out);
process.stdout.write("--- scores.json ---\n" + require("node:fs").readFileSync(join(runDir, "scores.json"), "utf8") + "\n");
'
```
Expected: 打印 `— score neuro-survey-attention` + `rubric-judge: unscored`；`scores.json` 含 `{taskId:"neuro-survey-attention", results:[{kind:"rubric-judge", unscored:true, ...}]}`。（rubric-judge 真评分体在 Plan 3-III；本计划证明引擎管道通。）

- [ ] **Step 5: 提交**

```bash
git add src/cli.ts
git commit -m "feat(cli): bp-bench score <runDir> 离线跑 scorer 写 scores.json

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 暴露公开 API + 收尾

**Files:**
- Modify: `src/index.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: `./artifacts.js`、`./score.js`。
- Produces: 主入口 + `./artifacts`、`./score` 子路径导出。

- [ ] **Step 1: `src/index.ts` 导出**

在 `export * from "./data/index.js";` 一行下方追加：
```ts
export * from "./artifacts.js";
export * from "./score.js";
```

若 `tsc` 报重复导出冲突 STOP 报告（不应发生——artifacts/score 导出名 ArtifactSource/captureArtifacts/filesystemArtifactSource/RunBundle/RunScores/ScorerRunResult/runScorers/bundleWorkspaceFiles 与现有无重名）。

- [ ] **Step 2: `package.json` exports 加两个子路径**

把：
```json
    "./data": "./dist/data/index.js"
  },
```
改成：
```json
    "./data": "./dist/data/index.js",
    "./artifacts": "./dist/artifacts.js",
    "./score": "./dist/score.js"
  },
```

- [ ] **Step 3: 全量 typecheck + build + test**

Run: `. "$HOME/.nvm/nvm.sh"; npm run typecheck && npm run build && npm test`
Expected: 三者全过；总 `# fail 0`（共 43：既有 37 + artifacts 3 + score 3）。

- [ ] **Step 4: 验证公开 API 解析**

Run:
```bash
. "$HOME/.nvm/nvm.sh"
node -e "import('./dist/index.js').then(m=>console.log('runScorers:',typeof m.runScorers,'| captureArtifacts:',typeof m.captureArtifacts,'| filesystemArtifactSource:',typeof m.filesystemArtifactSource,'| bundleWorkspaceFiles:',typeof m.bundleWorkspaceFiles))"
```
Expected: 四者均 `function`。

- [ ] **Step 5: 提交**

```bash
git add src/index.ts package.json
git commit -m "feat(score): 暴露 artifacts/score 公开 API + ./artifacts ./score 子路径

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 验收标准（Plan 3-I 完成定义）

- `npm run typecheck && npm run build && npm test` 全绿，**43 单测**（既有 37 + artifacts 3 + score 3），`# fail 0`，含 Phase 1 scoring golden 逐字节。
- **零新依赖**：`package.json` dependencies 仍只有 `@brainpilot/protocol` + `yaml`。
- **产物回收**：`captureArtifacts(filesystemArtifactSource(root), sid, globs, dest)` 按 glob 从 `<root>/<sid>` 拷进 dest（Task 1 测过保留相对路径、缺会话不抛、空 globs 空数组）。
- **评分引擎**：`runScorers(task, bundle, scoredAt)` 建 ScoreContext（workspaceFiles glob 落 `<runDir>/artifacts/`）跑 scorer 收 RunScores（Task 2 测过测试 scorer 出分、rubric 桩 unscored）。
- **端到端**：`bp-bench score <runDir>` 在手搓 bundle 上跑通、写 `scores.json`（Task 4 烟测，无需部署）；`run --workspace-root` 接线就位（Task 3，真跑需部署）。
- **seam 就位**：`ArtifactSource` 可插拔（HTTP 版未来 `registerArtifactSource` 式扩展不碰 core）；`scores.json` 是 Plan 3-II(exec)/3-III(judge) 真 scorer 落分的载体；rubric-judge 真评分体填进 `src/scorer/rubric.ts` 的 build()（现 unscored 桩）即翻活。

## 自检记录（writing-plans self-review）

- **Spec 覆盖**：本计划 = Phase 3 的地基切片（产物回收 + score 命令 + 评分引擎管道），对应 master spec §4「产物回收(harness 新能力)」+ §2 Scorer 接口的运行侧。**明确不做**（后续计划）：exec-script scorer + checks/solution/sandbox（Plan 3-II）、rubric-judge 真 LLM 评分体 + 多 judge 投票（Plan 3-III）、HTTP ArtifactSource + 数据 stage 进 workspace（更后）。文件系统同机回收 = 已定分叉，HTTP 留 `ArtifactSource` 接口 seam。
- **Placeholder 扫描**：无 TBD/TODO；每步给完整代码 + 确切命令 + 预期输出。
- **类型一致性**：跨 Task 统一 `ArtifactSource.collect(sessionId,globs,destDir)→Promise<string[]>`、`filesystemArtifactSource`、`captureArtifacts`、`RunBundle{runDir,runId,version,events,signals}`、`ScorerRunResult{kind,value,verdict?,explanation?,unscored?}`、`RunScores{taskId,runId,version,scoredAt,results}`、`bundleWorkspaceFiles(runDir)→(glob)=>string[]`、`runScorers(task,bundle,scoredAt)`。复用 Phase 1 的 `ScoreContext{task,runDir,events,signals,workspaceFiles}`、`getScorerModule`、`ScorerModule.build`——签名一致（workspaceFiles 单 glob 字符串）。Task 2 的测试 scorer 经 `registerScorer` 注册，与 Phase 1 注册表同款。
