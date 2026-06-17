# Phase 5 — 可复现 + leaderboard 硬化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 加 task `version` 字段（spec 漂移可比）、`value_to_float` 归一化、把 `leaderboard()` 从「单一均值」重写成「按 category 分类的稠密表，每格三态 scored/unscored/不成列」，读 Phase 3 的 `scores.json` 真分。

**Architecture:** 新增 `src/metrics.ts`（纯函数 `valueToFloat` + `medianFloat`，rubric 1-5 归一 `[0,1]`、exec 指标透传、pass/partial/fail→1/0.5/0），与 scorer 正交。重写 `src/scoring.ts` 的 `leaderboard()`：读 `runs/*/scores.json`（Phase 3 的 `RunScores`），按 `taskId` 经 `loadTask` 回查 `category`（task 是 SSOT），按 category 分组成稠密表——行=任务×version，列=该类别 `categories.yaml` 必备 metric，格子三态：**scored**（真值，进聚合）/ **unscored**（`scores.json` 里 `unscored:true` 或该 run 没产该 metric → `—`，排除出聚合，≠fail≠0）/ **not-applicable**（metric 不属该类别 → 压根不是列）。task.yaml 加 `version`（loader 解析，缺省 `"unversioned"`）。`bp-bench leaderboard <runsDir>` 改打印 per-category 表 + 每列 coverage。**绝不 unscored==fail。**

**Tech Stack:** TypeScript (NodeNext, strict) → `tsc` → `dist/`；`node --test`；**零新运行时依赖**——`node:fs`/`node:path` + 复用 `loadTask`/`loadCategories`/`requiredMetricsFor`。Node ≥ 22。

## Global Constraints

- **零新运行时依赖**：不得 `npm install` 任何包。只用 Node 内置 + 已有 `yaml`/`@brainpilot/protocol`。
- 构建 `npm run build`（tsc，NodeNext strict）；测试 `npm test`；typecheck `npm run typecheck`。
- TS-TDD：引用不存在的导出 → `npm run build` 编译失败 = RED；逻辑未实现 → `npm test` 断言失败 = RED。
- 跑命令前若 `node` 不在 PATH：先 `. "$HOME/.nvm/nvm.sh"`（Node v24）。
- 提交信息结尾固定加：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 当前在 `main`（已含 Phase 1-4）。**Task 0 先开分支。** 现有 86 单测必须保持全绿——含 Phase 1 的 scoring golden（`blankScoresheet` 逐字节）。
- **破坏性改动**：`leaderboard()` 签名/行为变（从 `ScoreRecord[]`→单一均值，改成 `(runsDir)`→per-category 表，读 scores.json）。`meanScore`/`validateScores`/`blankScoresheet`/`ScoreRecord` **保留不动**（人工 scoresheet 通道仍在）。CLI `leaderboard` 分支改读 scores.json。

### 开分支（Task 0，必须先做）

- [ ] 运行：
```bash
cd /Users/lucasli/Desktop/BrainPilot/repos/brainpilot-benchmark
git checkout main && git pull
git checkout -b feat/phase5-leaderboard
```

## 文件结构（本计划落子）

| 文件 | 职责 |
|---|---|
| `src/task.ts` | 修改。`TaskMeta` 加 `version: string` |
| `src/loader.ts` | 修改。`loadTask` 解析 `version`（缺省 `"unversioned"`） |
| `src/metrics.ts` | 创建。`valueToFloat(v)` + `medianFloat(xs)`（与 scorer 正交） |
| `src/metrics.test.ts` | 创建。归一化/透传/pass-fail/中位数 |
| `src/leaderboard.ts` | 创建。`loadRunScores(runsDir)` + `buildLeaderboard(runs, categoryFor, reg)` → per-category 稠密表(三态) |
| `src/leaderboard.test.ts` | 创建。三态/分类/coverage/排序 |
| `src/scoring.ts` | 修改。删旧 `leaderboard()`（移到 leaderboard.ts 重写）;re-export 新 API |
| `src/cli.ts` | 修改。`leaderboard` 分支改读 scores.json + loadTask 回查 category + 打印 per-category 表 |
| `src/index.ts` | 修改。`export * from "./metrics.js"` + `export * from "./leaderboard.js"` |
| `package.json` | 修改。`exports` 加 `./metrics` `./leaderboard` |
| `tasks/neuro-survey-attention/task.yaml` | 修改。加 `version: "0.1"` |
| `tasks/neuro-trends-connectomics/task.yaml` | 修改。加 `version: "0.1"` |
| `tasks/_example/exec-task/task.yaml` | 修改。加 `version: "0.1"` |

