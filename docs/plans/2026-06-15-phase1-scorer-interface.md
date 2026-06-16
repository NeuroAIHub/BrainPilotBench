# Phase 1 — Scorer 接口重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `scoring.ts` 里硬编码的 rubric 逻辑抽到一个可插拔的 Scorer 接口 + 注册表后面，**不改变任何外部行为**——两个种子任务必须产出与今天逐字节一致的 scoresheet。

**Architecture:** 新增 `src/scorer/`（types + registry + rubric 模块）。任务格式新增可选 `scoring.scorers`（缺省 = 单 `rubric-judge` over `rubric.yaml`）。`blankScoresheet` 改成从任务声明的 scorer 的 `outputs()` 推导维度，而非直接读 `task.rubric.dimensions`。Scorer 的 `build()/score()` 是为 Phase 3（judge/exec 执行）预留的承重墙，本期返回 `unscored`（rubric 由外部人/LLM 填，尚无 in-harness 执行）。

**Tech Stack:** TypeScript (NodeNext, strict) → `tsc` → `dist/`；`node --test` 跑编译后的 `dist/**/*.test.js`；`yaml` 解析。Node ≥ 22（环境为 v24）。

---

## 前置说明（执行者必读）

- 工作目录：`/Users/lucasli/Desktop/BrainPilot/repos/brainpilot-benchmark`（已在分支 `design/bench-architecture`）。
- 每次跑命令前若 `node` 不在 PATH：先 `. "$HOME/.nvm/nvm.sh"`。
- 需要装依赖时用 `npm install --registry=https://registry.npmmirror.com`（依赖已装，通常无需）。
- **TS-TDD 约定**：本仓测试是 `.ts` 编译成 `dist/**/*.test.js` 再跑。因此「验证测试失败」分两种 RED：
  - 引用尚不存在的导出 → `npm run build` **编译失败**（`has no exported member` / `Cannot find name`）就是 RED；
  - 函数已存在但逻辑未实现 → 编译过、`npm test` **断言失败**是 RED。
  每步会标明预期的 RED 形态。
- 提交信息结尾固定加：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

## 文件结构（本期落子）

| 文件 | 职责 |
|---|---|
| `src/scorer/types.ts` | 创建。`ScoreResult` / `ScoreContext` / `Scorer` / `ScorerModule` 接口（承重墙） |
| `src/scorer/registry.ts` | 创建。`Map<kind, ScorerModule>` + `registerScorer/getScorerModule/hasScorer/listScorers` |
| `src/scorer/rubric.ts` | 创建。rubric scorer 模块（`rubricDimensions` + `build`），注册 `rubric-judge`/`rubric-human` |
| `src/scorer/index.ts` | 创建。re-export types+registry，并 `import "./rubric.js"` 触发注册 |
| `src/scorer/*.test.ts` | 创建。registry / rubric / scoresheet 三组单测 |
| `src/task.ts` | 修改。新增 `ScorerSpec`、`DEFAULT_SCORERS`、`Task.scorers`、校验 |
| `src/loader.ts` | 修改。新增 `parseScorers()`，`loadTask` 填 `task.scorers` |
| `src/scoring.ts` | 修改。新增 `scoresheetDimensions()`，`blankScoresheet` 改走 scorer outputs |
| `src/index.ts` | 修改。`export * from "./scorer/index.js"` |
| `package.json` | 修改。`test` 脚本改递归 glob；`exports` 加 `./scorer` |

---

## Task 1: 测试脚本递归化 + Scorer 注册表（types + registry）

**Files:**
- Modify: `package.json`（`scripts.test`）
- Create: `src/scorer/types.ts`
- Create: `src/scorer/registry.ts`
- Test: `src/scorer/registry.test.ts`

- [ ] **Step 1: 把 test 脚本改成递归 glob（让 `dist/scorer/*.test.js` 被发现）**

把 `package.json` 里：
```json
    "test": "node --test dist/*.test.js",
```
改成：
```json
    "test": "node --test \"dist/**/*.test.js\"",
```

- [ ] **Step 2: 写失败测试**

