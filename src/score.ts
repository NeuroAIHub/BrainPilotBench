/**
 * score.ts — 离线评分引擎:从 run bundle 构造 ScoreContext、真跑任务声明的 scorer、
 * 收集结果成 RunScores。(SWE-bench run/eval 分离的 eval 侧。)
 */
import { globSync } from "node:fs";
import { join } from "node:path";
import type { Task } from "./task.js";
import { getScorerModule } from "./scorer/registry.js";
import "./scorer/index.js"; // 副作用:确保内置 scorer(rubric-judge/-human)已注册,引擎自足不靠调用方导入顺序
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