> 复用不改：`loadTask`/`loadCategories`/`requiredMetricsFor`/`RunScores`(score.ts 的 `{taskId,runId,version,scoredAt,results:[{kind,value,verdict?,explanation?,unscored?}]}`)。新 leaderboard 读 `scores.json`(=序列化的 RunScores)。

---

## Task 1: task version 字段

**Files:**
- Modify: `src/task.ts`
- Modify: `src/loader.ts`
- Test: `src/loader-version.test.ts`

**Interfaces:**
- Consumes: 现有 `TaskMeta`/`loadTask`。
- Produces: `TaskMeta` 增 `version: string`；`loadTask` 填 `metaRaw.version`（字符串化；缺省 `"unversioned"`）。

- [ ] **Step 1: 写失败测试**

创建 `src/loader-version.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTask } from "./loader.js";

function makeTask(extraYaml: string): string {
  const dir = mkdtempSync(join(tmpdir(), "bpb-ver-"));
  writeFileSync(join(dir, "task.yaml"),
    "id: t\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: \"*.md\"\ntimeout_min: 5\nbudget_tokens: 1000\n" + extraYaml);
  mkdirSync(join(dir, "prompt"), { recursive: true });
  writeFileSync(join(dir, "prompt", "turns.yaml"), "- send: hi\n");
  return dir;
}

test("loadTask: 解析 version", () => {
  const dir = makeTask("version: \"0.2\"\n");
  try { assert.equal(loadTask(dir).meta.version, "0.2"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: 数字 version 字符串化", () => {
  const dir = makeTask("version: 3\n");
  try { assert.equal(loadTask(dir).meta.version, "3"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});

test("loadTask: 无 version → unversioned", () => {
  const dir = makeTask("");
  try { assert.equal(loadTask(dir).meta.version, "unversioned"); }
  finally { rmSync(dir, { recursive: true, force: true }); }
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`version` 不在 TaskMeta（`t.meta.version` 报 TS 错）。

- [ ] **Step 3: 改 `src/task.ts`**

在 `TaskMeta` 接口里（`requires: TaskRequirements;` 下方、`category?` 等之前或之后均可，放 `requires` 下方）加：
```ts
  /** 任务规范版本;破坏性 spec 改动就 bump,leaderboard 数字据此可比。缺省 "unversioned"。 */
  version: string;
```

- [ ] **Step 4: 改 `src/loader.ts` 填 version**

在 `loadTask` 的 `meta` 对象字面量中（`requires: metaRaw.requires ?? {},` 一行下方）加：
```ts
    version: metaRaw.version != null ? String(metaRaw.version) : "unversioned",
```

- [ ] **Step 5: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`loader-version.test.js` 3 个用例通过；既有 86 全绿；总 `# fail 0`（共 89）。

> 注:既有 `blankScoresheet` golden 测试不读 `meta.version`,新增必填字段不影响它(golden 断的是 ScoreRecord 输出,不含 task.meta)。若编译因 `version` 必填、某处构造 `TaskMeta` 字面量缺 version 而报错——检查 `src/score.test.ts`/`rubric*.test.ts` 里手搓的 fake task `meta`,给它们补 `version: "test"`。**这是预期的连带改动**,把所有手搓 `meta:{...}` 的测试加 `version: "test"`。

- [ ] **Step 6: 提交**

```bash
git add src/task.ts src/loader.ts src/loader-version.test.ts src/score.test.ts src/scorer/rubric-judge.test.ts src/scorer/rubric.test.ts src/validate.test.ts
git commit -m "feat(task): task.yaml 加 version 字段(缺省 unversioned;补测试 fake meta)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

> 注:Step 6 的 `git add` 列出了可能含手搓 `meta` 的测试文件。实际只 add 真正改动的文件——先 `npm run build` 看哪些测试因缺 `version` 报错,只改+add 那些。

---

## Task 2: value_to_float 归一化（纯函数）

**Files:**
- Create: `src/metrics.ts`
- Test: `src/metrics.test.ts`

**Interfaces:**
- Consumes: 无（纯函数）。
- Produces:
  - `function valueToFloat(v: unknown, opts?: { rubric?: boolean }): number | null`（rubric 模式:1-5 → `(x-1)/4` ∈[0,1],越界→null;非 rubric:有限 number 透传,`"pass"`→1/`"partial"`→0.5/`"fail"`→0,其他→null）
  - `function medianFloat(xs: number[]): number | null`（空→null;奇数中间;偶数中间两数均值）

- [ ] **Step 1: 写失败测试**

创建 `src/metrics.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { valueToFloat, medianFloat } from "./metrics.js";

