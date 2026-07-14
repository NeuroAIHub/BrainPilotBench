/**
 * score.ts — 离线评分引擎:从 run bundle 构造 ScoreContext、真跑任务声明的 scorer、
 * 收集结果成 RunScores。(SWE-bench run/eval 分离的 eval 侧。)
 */
import { globSync, lstatSync, statSync } from "node:fs";
import { join } from "node:path";
import type { Task } from "./task.js";
import { getScorerModule } from "./scorer/registry.js";
import "./scorer/index.js"; // 副作用:确保内置 scorer(rubric-judge/-human)已注册,引擎自足不靠调用方导入顺序
import type { ScoreContext, ScoringState } from "./scorer/types.js";
import { sha256File } from "./data/cache.js";

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
  state?: Exclude<ScoringState, "ready_to_score" | "submission_invalid" | "scored">;
}

/** 一次评分的全部 scorer 结果。 */
export interface RunScores {
  taskId: string;
  runId: string;
  version: string;
  scoredAt: string;
  state: Exclude<ScoringState, "ready_to_score">;
  explanation?: string;
  results: ScorerRunResult[];
}

/** Content snapshot used to prove scorers did not mutate submitted artifacts. */
export async function snapshotArtifacts(runDir: string): Promise<Record<string, string>> {
  const artifactsDir = join(runDir, "artifacts");
  const snapshot: Record<string, string> = {};
  for (const name of ["meta.json", "events.jsonl", "signals.json"]) {
    const path = join(runDir, name);
    try { if (statSync(path).isFile()) snapshot[`$${name}`] = await sha256File(path); }
    catch { /* optional root file absent */ }
  }
  for (const rel of globSync(["**/*", "**/.*", "**/.*/**/*"], { cwd: artifactsDir }).sort()) {
    const path = join(artifactsDir, rel);
    try {
      const info = lstatSync(path);
      if (info.isSymbolicLink()) throw new Error(`artifact symlink is forbidden: ${rel}`);
      if (info.isFile()) snapshot[rel] = await sha256File(path);
    } catch (error) {
      throw new Error(`artifact snapshot failed for ${rel}: ${(error as Error).message}`, { cause: error });
    }
  }
  return snapshot;
}

/** ScoreContext.workspaceFiles 实现:glob 落在 <runDir>/artifacts/,只返回**文件**绝对路径(globSync 也匹配目录,需过滤)。 */
export function bundleWorkspaceFiles(runDir: string): (glob: string) => string[] {
  const artifactsDir = join(runDir, "artifacts");
  return (pattern: string) =>
    globSync(pattern, { cwd: artifactsDir })
      .map((rel) => join(artifactsDir, rel))
      .filter((p) => { try { return statSync(p).isFile(); } catch { return false; } });
}

/** 跑任务声明的全部 scorer,收集结果。 */
export async function runScorers(task: Task, bundle: RunBundle, scoredAt: string): Promise<RunScores> {
  const before = await snapshotArtifacts(bundle.runDir);
  const ctx: ScoreContext = {
    task,
    runDir: bundle.runDir,
    events: bundle.events,
    signals: bundle.signals,
    workspaceFiles: bundleWorkspaceFiles(bundle.runDir),
  };
  const results: ScorerRunResult[] = [];
  for (const spec of task.scorers) {
    try {
      const scorer = getScorerModule(spec.kind).build(spec, task);
      const r = await scorer(ctx);
      results.push({
        kind: spec.kind,
        value: r.value,
        verdict: r.verdict,
        explanation: r.explanation,
        unscored: r.unscored,
        state: r.unscored ? (r.state ?? "scoring_failed") : undefined,
      });
    } catch (error) {
      results.push({
        kind: spec.kind,
        value: {},
        unscored: true,
        state: "scoring_failed",
        explanation: (error as Error).message,
      });
    }
  }
  const after = await snapshotArtifacts(bundle.runDir);
  if (JSON.stringify(before) !== JSON.stringify(after)) {
    throw new Error("submission artifacts changed during scoring; results discarded");
  }
  const successful = results.some((result) => !result.unscored);
  const state = successful
    ? "scored"
    : results.some((result) => result.state === "private_access_denied")
      ? "private_access_denied"
      : results.some((result) => result.state === "private_data_missing")
        ? "private_data_missing"
        : "scoring_failed";
  return { taskId: task.meta.id, runId: bundle.runId, version: bundle.version, scoredAt, state, results };
}
