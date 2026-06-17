/**
 * scorer/rubric.ts — rubric 评分模块。
 * outputs = rubric 维度（spec.rubric 指定的文件 → task.rubric → DEFAULT_RUBRIC）。
 * build = 本期返回 unscored：rubric 由外部人/LLM 填 scoresheet，尚无 in-harness 执行；
 *         Phase 3 在此填 judge 调用（同一 Scorer 签名，只换函数体）。
 */
import { readFileSync, existsSync } from "node:fs";
import { join, basename } from "node:path";
import { parse as parseYaml } from "yaml";
import type { Task, ScorerSpec } from "../task.js";
import { DEFAULT_RUBRIC } from "../task.js";
import type { ScorerModule, Scorer, ScoreContext, ScoreResult } from "./types.js";
import { registerScorer } from "./registry.js";
import { resolveJudgeConfig, anthropicJudgeClient, JudgeRefusal, type JudgeClient } from "../judge.js";
import { extractScores, aggregateScores, buildJudgePrompt } from "./grade.js";

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

let injectedClient: JudgeClient | null = null;
/** 测试注入 judge 客户端;非 null 时跳过 env 凭证检查直接用它。 */
export function setJudgeClient(c: JudgeClient | null): void { injectedClient = c; }
export function resetJudgeClient(): void { injectedClient = null; }

/** 读产物 → N judge → 逐维中位数聚合。无凭证/全失败 → error(交上层 unscored)。 */
async function judgeRubric(
  dims: string[],
  ctx: ScoreContext,
): Promise<{ value: Record<string, number>; n: number; votes: number } | { error: string }> {
  const cfg = resolveJudgeConfig();
  const client = injectedClient ?? (cfg ? anthropicJudgeClient(cfg) : null);
  if (!client) return { error: "no judge credentials (set ANTHROPIC_API_KEY or BPB_JUDGE_API_KEY)" };
  const votes = cfg?.votes ?? 3;
  const model = cfg?.model ?? "claude-opus-4-8";

  const artifacts: { name: string; content: string }[] = [];
  for (const a of ctx.task.meta.expectedArtifacts) {
    for (const p of ctx.workspaceFiles(a.workspace)) {
      try { artifacts.push({ name: basename(p), content: readFileSync(p, "utf8").slice(0, 60_000) }); } catch { /* 跳过读不到的 */ }
    }
  }
  const { system, prompt } = buildJudgePrompt(ctx.task.meta.summary, dims, artifacts);

  const perJudge: Record<string, number>[] = [];
  let refused = 0;
  let errored = 0;
  for (let i = 0; i < votes; i++) {
    try {
      const text = await client.complete({ system, prompt, model });
      const scores = extractScores(text, dims);
      if (scores) perJudge.push(scores);
    } catch (e) {
      if (e instanceof JudgeRefusal) refused++; else errored++; // 这一票作废,继续
    }
  }
  if (!perJudge.length) {
    const why = refused && !errored ? "all judges refused"
      : errored && !refused ? "all judge calls errored"
      : "judge produced no parseable scores";
    return { error: `${why} (${votes} attempts: ${refused} refused, ${errored} errored, ${votes - refused - errored} unparseable)` };
  }
  return { value: aggregateScores(perJudge, dims), n: perJudge.length, votes };
}

const rubricModule: ScorerModule = {
  outputs: (spec, task) => rubricDimensions(spec, task),
  build: (spec, task): Scorer => {
    const dims = rubricDimensions(spec, task);
    return async (ctx: ScoreContext): Promise<ScoreResult> => {
      const r = await judgeRubric(dims, ctx);
      if ("error" in r) {
        return { value: Object.fromEntries(dims.map((d) => [d, 0] as [string, number])), unscored: true, explanation: r.error };
      }
      return { value: r.value, explanation: `judged by ${resolveJudgeConfig()?.model ?? "injected"}, ${r.n}/${r.votes} votes` };
    };
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