创建 `src/scorer/registry.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { registerScorer, getScorerModule, hasScorer, listScorers } from "./registry.js";
import type { ScorerModule } from "./types.js";

const dummy: ScorerModule = {
  outputs: () => ["dim_a", "dim_b"],
  build: () => async () => ({ value: 0, unscored: true }),
};

test("registerScorer + getScorerModule round-trips", () => {
  registerScorer("dummy-kind", dummy);
  assert.equal(hasScorer("dummy-kind"), true);
  assert.deepEqual(getScorerModule("dummy-kind").outputs({ kind: "dummy-kind" } as any, {} as any), ["dim_a", "dim_b"]);
});

test("getScorerModule throws a helpful error for unknown kind", () => {
  assert.throws(() => getScorerModule("no-such-kind"), /unknown scorer kind: no-such-kind/);
  assert.ok(listScorers().includes("dummy-kind"));
});
```

- [ ] **Step 3: 跑构建验证 RED（编译失败 = 模块不存在）**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，类似 `error TS2307: Cannot find module './registry.js'` 或 `./types.js`。

- [ ] **Step 4: 写 `src/scorer/types.ts`**

```ts
/**
 * scorer/types.ts — 可插拔评分的承重墙接口（统一 rubric/exec/未来轨迹评分）。
 * 三种评分实现同一 Scorer 签名，只是函数体不同（Inspect 闭包工厂 + Protocol）。
 */
import type { Task, ScorerSpec } from "../task.js";

/** dict 值 → 每维度自动出榜；标量值用于单指标 scorer。 */
export type ScoreValue = Record<string, number> | number;

export interface ScoreResult {
  value: ScoreValue;
  verdict?: "pass" | "partial" | "fail";
  explanation?: string;
  raw?: unknown;
  /** judge/基础设施失败 → 排除出聚合，≠ fail、≠ 0。 */
  unscored?: boolean;
}

/** 喂给 scorer 的是"产物 + 轨迹"，不是 agent 本身。 */
export interface ScoreContext {
  task: Task;
  runDir: string;
  events: unknown[];                              // 完整轨迹（轨迹评分接口预留点）
  signals: Record<string, unknown>;
  workspaceFiles: (glob: string) => string[];     // 回收回来的产物
}

export type Scorer = (ctx: ScoreContext) => Promise<ScoreResult>;

/** 一个评分类别的实现：声明它产出的列 + 构建 scorer 函数。 */
export interface ScorerModule {
  /** 该 scorer 贡献到 blank scoresheet / leaderboard 的列名。 */
  outputs(spec: ScorerSpec, task: Task): string[];
  /** 构建 scorer 函数（Phase 3+ 填 judge/exec 执行体；本期 rubric 返回 unscored）。 */
  build(spec: ScorerSpec, task: Task): Scorer;
}
```

- [ ] **Step 5: 写 `src/scorer/registry.ts`**

```ts
/**
 * scorer/registry.ts — kind → ScorerModule 的开放命名注册表
 * (对照 lm-eval @register_metric / HELM MetricSpec；拒绝 BIG-bench 封闭枚举)。
 */
import type { ScorerModule } from "./types.js";

const REGISTRY = new Map<string, ScorerModule>();

export function registerScorer(kind: string, mod: ScorerModule): void {
  REGISTRY.set(kind, mod);
}

export function getScorerModule(kind: string): ScorerModule {
  const m = REGISTRY.get(kind);
  if (!m) throw new Error(`unknown scorer kind: ${kind} (registered: ${[...REGISTRY.keys()].join(", ") || "none"})`);
  return m;
}

export function hasScorer(kind: string): boolean {
  return REGISTRY.has(kind);
}

export function listScorers(): string[] {
  return [...REGISTRY.keys()];
}
```

> 注：`types.ts` 引用了 `Task`/`ScorerSpec`（来自 `../task.js`），它们在 Task 2 才新增。本 Task 的构建会因此报缺 `ScorerSpec`。为让 Task 1 独立通过，**先在 `src/task.ts` 末尾加一行占位再补全**——见 Step 6。

- [ ] **Step 6: 在 `src/task.ts` 末尾追加最小 `ScorerSpec`（Task 2 会补全其余）**

在 `src/task.ts` 文件**末尾**追加：
```ts
/** 任务声明的一个 scorer（从 task.yaml scoring.scorers 解析；详见 loader）。 */
export interface ScorerSpec {
  kind: string;
  rubric?: string;
  script?: string;
  parser?: string;
  [k: string]: unknown;
}
```

- [ ] **Step 7: 构建 + 跑测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；测试输出含 `# pass 2` / `# fail 0`（registry.test.js 两个用例通过）。

