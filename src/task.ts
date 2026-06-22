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
import type { DatasetEntry } from "./data/types.js";

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
  /** 任务规范版本;破坏性 spec 改动就 bump,leaderboard 数字据此可比。缺省 "unversioned"。 */
  version: string;
  /** ISO 日期(YYYY-MM-DD);污染防御一等轴(provenance)。缺失由 validate 报错。 */
  createdAt?: string;
  /** held-out 标记:heldout 任务不进公开 list/leaderboard,只在终审评测集。loadTask 缺省填 "public"。 */
  visibility?: "public" | "heldout";
  /** 类别(track):决定进哪张 leaderboard;缺省回落 domain。 */
  category?: string;
  /** Oracle/NOP 门阈值;缺省按 scorer kind 回落 DEFAULT_GATE。 */
  gate?: TaskGate;
}

/** task.yaml 的 gate 段:Oracle 必须 ≥ oracleMin、NOP 必须 ≤ nopMax。 */
export interface TaskGate {
  oracleMin?: number;
  nopMax?: number;
}

/** 缺省门阈值,按 scorer kind 分组(量纲自适应:rubric 1-5、exec 归一化)。 */
export const DEFAULT_GATE: Record<string, { oracleMin: number; nopMax: number }> = {
  "rubric-judge": { oracleMin: 4, nopMax: 2 },
  "rubric-human": { oracleMin: 4, nopMax: 2 },
  "exec-script": { oracleMin: 1, nopMax: 0 },
};

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
  /** 该任务声明的 scorer 列表（缺省 DEFAULT_SCORERS）。 */
  scorers: ScorerSpec[];
  /** 该任务声明的数据集（来自 data.lock；无则空数组）。 */
  datasets: DatasetEntry[];
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
  if (!Array.isArray(t.scorers) || t.scorers.length === 0)
    throw new Error(`task ${m.id}: scorers must be a non-empty list`);
  for (const [i, s] of t.scorers.entries()) {
    if (typeof s.kind !== "string" || !s.kind)
      throw new Error(`task ${m.id}: scorer ${i} missing 'kind'`);
  }
}

/** 任务声明的一个 scorer（从 task.yaml scoring.scorers 解析；详见 loader）。 */
export interface ScorerSpec {
  kind: string;
  rubric?: string;
  script?: string;
  parser?: string;
  [k: string]: unknown;
}

/** 任务未声明 scoring 时的缺省：单 rubric-judge over rubric.yaml（保持今天行为）。 */
export const DEFAULT_SCORERS: ScorerSpec[] = [{ kind: "rubric-judge", rubric: "rubric.yaml" }];
