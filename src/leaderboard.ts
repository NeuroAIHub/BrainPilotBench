/**
 * leaderboard.ts — 按 category 分类的稠密表(读 Phase 3 的 scores.json 真分)。
 * 行=任务×version,列=该类别 categories.yaml 必备 metric。三态:
 *   scored(有效 float,进中位数) / unscored(该 run 没产或值非法→排除聚合,≠fail≠0) / not-applicable(不属该类别→不成列)。
 * rubric 维度 1-5 归一 [0,1];exec 指标透传。绝不 unscored==0。
 */
import { readdirSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { RunScores } from "./score.js";
import type { ScoringState } from "./scorer/types.js";
import { valueToFloat, medianFloat } from "./metrics.js";
import type { CategoryRegistry } from "./categories.js";
import { requiredMetricsFor } from "./categories.js";

export interface LeaderboardCell {
  metric: string;
  /** 该 (task,version) 跨 run 该 metric 的中位数;全 unscored → null。 */
  value: number | null;
  /** scored = 贡献了有效值的 run 数(每 run 最多算一票);total = 该 (task,version) 的 run 数。scored ≤ total。 */
  coverage: { scored: number; total: number };
}
export interface LeaderboardRow {
  taskId: string;
  version: string;
  cells: LeaderboardCell[];
  states: Partial<Record<Exclude<ScoringState, "ready_to_score">, number>>;
}
export interface CategoryTable {
  category: string;
  metrics: string[];
  rows: LeaderboardRow[];
}

/** 读 <runsDir>/*\/scores.json;缺/坏的跳过。 */
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
  if (run.state && run.state !== "scored") return m;
  for (const res of run.results) {
    if (!res || typeof res.kind !== "string") continue; // 坏条目(null/缺 kind)跳过——scores.json 是外部数据
    if (res.unscored) continue; // 整条 unscored → 不贡献任何 metric
    const rubric = res.kind.startsWith("rubric");
    const entries: [string, unknown][] =
      typeof res.value === "number" ? [[res.kind, res.value]] : Object.entries(res.value ?? {});
    for (const [metric, raw] of entries) {
      const f = valueToFloat(raw, { rubric });
      if (f == null) continue; // 非法值 → unscored 该 metric
      const arr = m.get(metric);
      if (arr) arr.push(f);
      else m.set(metric, [f]);
    }
  }
  return m;
}

/** 构建 per-category 稠密表。categoryOf(taskId) 回查 task 的 category(task SSOT)。 */
export function buildLeaderboard(
  runs: RunScores[],
  categoryOf: (taskId: string) => string | undefined,
  reg: CategoryRegistry,
  opts: { includeIneligible?: boolean } = {},
): CategoryTable[] {
  // 1) 按 category 分组 runs。
  const byCat = new Map<string, RunScores[]>();
  for (const run of runs) {
    // Official tables exclude explicitly incomplete lifecycle attempts. Valid
    // completed attempts whose grader failed remain visible in the coverage
    // denominator/state counts, preserving the benchmark's unscored semantics.
    if (!opts.includeIneligible && run.runCompleted === false) continue;
    const cat = categoryOf(run.taskId);
    if (!cat) continue; // 无 category 的 task 不进分类表
    const arr = byCat.get(cat);
    if (arr) arr.push(run);
    else byCat.set(cat, [run]);
  }
  const tables: CategoryTable[] = [];
  for (const [category, catRuns] of byCat) {
    const metrics = requiredMetricsFor(category, reg); // 列 = 必备集(not-applicable 不成列)
    // 按 (taskId,version) 聚合;key 用 JSON 元组(单射,避免 taskId/version 含空格时 split 串味)
    const byKey = new Map<string, { taskId: string; version: string; runs: RunScores[] }>();
    for (const run of catRuns) {
      const k = JSON.stringify([run.taskId, run.version]);
      const g = byKey.get(k);
      if (g) g.runs.push(run);
      else byKey.set(k, { taskId: run.taskId, version: run.version, runs: [run] });
    }
    const rows: LeaderboardRow[] = [];
    for (const { taskId, version, runs: keyRuns } of byKey.values()) {
      const perRun = keyRuns.map(metricFloats); // 每 run 算一次(缓存,避免内层重算)
      const cells: LeaderboardCell[] = metrics.map((metric) => {
        // 每 run 先塌缩成单一代表值(同 metric 多 scorer 取中位数),再跨 run 聚合——
        // 保证一个 run 在「跨 run 中位数」里只占一票,coverage.scored = 贡献的 run 数。
        const floats: number[] = [];
        for (const mf of perRun) {
          const fs = mf.get(metric);
          if (fs && fs.length) floats.push(medianFloat(fs)!);
        }
        return { metric, value: medianFloat(floats), coverage: { scored: floats.length, total: keyRuns.length } };
      });
      const states: LeaderboardRow["states"] = {};
      for (const run of keyRuns) {
        const state = run.state ?? "scored";
        states[state] = (states[state] ?? 0) + 1;
      }
      rows.push({ taskId, version, cells, states });
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