- [ ] **Step 8: 提交**

```bash
git add package.json src/scorer/types.ts src/scorer/registry.ts src/scorer/registry.test.ts src/task.ts
git commit -m "feat(scorer): Scorer 接口 + 开放命名注册表(承重墙)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 任务格式新增 `scorers` + loader 解析 + 缺省

**Files:**
- Modify: `src/task.ts`（补 `DEFAULT_SCORERS`、`Task.scorers`、`validateTask`）
- Modify: `src/loader.ts`（新增 `parseScorers`，`loadTask` 填 `scorers`）
- Test: `src/loader.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `src/loader.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { parseScorers, loadTask } from "./loader.js";
import { DEFAULT_SCORERS } from "./task.js";

const SURVEY = fileURLToPath(new URL("../tasks/neuro-survey-attention", import.meta.url));

test("parseScorers: 缺省回落 DEFAULT_SCORERS", () => {
  assert.deepEqual(parseScorers(undefined), DEFAULT_SCORERS);
  assert.deepEqual(parseScorers({}), DEFAULT_SCORERS);
});

test("parseScorers: 解析显式 scorers，保留 kind 与配置字段", () => {
  const out = parseScorers({ scorers: [
    { kind: "rubric-judge", rubric: "rubric.yaml" },
    { kind: "exec-script", script: "checks/check.sh", parser: "pytest" },
  ] });
  assert.equal(out.length, 2);
  assert.equal(out[0].kind, "rubric-judge");
  assert.equal(out[1].script, "checks/check.sh");
});

test("loadTask: 种子任务无 scoring 字段 → scorers == DEFAULT_SCORERS", () => {
  const t = loadTask(SURVEY);
  assert.deepEqual(t.scorers, DEFAULT_SCORERS);
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`./task.js` has no exported member `DEFAULT_SCORERS`，`./loader.js` has no exported member `parseScorers`。

- [ ] **Step 3: 在 `src/task.ts` 加 `DEFAULT_SCORERS` 并把 `scorers` 接进 `Task` + 校验**

在 `src/task.ts` 的 `ScorerSpec` 接口下方追加：
```ts
/** 任务未声明 scoring 时的缺省：单 rubric-judge over rubric.yaml（保持今天行为）。 */
export const DEFAULT_SCORERS: ScorerSpec[] = [{ kind: "rubric-judge", rubric: "rubric.yaml" }];
```

在 `Task` 接口里（`rubric: Rubric;` 一行下方）加一个字段：
```ts
  /** 该任务声明的 scorer 列表（缺省 DEFAULT_SCORERS）。 */
  scorers: ScorerSpec[];
```

在 `validateTask` 函数体**末尾**（`rubric` 校验之后、函数结束前）追加：
```ts
  if (!Array.isArray(t.scorers) || t.scorers.length === 0)
    throw new Error(`task ${m.id}: scorers must be a non-empty list`);
  for (const [i, s] of t.scorers.entries()) {
    if (typeof s.kind !== "string" || !s.kind)
      throw new Error(`task ${m.id}: scorer ${i} missing 'kind'`);
  }
```

- [ ] **Step 4: 在 `src/loader.ts` 加 `parseScorers` 并在 `loadTask` 里填 `scorers`**

在 `src/loader.ts` 顶部 import 里把 `DEFAULT_SCORERS` 和 `ScorerSpec` 加进来（与现有 `type Task ...` 同一行 import）：
```ts
import { type Task, type TaskMeta, type TaskTurn, type Rubric, type ScorerSpec, DEFAULT_RUBRIC, DEFAULT_SCORERS, validateTask } from "./task.js";
```

在 `loadTask` 里、`const task: Task = { meta, turns, askUser, rubric, dir };` 这一行**之前**插入：
```ts
  const scorers = parseScorers(metaRaw.scoring);
```
并把构造对象改成包含 `scorers`：
```ts
  const task: Task = { meta, turns, askUser, rubric, scorers, dir };
```

在文件末尾（`answerFor` 函数之后）追加导出：
```ts
/** 从 task.yaml 的 `scoring` 段解析 scorer 列表；缺省回落 DEFAULT_SCORERS。 */
export function parseScorers(scoringRaw: any): ScorerSpec[] {
  const list = scoringRaw?.scorers;
  if (!Array.isArray(list) || list.length === 0) return DEFAULT_SCORERS;
  return list.map((s: any) => ({ ...s, kind: String(s.kind) }));
}
```

- [ ] **Step 5: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`loader.test.js` 三个用例通过，总计 `# fail 0`。

