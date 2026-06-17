/**
 * loader.ts — Load a Task instance from a `tasks/<id>/` directory.
 */
import { readFileSync, existsSync } from "node:fs";
import { join, basename } from "node:path";
import { parse as parseYaml } from "yaml";
import { type Task, type TaskMeta, type TaskTurn, type Rubric, type ScorerSpec, type TaskGate, DEFAULT_RUBRIC, DEFAULT_SCORERS, validateTask } from "./task.js";
import { parseDataManifest } from "./data/manifest.js";

function readYaml(path: string): any {
  return parseYaml(readFileSync(path, "utf8"));
}

/** Load + validate a single task directory. */
export function loadTask(dir: string): Task {
  const id = basename(dir);
  const metaRaw = readYaml(join(dir, "task.yaml")) ?? {};
  const meta: TaskMeta = {
    id: metaRaw.id ?? id,
    domain: metaRaw.domain ?? "",
    summary: metaRaw.summary ?? "",
    expectedArtifacts: (metaRaw.expected_artifacts ?? metaRaw.expectedArtifacts ?? []).map((a: any) =>
      typeof a === "string" ? { workspace: a } : { workspace: a.workspace }),
    timeoutMin: metaRaw.timeout_min ?? metaRaw.timeoutMin ?? 60,
    budgetTokens: metaRaw.budget_tokens ?? metaRaw.budgetTokens ?? 500000,
    requires: metaRaw.requires ?? {},
    category: typeof metaRaw.category === "string" ? metaRaw.category : undefined,
    gate: parseGate(metaRaw.gate),
  };

  const turnsRaw = readYaml(join(dir, "prompt", "turns.yaml")) ?? [];
  const turns: TaskTurn[] = (Array.isArray(turnsRaw) ? turnsRaw : turnsRaw.turns ?? []).map((t: any) =>
    typeof t === "string" ? { send: t } : { send: t.send, then: t.then ?? "wait_idle" });

  const askUserPath = join(dir, "prompt", "ask_user.yaml");
  const askUser: Record<string, string> = existsSync(askUserPath) ? (readYaml(askUserPath) ?? {}) : {};

  const rubricPath = join(dir, "rubric.yaml");
  const rubric: Rubric = existsSync(rubricPath)
    ? { dimensions: readYaml(rubricPath)?.dimensions ?? DEFAULT_RUBRIC.dimensions }
    : DEFAULT_RUBRIC;

  const scorers = parseScorers(metaRaw.scoring);

  const dataLockPath = join(dir, "data.lock");
  const datasets = existsSync(dataLockPath)
    ? parseDataManifest(readYaml(dataLockPath)).datasets
    : [];

  const task: Task = { meta, turns, askUser, rubric, scorers, datasets, dir };
  validateTask(task);
  return task;
}

/** Resolve an ask_user answer for a question, by first matching pattern then `default`. */
export function answerFor(askUser: Record<string, string>, question: string): string | undefined {
  for (const [pattern, answer] of Object.entries(askUser)) {
    if (pattern === "default") continue;
    try { if (new RegExp(pattern, "i").test(question)) return answer; } catch { /* literal */ if (question.includes(pattern)) return answer; }
  }
  return askUser.default;
}

/** 从 task.yaml 的 `scoring` 段解析 scorer 列表；缺省回落 DEFAULT_SCORERS。
 *  保持 kind 原样(不强转)，让 validateTask 统一把关缺失/非法 kind。 */
export function parseScorers(scoringRaw: any): ScorerSpec[] {
  const list = scoringRaw?.scorers;
  if (!Array.isArray(list) || list.length === 0) return DEFAULT_SCORERS;
  return list.map((s: any, i: number) => {
    if (s == null || typeof s !== "object" || Array.isArray(s))
      throw new Error(`scoring.scorers[${i}] must be a mapping with a 'kind'`);
    return { ...s };
  });
}

/** 解析 task.yaml 的 gate 段(snake_case → camelCase);无则 undefined。 */
export function parseGate(raw: any): TaskGate | undefined {
  if (raw == null || typeof raw !== "object") return undefined;
  const g: TaskGate = {};
  if (typeof raw.oracle_min === "number") g.oracleMin = raw.oracle_min;
  if (typeof raw.nop_max === "number") g.nopMax = raw.nop_max;
  return Object.keys(g).length ? g : undefined;
}