test("valueToFloat rubric: 1-5 → [0,1]", () => {
  assert.equal(valueToFloat(1, { rubric: true }), 0);
  assert.equal(valueToFloat(3, { rubric: true }), 0.5);
  assert.equal(valueToFloat(5, { rubric: true }), 1);
  assert.equal(valueToFloat(0, { rubric: true }), null); // 越界
  assert.equal(valueToFloat(6, { rubric: true }), null);
});

test("valueToFloat 非rubric: 数值透传 + pass/partial/fail", () => {
  assert.equal(valueToFloat(0.83), 0.83);
  assert.equal(valueToFloat(3), 3);
  assert.equal(valueToFloat("pass"), 1);
  assert.equal(valueToFloat("partial"), 0.5);
  assert.equal(valueToFloat("fail"), 0);
  assert.equal(valueToFloat("nonsense"), null);
  assert.equal(valueToFloat(NaN), null);
  assert.equal(valueToFloat(Infinity), null);
  assert.equal(valueToFloat(null), null);
});

test("medianFloat", () => {
  assert.equal(medianFloat([]), null);
  assert.equal(medianFloat([4]), 4);
  assert.equal(medianFloat([3, 5, 4]), 4);     // 奇数
  assert.equal(medianFloat([3, 4]), 3.5);      // 偶数
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './metrics.js'`。

- [ ] **Step 3: 写 `src/metrics.ts`**

```ts
/**
 * metrics.ts — 与 scorer 正交的聚合/归一化纯函数。
 * rubric 1-5 → [0,1] 归一(可跨任务比);exec 指标(accuracy/rows_ok)是有意义数值,透传不归一。
 * pass/partial/fail → 1/0.5/0(verdict 风格)。聚合用中位数(降单 judge 方差,与 rubric judge 一致)。
 */

/** 把一个分值规整成 float:rubric 1-5 归一 [0,1];否则数值透传 / pass-partial-fail。不可解→null。 */
export function valueToFloat(v: unknown, opts: { rubric?: boolean } = {}): number | null {
  if (opts.rubric) {
    if (typeof v !== "number" || !Number.isFinite(v) || v < 1 || v > 5) return null;
    return (v - 1) / 4;
  }
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (v === "pass") return 1;
  if (v === "partial") return 0.5;
  if (v === "fail") return 0;
  return null;
}

/** 中位数;空数组→null;偶数取中间两数均值。 */
export function medianFloat(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}
```

- [ ] **Step 4: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`metrics.test.js` 3 个用例通过；总 `# fail 0`（共 92）。

- [ ] **Step 5: 提交**

```bash
git add src/metrics.ts src/metrics.test.ts
git commit -m "feat(metrics): value_to_float(rubric 1-5 归一/exec 透传/pass-fail)+ medianFloat

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: per-category 稠密表 leaderboard

**Files:**
- Create: `src/leaderboard.ts`
- Test: `src/leaderboard.test.ts`

**Interfaces:**
- Consumes: `RunScores`（`./score.js`，形如 `{taskId,runId,version,scoredAt,results:[{kind,value:Record<string,number>|number,verdict?,unscored?}]}`）；`valueToFloat`/`medianFloat`（`./metrics.js`）；`CategoryRegistry`/`requiredMetricsFor`（`./categories.js`）。
- Produces:
  - `interface LeaderboardCell { metric: string; value: number | null; coverage: { scored: number; total: number } }`（value=该 (task,version) 跨 run 的中位数,全 unscored→null）
  - `interface LeaderboardRow { taskId: string; version: string; cells: LeaderboardCell[] }`
  - `interface CategoryTable { category: string; metrics: string[]; rows: LeaderboardRow[] }`
  - `function loadRunScores(runsDir: string): RunScores[]`（读 `<runsDir>/*/scores.json`，缺/坏的跳过）
  - `function buildLeaderboard(runs: RunScores[], categoryOf: (taskId: string) => string | undefined, reg: CategoryRegistry): CategoryTable[]`

> 三态语义（关键）：对某 (task,version)×metric 格子——收集所有 run 里该 metric 的值，每个值经 `valueToFloat`（rubric scorer 的结果用 `{rubric:true}`，exec 用透传）。**not-applicable**：metric 不在该 task 的 category 必备集 → 不成列（buildLeaderboard 的列 = 该 category 的 `requiredMetricsFor`，不在的 metric 不出列）。**unscored**：该 run 没产这个 metric，或产了但值 `valueToFloat→null` → 不进聚合。**scored**：有有效 float → 进中位数。`cell.value` = 该格所有 scored float 的中位数（全 unscored → null），`coverage={scored,total}`（total=该 (task,version) 的 run 数）。**绝不把 unscored 当 0/fail。**

> rubric vs exec 判定:`RunScores.results[]` 每条有 `kind`;`kind` 以 `rubric` 开头(rubric-judge/rubric-human)→该结果的 value 各维用 `valueToFloat(x,{rubric:true})`;否则(exec-script 等)透传。一条 result 的 `value` 可能是 dict(rubric 多维 / exec 多指标)或标量。

- [ ] **Step 1: 写失败测试**

创建 `src/leaderboard.test.ts`：
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadRunScores, buildLeaderboard } from "./leaderboard.js";
import type { CategoryRegistry } from "./categories.js";

const REG: CategoryRegistry = {
  "survey-writing": { metrics: ["correctness", "completeness"] },
  "exec-data-analysis": { metrics: ["rows_ok"] },
};
const catOf = (id: string) => (id === "ex" ? "exec-data-analysis" : "survey-writing");

test("buildLeaderboard: rubric 归一 + 跨 run 中位数 + coverage", () => {
  const runs = [
    { taskId: "t1", runId: "t1-v1-a", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", value: { correctness: 5, completeness: 3 } }] },
    { taskId: "t1", runId: "t1-v1-b", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", value: { correctness: 3, completeness: 3 } }] },
  ] as any;
  const tables = buildLeaderboard(runs, catOf, REG);
  const sw = tables.find((t) => t.category === "survey-writing")!;
  assert.deepEqual(sw.metrics, ["correctness", "completeness"]);
  const row = sw.rows.find((r) => r.taskId === "t1" && r.version === "v1")!;
  const corr = row.cells.find((c) => c.metric === "correctness")!;
  // correctness: 5→1.0, 3→0.5;中位数 0.75
  assert.equal(corr.value, 0.75);
  assert.deepEqual(corr.coverage, { scored: 2, total: 2 });
  const comp = row.cells.find((c) => c.metric === "completeness")!;
  assert.equal(comp.value, 0.5); // 3→0.5, 3→0.5 → 0.5
});

test("buildLeaderboard: unscored 排除出聚合,≠0", () => {
  const runs = [
    { taskId: "t1", runId: "a", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", value: { correctness: 5, completeness: 5 } }] },
    { taskId: "t1", runId: "b", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", unscored: true, value: { correctness: 0, completeness: 0 } }] },
  ] as any;
  const sw = buildLeaderboard(runs, catOf, REG).find((t) => t.category === "survey-writing")!;
  const corr = sw.rows[0].cells.find((c) => c.metric === "correctness")!;
  assert.equal(corr.value, 1); // 只算 scored 那条(5→1);unscored 不拉低成 0.5
  assert.deepEqual(corr.coverage, { scored: 1, total: 2 });
});

test("buildLeaderboard: exec 指标透传(不归一),not-applicable 不成列", () => {
  const runs = [
    { taskId: "ex", runId: "a", version: "v1", scoredAt: "x", results: [{ kind: "exec-script", value: { rows: 3, rows_ok: 1 } }] },
  ] as any;
  const ex = buildLeaderboard(runs, catOf, REG).find((t) => t.category === "exec-data-analysis")!;
  assert.deepEqual(ex.metrics, ["rows_ok"]); // rows 不在必备集 → 不成列
  const cell = ex.rows[0].cells.find((c) => c.metric === "rows_ok")!;
  assert.equal(cell.value, 1); // 透传,不归一
});

test("buildLeaderboard: 全 unscored 格子 value=null(不是 0)", () => {
  const runs = [
    { taskId: "t1", runId: "a", version: "v1", scoredAt: "x", results: [{ kind: "rubric-judge", unscored: true, value: { correctness: 0, completeness: 0 } }] },
  ] as any;
  const sw = buildLeaderboard(runs, catOf, REG).find((t) => t.category === "survey-writing")!;
  const corr = sw.rows[0].cells.find((c) => c.metric === "correctness")!;
  assert.equal(corr.value, null);
  assert.deepEqual(corr.coverage, { scored: 0, total: 1 });
});

test("loadRunScores: 读 runs/*/scores.json,坏的跳过", () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-runs-"));
  try {
    mkdirSync(join(dir, "r1"), { recursive: true });
    writeFileSync(join(dir, "r1", "scores.json"), JSON.stringify({ taskId: "t1", runId: "r1", version: "v1", scoredAt: "x", results: [] }));
    mkdirSync(join(dir, "r2"), { recursive: true });
    writeFileSync(join(dir, "r2", "scores.json"), "not json");
    mkdirSync(join(dir, "r3"), { recursive: true }); // 无 scores.json
    const runs = loadRunScores(dir);
    assert.equal(runs.length, 1);
    assert.equal(runs[0].taskId, "t1");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
```

- [ ] **Step 2: 跑构建验证 RED**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build`
Expected: 失败，`Cannot find module './leaderboard.js'`。

- [ ] **Step 3: 写 `src/leaderboard.ts`**

```ts
/**
 * leaderboard.ts — 按 category 分类的稠密表(读 Phase 3 的 scores.json 真分)。
 * 行=任务×version,列=该类别 categories.yaml 必备 metric。三态:
 *   scored(有效 float,进中位数) / unscored(该 run 没产或值非法→排除聚合,≠fail≠0) / not-applicable(不属该类别→不成列)。
 * rubric 维度 1-5 归一 [0,1];exec 指标透传。绝不 unscored==0。
 */
import { readdirSync, existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import type { RunScores } from "./score.js";
import { valueToFloat, medianFloat } from "./metrics.js";
import type { CategoryRegistry } from "./categories.js";
import { requiredMetricsFor } from "./categories.js";

export interface LeaderboardCell {
  metric: string;
  /** 该 (task,version) 跨 run 该 metric 的中位数;全 unscored → null。 */
  value: number | null;
  coverage: { scored: number; total: number };
}
export interface LeaderboardRow {
  taskId: string;
  version: string;
  cells: LeaderboardCell[];
}
export interface CategoryTable {
  category: string;
  metrics: string[];
  rows: LeaderboardRow[];
}

/** 读 <runsDir>/*/scores.json;缺/坏的跳过。 */
export function loadRunScores(runsDir: string): RunScores[] {
  if (!existsSync(runsDir)) return [];
  const out: RunScores[] = [];
  for (const d of readdirSync(runsDir)) {
    const p = join(runsDir, d, "scores.json");
    if (!existsSync(p)) continue;
    try {
      const r = JSON.parse(readFileSync(p, "utf8"));
      if (r && typeof r === "object" && typeof r.taskId === "string" && Array.isArray(r.results)) out.push(r);
    } catch { /* 坏 JSON 跳过 */ }
  }
  return out;
}

/** 从一个 run 收集 (metric → float[]):rubric 维度归一,exec 透传;unscored 整条跳过。 */
function metricFloats(run: RunScores): Map<string, number[]> {
  const m = new Map<string, number[]>();
  for (const res of run.results) {
    if (res.unscored) continue; // 整条 unscored → 不贡献任何 metric
    const rubric = res.kind.startsWith("rubric");
    const entries: [string, unknown][] =
      typeof res.value === "number" ? [[res.kind, res.value]] : Object.entries(res.value ?? {});
    for (const [metric, raw] of entries) {
      const f = valueToFloat(raw, { rubric });
      if (f == null) continue; // 非法值 → unscored 该 metric
      (m.get(metric) ?? m.set(metric, []).get(metric)!).push(f);
    }
  }
  return m;
}

/** 构建 per-category 稠密表。categoryOf(taskId) 回查 task 的 category(task SSOT)。 */
export function buildLeaderboard(
  runs: RunScores[],
  categoryOf: (taskId: string) => string | undefined,
  reg: CategoryRegistry,
): CategoryTable[] {
  // 1) 按 category 分组 runs;每个 (taskId,version) 聚合多 run。
  const byCat = new Map<string, RunScores[]>();
  for (const run of runs) {
    const cat = categoryOf(run.taskId);
    if (!cat) continue; // 无 category 的 task 不进分类表
    (byCat.get(cat) ?? byCat.set(cat, []).get(cat)!).push(run);
  }
  const tables: CategoryTable[] = [];
  for (const [category, catRuns] of byCat) {
    const metrics = requiredMetricsFor(category, reg); // 列 = 必备集(not-applicable 不成列)
    // 按 (taskId,version) 聚合
    const byKey = new Map<string, RunScores[]>();
    for (const run of catRuns) {
      const k = `${run.taskId} ${run.version}`;
      (byKey.get(k) ?? byKey.set(k, []).get(k)!).push(run);
    }
    const rows: LeaderboardRow[] = [];
    for (const [k, keyRuns] of byKey) {
      const [taskId, version] = k.split(" ");
      const cells: LeaderboardCell[] = metrics.map((metric) => {
        const floats: number[] = [];
        for (const run of keyRuns) {
          const fs = metricFloats(run).get(metric);
          if (fs) floats.push(...fs);
        }
        return { metric, value: medianFloat(floats), coverage: { scored: floats.length, total: keyRuns.length } };
      });
      rows.push({ taskId, version, cells });
    }
    // 行排序:按行内有效 metric 均值降序(全 null 排末尾)
    rows.sort((a, b) => rowScore(b) - rowScore(a));
    tables.push({ category, metrics, rows });
  }
  tables.sort((a, b) => a.category.localeCompare(b.category));
  return tables;
}

/** 一行的排序键:有效格子均值(全 null → -Infinity 排末尾)。 */
function rowScore(row: LeaderboardRow): number {
  const vals = row.cells.map((c) => c.value).filter((v): v is number => v != null);
  return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : -Infinity;
}
```

> ⚠️ `metricFloats(run)` 在内层循环里对每个 metric 重新算了整个 run——低效但简单。**实现时可缓存**:在 `for (const [k, keyRuns] of byKey)` 里先 `const perRun = keyRuns.map(metricFloats)`,再 metrics.map 里查 `perRun`。功能等价。测试不卡性能,但缓存版更干净;实现者择一,行为必须一致。

- [ ] **Step 4: 构建 + 测试验证 GREEN**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && npm test`
Expected: 构建通过；`leaderboard.test.js` 5 个用例通过；总 `# fail 0`（共 97）。

- [ ] **Step 5: 提交**

```bash
git add src/leaderboard.ts src/leaderboard.test.ts
git commit -m "feat(leaderboard): per-category 稠密表(三态 scored/unscored/不成列;rubric 归一 exec 透传)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: scoring.ts 删旧 leaderboard + CLI 改读 scores.json + 公开 API

**Files:**
- Modify: `src/scoring.ts`（删旧 `leaderboard()` + 旧 import 清理）
- Modify: `src/cli.ts`（`leaderboard` 分支重写）
- Modify: `src/index.ts`（导出 metrics + leaderboard）
- Modify: `package.json`（exports 加 `./metrics` `./leaderboard`）

**Interfaces:**
- Consumes: `loadRunScores`/`buildLeaderboard`/`CategoryTable`（`./leaderboard.js`）、`loadTask`（cli 已有）、`loadCategories`（`./categories.js`）。
- Produces: `src/scoring.ts` 不再导出 `leaderboard`（移到 leaderboard.ts）；保留 `meanScore`/`validateScores`/`blankScoresheet`/`scoresheetDimensions`/`ScoreRecord`。CLI `leaderboard <runsDir> [--tasks <dir>]` 打印 per-category 表。

- [ ] **Step 1: 删 `src/scoring.ts` 旧 `leaderboard()`**

删掉 `src/scoring.ts` 末尾整个 `export function leaderboard(records: ScoreRecord[]): ...{...}` 函数（约 75-88 行）。其余（`meanScore`/`validateScores`/`blankScoresheet`/`scoresheetDimensions`/`ScoreRecord`/`DimensionScore`）**保留**。`getScorerModule` import 仍被 `scoresheetDimensions` 用,不动。

- [ ] **Step 2: 改 `src/cli.ts` 的 import**

把 `import { blankScoresheet, leaderboard, type ScoreRecord } from "./scoring.js";` 改成（去掉 `leaderboard`）：
```ts
import { blankScoresheet, type ScoreRecord } from "./scoring.js";
import { loadRunScores, buildLeaderboard, type CategoryTable } from "./leaderboard.js";
import { loadCategories } from "./categories.js";
```

- [ ] **Step 3: 重写 `src/cli.ts` 的 `leaderboard` 分支**

把整个 `if (cmd === "leaderboard") { ... }` 分支替换为：
```ts
  if (cmd === "leaderboard") {
    const runsDir = argv[1] ?? "runs";
    const repoDir = tasksDir === "tasks" ? "." : tasksDir + "/..";
    const reg = loadCategories(repoDir);
    // taskId → category(task SSOT):用 listTaskDirs 建一次映射。
    const catById = new Map<string, string | undefined>();
    for (const d of listTaskDirs()) {
      try { const t = loadTask(d); catById.set(t.meta.id, t.meta.category); } catch { /* 跳过坏 task */ }
    }
    const runs = loadRunScores(runsDir);
    const tables = buildLeaderboard(runs, (id) => catById.get(id), reg);
    if (!tables.length) { console.log("（无 scores.json 或无 category 记录）"); return; }
    for (const tbl of tables) {
      console.log(`\n${B}# ${tbl.category}${X}`);
      console.log(`task / version            ` + tbl.metrics.map((m) => m.padEnd(14)).join(""));
      for (const row of tbl.rows) {
        const label = `${row.taskId}@${row.version}`.padEnd(26);
        const cells = row.cells.map((c) => {
          const v = c.value == null ? `${Y}—${X}` : c.value.toFixed(2);
          return `${v} (${c.coverage.scored}/${c.coverage.total})`.padEnd(14);
        }).join("");
        console.log(`${label}${cells}`);
      }
    }
    return;
  }
```

> 注:`—`(unscored)用黄色 + `(scored/total)` coverage,数值保留两位。padEnd 对齐够用(终端表格不追求像素级)。

- [ ] **Step 4: `src/index.ts` 导出 metrics + leaderboard**

在 `export * from "./validate.js";` / `export * from "./categories.js";` 一带下方追加：
```ts
export * from "./metrics.js";
export * from "./leaderboard.js";
```

> ⚠️ `scoring.js` 之前 `export * ` 带出过 `leaderboard`,现已删;`leaderboard.js` 现导出新 `buildLeaderboard`/`loadRunScores`(不叫 `leaderboard`,无重名冲突)。若 tsc 报 `CategoryTable`/`LeaderboardRow` 等与别处重名,STOP 报告(不应发生)。

- [ ] **Step 5: `package.json` exports 加两个子路径**

把：
```json
    "./validate": "./dist/validate.js"
  },
