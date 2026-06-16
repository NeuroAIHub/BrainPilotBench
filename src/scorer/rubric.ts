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
