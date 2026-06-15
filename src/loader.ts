/**
 * loader.ts — Load a Task instance from a `tasks/<id>/` directory.
 */
import { readFileSync, existsSync } from "node:fs";
import { join, basename } from "node:path";
import { parse as parseYaml } from "yaml";
import { type Task, type TaskMeta, type TaskTurn, type Rubric, DEFAULT_RUBRIC, validateTask } from "./task.js";

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

  const task: Task = { meta, turns, askUser, rubric, dir };
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