- [ ] **Step 6: 提交**

```bash
git add src/task.ts src/loader.ts src/loader.test.ts
git commit -m "feat(task): task.yaml 新增可选 scoring.scorers + loader 解析(缺省单 rubric-judge)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: rubric scorer 模块 + 注册 + index

**Files:**
- Create: `src/scorer/rubric.ts`
- Create: `src/scorer/index.ts`
- Test: `src/scorer/rubric.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `src/scorer/rubric.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { loadTask } from "../loader.js";
import { getScorerModule } from "./registry.js";
import "./index.js"; // 触发 rubric 注册

const SURVEY = fileURLToPath(new URL("../../tasks/neuro-survey-attention", import.meta.url));
const TRENDS = fileURLToPath(new URL("../../tasks/neuro-trends-connectomics", import.meta.url));

test("rubric-judge 注册并对有 rubric.yaml 的任务给出 4 维", () => {
  const t = loadTask(SURVEY);
  const dims = getScorerModule("rubric-judge").outputs(t.scorers[0], t);
  assert.deepEqual(dims, ["correctness", "completeness", "methodology", "presentation"]);
});

test("rubric 对无 rubric.yaml 的任务回落 DEFAULT_RUBRIC 5 维", () => {
  const t = loadTask(TRENDS);
  const dims = getScorerModule("rubric-judge").outputs(t.scorers[0], t);
  assert.deepEqual(dims, ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});

test("rubric.build().score() 本期返回 unscored（Phase 3 承重墙）", async () => {
  const t = loadTask(SURVEY);
  const scorer = getScorerModule("rubric-human").build(t.scorers[0], t);
  const res = await scorer({ task: t, runDir: "/tmp", events: [], signals: {}, workspaceFiles: () => [] });
  assert.equal(res.unscored, true);
  assert.deepEqual(Object.keys(res.value as Record<string, number>), ["correctness", "completeness", "methodology", "presentation"]);
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './index.js'`（`src/scorer/index.ts` 尚不存在）。

- [ ] **Step 3: 写 `src/scorer/rubric.ts`**

```ts
/**
 * scorer/rubric.ts — rubric 评分模块。
 * outputs = rubric 维度（spec.rubric 指定的文件 → task.rubric → DEFAULT_RUBRIC）。
 * build = 本期返回 unscored：rubric 由外部人/LLM 填 scoresheet，尚无 in-harness 执行；
 *         Phase 3 在此填 judge 调用（同一 Scorer 签名，只换函数体）。
 */
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { parse as parseYaml } from "yaml";
import type { Task, ScorerSpec } from "../task.js";
import { DEFAULT_RUBRIC } from "../task.js";
import type { ScorerModule, Scorer, ScoreContext, ScoreResult } from "./types.js";
import { registerScorer } from "./registry.js";

/** rubric 维度：优先读 spec.rubric 指向的文件，缺省 rubric.yaml；再回落 task.rubric / DEFAULT_RUBRIC。 */
export function rubricDimensions(spec: ScorerSpec, task: Task): string[] {
  const rel = typeof spec.rubric === "string" ? spec.rubric : "rubric.yaml";
  const p = join(task.dir, rel);
  if (existsSync(p)) {
    const dims = parseYaml(readFileSync(p, "utf8"))?.dimensions;
    if (Array.isArray(dims) && dims.length) return dims;
  }
  if (task.rubric?.dimensions?.length) return task.rubric.dimensions;
  return DEFAULT_RUBRIC.dimensions;
}

const rubricModule: ScorerModule = {
  outputs: (spec, task) => rubricDimensions(spec, task),
  build: (spec, task): Scorer => {
    const dims = rubricDimensions(spec, task);
    return async (_ctx: ScoreContext): Promise<ScoreResult> => ({
      value: Object.fromEntries(dims.map((d) => [d, 0] as [string, number])),
      unscored: true, // 见模块注释：Phase 3 在此填 judge 执行体
    });
  },
};

let registered = false;
/** 幂等注册 rubric-judge / rubric-human（二者本期共享同一模块）。 */
export function registerRubricScorers(): void {
  if (registered) return;
  registerScorer("rubric-judge", rubricModule);
  registerScorer("rubric-human", rubricModule);
  registered = true;
}
```

