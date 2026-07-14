/**
 * scoring.ts — Rubric scoring scaffold.
 *
 * Benchmark quality is judged by humans (and optionally an LLM judge) against a
 * task's rubric dimensions (1-5 + comment). This module defines the score record
 * shape, aggregation, and a scoresheet generator. It does NOT itself判定
 * pass/fail — benchmarks rank by score, they don't gate.
 */
import { type Task } from "./task.js";
import { getScorerModule } from "./scorer/registry.js";
import "./scorer/index.js"; // 注册全部内置 scorer，避免调用方导入顺序影响 scoresheet

export interface DimensionScore {
  dimension: string;
  /** 1-5. */
  score: number;
  comment?: string;
}

export interface ScoreRecord {
  taskId: string;
  runId: string;
  /** Engine/deployment version under test (e.g. sandbox image tag or commit). */
  version: string;
  judge: string;          // reviewer id (human name or "llm:<model>")
  scoredAt: string;       // ISO
  dimensions: DimensionScore[];
  /** Auto-signals copied from the run for context (not scored). */
  autoSignals?: Record<string, unknown>;
}

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

/** Build a blank scoresheet for a task+run, for a judge to fill in. */
export function blankScoresheet(task: Task, runId: string, version: string, judge: string, scoredAt: string): ScoreRecord {
  return {
    taskId: task.meta.id,
    runId,
    version,
    judge,
    scoredAt,
    dimensions: scoresheetDimensions(task).map((d) => ({ dimension: d, score: 0, comment: "" })),
  };
}

/** Mean score across dimensions (ignoring unscored 0s). */
export function meanScore(rec: ScoreRecord): number | null {
  const scored = rec.dimensions.filter((d) => d.score >= 1 && d.score <= 5);
  if (!scored.length) return null;
  return scored.reduce((s, d) => s + d.score, 0) / scored.length;
}

/** Validate a filled scoresheet (all dimensions 1-5). */
export function validateScores(rec: ScoreRecord): string[] {
  const errs: string[] = [];
  if (!rec.judge) errs.push("missing judge");
  for (const d of rec.dimensions) {
    if (!(d.score >= 1 && d.score <= 5)) errs.push(`${d.dimension}: score ${d.score} not in 1-5`);
  }
  return errs;
}
