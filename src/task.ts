/**
 * task.ts — Benchmark task instance format (the "QC" format from the BrainPilot
 * test plan §5.1, formalized as a contributable spec).
 *
 * A task instance is a directory under `tasks/<id>/`:
 *   task.yaml      — metadata + expected artifacts + budget + requirements
 *   prompt/turns.yaml      — the user turns to inject ([{send, then}])
 *   prompt/ask_user.yaml   — preset answers for ask_user prompts (optional)
 *   env/env.patch.yaml     — deviations from baseline manifest (image/model/mcp/gpu) (optional)
 *   env/setup.sh           — stage data into the workspace (optional)
 *   data.lock              — dataset URI + sha256 (data body NOT in git) (optional)
 *   rubric.yaml            — scoring dimensions for human/LLM judges
 *
 * This module defines the types + a minimal YAML-subset loader (zero deps) +
 * validation. Contributors add a task by dropping in a directory matching this.
 */

export interface TaskTurn {
  /** Message to send to the session. */
  send: string;
  /** What to do after sending. Default "wait_idle". */
  then?: "wait_idle" | "interrupt" | "none";
}

export interface ExpectedArtifact {
  /** Workspace-relative glob, e.g. "results/*.png" or "report.md". */
  workspace: string;
}

export interface TaskRequirements {
  gpu?: boolean;
  mcp?: string[];
  network?: boolean;
}

export interface TaskMeta {
  id: string;
  /** Scientific domain, e.g. "neuroscience-survey", "electrophysiology". */
  domain: string;
  /** One-line human summary of the task. */
  summary: string;
  /** Declared outputs — checked for existence; also the bundle collection whitelist. */
  expectedArtifacts: ExpectedArtifact[];
  timeoutMin: number;
  budgetTokens: number;
  requires: TaskRequirements;
}

export interface Rubric {
  /** Scoring dimensions (each scored 1-5 + comment by a human/LLM judge). */
  dimensions: string[];
}

export interface Task {
  meta: TaskMeta;
  turns: TaskTurn[];
  /** Pattern → answer rules for ask_user; `default` is the fallback. */
  askUser: Record<string, string>;
  rubric: Rubric;
  /** Absolute path to the task directory (for setup.sh / data.lock resolution). */
  dir: string;
}

/** Standard rubric for scientific-research tasks (default if a task omits one). */
export const DEFAULT_RUBRIC: Rubric = {
  dimensions: [
    "correctness",     // scientific correctness: method, parameters, conclusions
    "completeness",    // did it cover all requirements
    "methodology",     // process soundness: agent collaboration, tool use (seen via replay)
    "reproducibility", // can the produced code be re-run
    "presentation",    // quality of report/figures
  ],
};

/** Validate a loaded Task; throws with a clear message on the first problem. */
export function validateTask(t: Partial<Task>): asserts t is Task {
  const m = t.meta;
  if (!m?.id) throw new Error("task.yaml: missing id");
  if (!m.domain) throw new Error(`task ${m.id}: missing domain`);
  if (!m.summary) throw new Error(`task ${m.id}: missing summary`);
  if (!Array.isArray(m.expectedArtifacts) || m.expectedArtifacts.length === 0)
    throw new Error(`task ${m.id}: expectedArtifacts must be a non-empty list`);
  if (!Number.isFinite(m.timeoutMin) || m.timeoutMin <= 0)
    throw new Error(`task ${m.id}: timeoutMin must be > 0`);
  if (!Number.isFinite(m.budgetTokens) || m.budgetTokens <= 0)
    throw new Error(`task ${m.id}: budgetTokens must be > 0`);
  if (!Array.isArray(t.turns) || t.turns.length === 0)
    throw new Error(`task ${m.id}: prompt/turns.yaml must have at least one turn`);
  for (const [i, turn] of t.turns.entries()) {
    if (typeof turn.send !== "string" || !turn.send)
      throw new Error(`task ${m.id}: turn ${i} missing 'send'`);
  }
  if (!t.rubric || !Array.isArray(t.rubric.dimensions) || t.rubric.dimensions.length === 0)
    throw new Error(`task ${m.id}: rubric must have at least one dimension`);
}

/** 任务声明的一个 scorer（从 task.yaml scoring.scorers 解析；详见 loader）。 */
export interface ScorerSpec {
  kind: string;
  rubric?: string;
  script?: string;
  parser?: string;
  [k: string]: unknown;
}