- [ ] **Step 4: 写 `src/scorer/index.ts`（re-export + 触发注册）**

```ts
/**
 * scorer/index.ts — 公开 API + 注册内置 scorer（import 即注册，副作用一次）。
 */
export * from "./types.js";
export * from "./registry.js";

import { registerRubricScorers } from "./rubric.js";
registerRubricScorers();

export { registerRubricScorers, rubricDimensions } from "./rubric.js";
```

- [ ] **Step 5: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`rubric.test.js` 三个用例通过；总 `# fail 0`。

- [ ] **Step 6: 提交**

```bash
git add src/scorer/rubric.ts src/scorer/index.ts src/scorer/rubric.test.ts
git commit -m "feat(scorer): rubric 模块(维度推导+承重墙 build)注册 rubric-judge/rubric-human

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `blankScoresheet` 改走 scorer outputs（逐字节一致，关键验收）

**Files:**
- Modify: `src/scoring.ts`（新增 `scoresheetDimensions`，重写 `blankScoresheet`）
- Test: `src/scoring.test.ts`

- [ ] **Step 1: 写失败测试（含逐字节 golden）**

创建 `src/scoring.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { loadTask } from "./loader.js";
import { blankScoresheet, scoresheetDimensions } from "./scoring.js";

const SURVEY = fileURLToPath(new URL("../tasks/neuro-survey-attention", import.meta.url));
const TRENDS = fileURLToPath(new URL("../tasks/neuro-trends-connectomics", import.meta.url));

