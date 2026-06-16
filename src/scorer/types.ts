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