```
改成：
```json
    "./validate": "./dist/validate.js",
    "./metrics": "./dist/metrics.js",
    "./leaderboard": "./dist/leaderboard.js"
  },
```

- [ ] **Step 6: 全量 typecheck + build + test + 公开 API + 端到端**

Run:
```bash
. "$HOME/.nvm/nvm.sh"
npm run typecheck && npm run build && npm test 2>&1 | grep -E '^ℹ (tests|pass|fail)'
node -e "import('./dist/index.js').then(m=>console.log('valueToFloat:',typeof m.valueToFloat,'| buildLeaderboard:',typeof m.buildLeaderboard,'| loadRunScores:',typeof m.loadRunScores))"
echo "--- 端到端:造两个 run 的 scores.json 跑 leaderboard ---"
node -e '
const { mkdtempSync, mkdirSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os"); const { join } = require("node:path");
const { execSync } = require("node:child_process");
const runs = mkdtempSync(join(tmpdir(), "bpb-lb-"));
for (const [r, corr] of [["r1",5],["r2",3]]) {
  mkdirSync(join(runs, r), { recursive: true });
  writeFileSync(join(runs, r, "scores.json"), JSON.stringify({ taskId: "neuro-survey-attention", runId: r, version: "0.1", scoredAt: "x", results: [{ kind: "rubric-judge", value: { correctness: corr, completeness: 4, methodology: 4, presentation: 4 } }] }));
}
process.stdout.write(execSync("node " + JSON.stringify(join(process.cwd(),"dist/cli.js")) + " leaderboard " + JSON.stringify(runs), { encoding: "utf8" }));
'
```
Expected: typecheck+build+test 全过，`# fail 0`（共 97）。API 行三 function。端到端打印 `# survey-writing` 表,`neuro-survey-attention@0.1` 行,correctness 列 = 0.75 (2/2)（5→1、3→0.5 中位 0.75），其他维 0.75 (4→0.75)。证明真分经 scores.json → 归一 → per-category 表跑通。

- [ ] **Step 7: 提交**

```bash
git add src/scoring.ts src/cli.ts src/index.ts package.json
git commit -m "feat(cli): leaderboard 重写读 scores.json 出 per-category 表 + 暴露 metrics/leaderboard API

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 给三任务补 version + 文档

**Files:**
- Modify: `tasks/neuro-survey-attention/task.yaml`、`tasks/neuro-trends-connectomics/task.yaml`、`tasks/_example/exec-task/task.yaml`（各加 `version: "0.1"`）
- Modify: `README.md`

- [ ] **Step 1: 给三任务加 version**

每个 task.yaml 在 `domain:`（或 `category:`）行附近加：
```yaml
version: "0.1"
```
（三个文件都加；不破坏 canary 首行。）

- [ ] **Step 2: 验证 validate + list 仍正常**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && node dist/cli.js validate all && node dist/cli.js list | head -2`
Expected: `validate all` 两种子任务 ✓ exit 0；`list` 仍两行。

- [ ] **Step 3: README 加 leaderboard + version 一节**

在 README 的「Validating a task」一节之后追加：
```markdown
## Leaderboard

`bp-bench leaderboard <runsDir>` reads every `<runsDir>/*/scores.json` and prints **per-category dense tables** — one table per `category`, rows = `task@version`, columns = that category's required metrics (from `categories.yaml`).

Each cell is one of three states (never conflated):
- **scored** — a real value (median across runs of that task+version). rubric dimensions are normalized 1-5 → [0,1]; exec metrics pass through as-is.
- **unscored** — shown as `—`; the run produced no value for that metric (judge refusal, infra failure, or an unscored result). **Excluded from the aggregate — never counted as 0 or fail.**
- **not-applicable** — the metric isn't in the task's category, so it isn't a column at all.

Each cell also shows `(scored/total)` coverage. Tasks declare a `version` in `task.yaml` (default `"unversioned"`); bump it on any breaking spec edit so leaderboard numbers stay comparable across versions.
```

- [ ] **Step 4: 验证 list 不受影响 + 提交**

Run: `. "$HOME/.nvm/nvm.sh"; npm run build && node dist/cli.js list | head -2`
Expected: 仍两行。

```bash
git add tasks/neuro-survey-attention/task.yaml tasks/neuro-trends-connectomics/task.yaml tasks/_example/exec-task/task.yaml README.md
git commit -m "docs(leaderboard): 三任务补 version + README leaderboard/version 一节

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 验收标准（Phase 5 完成定义）

- `npm run typecheck && npm run build && npm test` 全绿，**97 单测**（既有 86 + loader-version 3 + metrics 3 + leaderboard 5），`# fail 0`，含 Phase 1 scoring golden 逐字节。
- **零新依赖**：dependencies 仍只有 `@brainpilot/protocol` + `yaml`。
- **value_to_float**：rubric 1-5 → [0,1]、exec 透传、pass/partial/fail → 1/0.5/0，越界/非法 → null（测过）。
- **per-category 稠密表**：读 scores.json，按 category 分组，列=必备 metric，三态——scored 进中位数、unscored 排除（`—`,≠0≠fail）、not-applicable 不成列；coverage `(scored/total)`；端到端经真 scores.json 跑通（Task 4 Step 6）。
- **version**：三任务声明 `version`，`leaderboard` 行按 `task@version` 分。
- **不破坏现状**：`bp-bench list`/`validate all` 仍正常；`meanScore`/`validateScores`/`blankScoresheet` 人工通道保留；Phase 1 golden 不变。

## 自检记录（writing-plans self-review）

- **设计覆盖**：spec §6 = task version(Task1)、value_to_float 1-5 归一(Task2)、leaderboard 按 category 稠密表三态(Task3)、结构化输出(scores.json 已是机读 JSON,leaderboard 读它)。四个拍板:读 scores.json、重写 leaderboard()、rubric 归一 exec 透传、category 经 loadTask 回查——全落地。**明确不做**:exec-pass 与 rubric 合成头条数字(spec 说分列不合成,本计划就是分类分列);registry.json 冻结版本/entry-point 插件(Phase 6)。
- **Placeholder 扫描**:无 TBD/TODO。Task1 Step5/6 标注了"version 必填→手搓 fake meta 测试需补 version"的连带改动,并说明"先 build 看哪些报错只改那些"——这是真实连带,非占位。Task3 的 `metricFloats` 低效但功能正确,给了缓存版提示,行为等价。
- **类型一致**:`valueToFloat(v,{rubric?})`/`medianFloat`、`LeaderboardCell{metric,value,coverage:{scored,total}}`/`LeaderboardRow{taskId,version,cells}`/`CategoryTable{category,metrics,rows}`、`loadRunScores`/`buildLeaderboard(runs,categoryOf,reg)` 跨 Task 一致。复用 `RunScores`(score.ts)/`CategoryRegistry`+`requiredMetricsFor`(categories.ts)/`loadTask`/`loadCategories` 不改签名。旧 `leaderboard()` 删除是破坏性改动,已在 Global Constraints + Task4 写明,保留 meanScore/blankScoresheet 人工通道。