test("scoresheetDimensions: 默认单 rubric scorer = rubric 维度", () => {
  assert.deepEqual(scoresheetDimensions(loadTask(SURVEY)),
    ["correctness", "completeness", "methodology", "presentation"]);
  assert.deepEqual(scoresheetDimensions(loadTask(TRENDS)),
    ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});

test("blankScoresheet: survey 逐字节 golden 不变", () => {
  const t = loadTask(SURVEY);
  const sheet = blankScoresheet(t, "neuro-survey-attention-vTEST", "vTEST", "", "2026-06-15T00:00:00.000Z");
  const golden = JSON.stringify({
    taskId: "neuro-survey-attention",
    runId: "neuro-survey-attention-vTEST",
    version: "vTEST",
    judge: "",
    scoredAt: "2026-06-15T00:00:00.000Z",
    dimensions: [
      { dimension: "correctness", score: 0, comment: "" },
      { dimension: "completeness", score: 0, comment: "" },
      { dimension: "methodology", score: 0, comment: "" },
      { dimension: "presentation", score: 0, comment: "" },
    ],
  }, null, 2);
  assert.equal(JSON.stringify(sheet, null, 2), golden);
});

test("blankScoresheet: trends 回落 DEFAULT_RUBRIC 5 维", () => {
  const t = loadTask(TRENDS);
  const sheet = blankScoresheet(t, "x", "v", "", "ts");
  assert.deepEqual(sheet.dimensions.map((d) => d.dimension),
    ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`./scoring.js` has no exported member `scoresheetDimensions`。

- [ ] **Step 3: 改 `src/scoring.ts`**

在 `src/scoring.ts` 顶部 import 区（`import { type Task } from "./task.js";` 一行下方）追加：
```ts
import { getScorerModule } from "./scorer/registry.js";
import { registerRubricScorers } from "./scorer/rubric.js";
registerRubricScorers(); // 确保 rubric-judge/rubric-human 已注册（幂等）
```

新增导出函数（放在 `blankScoresheet` 之前）：
```ts
/** 任务 scoresheet 的维度 = 所有声明 scorer 的 outputs 并集（保序去重）。 */
export function scoresheetDimensions(task: Task): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const spec of task.scorers) {
    for (const d of getScorerModule(spec.kind).outputs(spec, task)) {
      if (!seen.has(d)) { seen.add(d); out.push(d); }
    }
  }
  return out;
}
```

把现有 `blankScoresheet` 里这一行：
```ts
    dimensions: task.rubric.dimensions.map((d) => ({ dimension: d, score: 0, comment: "" })),
```
改成：
```ts
    dimensions: scoresheetDimensions(task).map((d) => ({ dimension: d, score: 0, comment: "" })),
```

- [ ] **Step 4: 构建 + 测试验证 GREEN（逐字节 golden 通过）**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`scoring.test.js` 三个用例通过（含 golden 逐字节相等）；总 `# fail 0`。

- [ ] **Step 5: 提交**

```bash
git add src/scoring.ts src/scoring.test.ts
git commit -m "refactor(scoring): blankScoresheet 改走 scorer outputs(种子任务逐字节一致)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 暴露公开 API + CLI 烟测 + 收尾

**Files:**
- Modify: `src/index.ts`
- Modify: `package.json`（`exports` 加 `./scorer`）

- [ ] **Step 1: `src/index.ts` 导出 scorer 模块**

在 `src/index.ts` 的 `export * from "./scoring.js";` 一行下方追加：
```ts
export * from "./scorer/index.js";
```

- [ ] **Step 2: `package.json` exports 加 `./scorer`**

把 `exports` 段：
```json
  "exports": {
    ".": "./dist/index.js",
    "./task": "./dist/task.js",
    "./runner": "./dist/runner.js",
    "./scoring": "./dist/scoring.js"
  },
```
改成（注意 `./scoring` 行尾加逗号）：
```json
  "exports": {
    ".": "./dist/index.js",
    "./task": "./dist/task.js",
    "./runner": "./dist/runner.js",
    "./scoring": "./dist/scoring.js",
    "./scorer": "./dist/scorer/index.js"
  },
```

- [ ] **Step 3: 全量 typecheck + build + test**

Run: `. "$HOME/.nvm/nvm.sh"; npm run typecheck && npm run build && npm test`
Expected: 三者全过；测试汇总 `# fail 0`（registry 2 + loader 3 + rubric 3 + scoring 3 = 11 用例通过）。

- [ ] **Step 4: CLI 烟测——`list` 仍正常，且任务带 scorers**

Run:
```bash
. "$HOME/.nvm/nvm.sh"
node dist/cli.js list
node -e "import('./dist/loader.js').then(({loadTask})=>{const t=loadTask('tasks/neuro-survey-attention');console.log('scorers=',JSON.stringify(t.scorers));})"
```
Expected: `list` 输出两行任务（与今天一致）；第二条打印 `scorers= [{"kind":"rubric-judge","rubric":"rubric.yaml"}]`。

- [ ] **Step 5: 提交**

```bash
git add src/index.ts package.json
git commit -m "feat(scorer): 经 index 暴露 @brainpilot/bench scorer 公开 API + ./scorer 子路径

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 验收标准（Phase 1 完成定义）

- `npm run typecheck && npm run build && npm test` 全绿，11 个用例通过。
- **逐字节一致**：`scoring.test.ts` 的 survey golden 用例证明 `blankScoresheet` 输出与重构前完全相同（CLI 写 scoresheet 用的就是这个函数，故无需起真实部署即可证明行为不变）。
- `bp-bench list` 输出与今天一致。
- 新增 `src/scorer/`（types/registry/rubric/index）+ `task.scorers` + `scoresheetDimensions` 三处承重墙就位，`rubric-judge`/`rubric-human` 已注册，`getScorerModule` 对未知 kind 报清晰错误——为 Phase 2（data.lock）/ Phase 3（exec-script + judge 执行体）铺好缝。

## 自检记录（writing-plans self-review）

- **Spec 覆盖**：本计划只实现 spec §9 Phase 1（Scorer 接口重构，行为不变）。Phase 2-6 不在本计划。§2 的 Scorer/ScoreContext/ScoreResult/ScorerModule 接口、注册表、rubric 维度推导、"behavior 不变 + 逐字节 scoresheet" 验收均有对应 Task。轨迹评分接口预留 = `ScoreContext.events` 字段已在 types.ts（§2"轨迹评分接口预留"）。
- **Placeholder 扫描**：无 TBD/TODO；每个改动步骤都给了完整代码与确切命令、预期输出。
- **类型一致性**：跨 Task 统一使用 `registerScorer/getScorerModule/hasScorer/listScorers`、`ScorerModule.outputs/build`、`ScorerSpec{kind,rubric,...}`、`DEFAULT_SCORERS`、`parseScorers`、`scoresheetDimensions`、`blankScoresheet`、`rubricDimensions/registerRubricScorers`。Task 1 先在 task.ts 落 `ScorerSpec`，Task 2 补 `DEFAULT_SCORERS`/`Task.scorers`/校验——顺序无前向引用。
