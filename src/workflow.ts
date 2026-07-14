/** End-to-end workspace preparation and submission bundle assembly. */
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import type { Task } from "./task.js";
import type { RunResult } from "./runner.js";
import { blankScoresheet } from "./scoring.js";
import { captureArtifacts, filesystemArtifactSource } from "./artifacts.js";
import { verifySubmission, type SubmissionIssue, type SubmissionMeta } from "./submission.js";
import { cachePathFor } from "./data/cache.js";

export interface BundleResult {
  runDir: string;
  artifacts: string[];
  issues: SubmissionIssue[];
}

export interface ManualRunState {
  taskId: string;
  taskVersion: string;
  agent: string;
  adapter: "manual";
  workspaceDir: string;
  createdAt: string;
}

export function taskPromptMarkdown(task: Task): string {
  const turns = task.turns.map((turn, index) => `## Turn ${index + 1}\n\n${turn.send}`).join("\n\n");
  return `# ${task.meta.id}\n\n${task.meta.summary}\n\n${turns}\n`;
}

/** Refuse to start an Agent while benchmark-managed private data is visible. */
export function assertAgentDataBoundary(task: Task): void {
  if (process.env.BPB_TOPS_PRIVATE_EVAL_DIR || process.env.BPB_PRIVATE_EVAL_DIR) {
    throw new Error("private evaluator environment is present; unset it before starting an Agent run");
  }
  const cachedPrivate = task.datasets
    .filter((entry) => entry.scope === "private")
    .filter((entry) => existsSync(cachePathFor(entry.sha256)))
    .map((entry) => entry.name);
  if (cachedPrivate.length) {
    throw new Error(`private evaluator data exists in the Agent cache (${cachedPrivate.join(", ")}); use a separate evaluator cache and remove it from the Agent environment`);
  }
}

/** Prepare a concrete agent workspace using public data only. */
export function prepareWorkspace(task: Task, workspaceDir: string): { setupRan: boolean; promptPath: string } {
  assertAgentDataBoundary(task);
  mkdirSync(workspaceDir, { recursive: true });
  // Keep harness-owned files under a hidden directory so broad artifact globs
  // such as "*.md" cannot mistake the task prompt for agent output.
  mkdirSync(join(workspaceDir, ".bpb"), { recursive: true });
  const promptPath = join(workspaceDir, ".bpb", "TASK_PROMPT.md");
  writeFileSync(promptPath, taskPromptMarkdown(task));
  // setup runs with cwd switched to the Agent workspace, so task-relative
  // paths must be resolved while we are still in the benchmark repository.
  const setupPath = resolve(task.dir, "env", "setup.sh");
  if (!existsSync(setupPath)) return { setupRan: false, promptPath };
  execFileSync("/bin/bash", [setupPath, "--role", "agent"], {
    cwd: workspaceDir,
    stdio: "inherit",
    timeout: 300_000,
  });
  return { setupRan: true, promptPath };
}

export async function buildSubmissionBundle(opts: {
  task: Task;
  result: RunResult;
  workspaceDir: string;
  runDir: string;
  agent: string;
}): Promise<BundleResult> {
  const { task, result, workspaceDir, runDir, agent } = opts;
  rmSync(join(runDir, "artifacts"), { recursive: true, force: true });
  rmSync(join(runDir, "scores.json"), { force: true });
  mkdirSync(join(runDir, "artifacts"), { recursive: true });
  const producedAt = new Date().toISOString();
  const meta: SubmissionMeta = {
    taskId: task.meta.id,
    agent,
    taskVersion: task.meta.version,
    producedAt,
  };
  writeFileSync(join(runDir, "meta.json"), JSON.stringify(meta, null, 2));
  writeFileSync(join(runDir, "events.jsonl"), result.events.map((event) => JSON.stringify(event)).join("\n"));
  writeFileSync(join(runDir, "signals.json"), JSON.stringify({
    taskId: task.meta.id,
    runId: `${task.meta.id}-${agent}`,
    sessionId: result.sessionId,
    reason: result.reason,
    ...result.signals,
  }, null, 2));
  writeFileSync(join(runDir, "scoresheet.json"), JSON.stringify(
    blankScoresheet(task, `${task.meta.id}-${agent}`, agent, "", producedAt), null, 2,
  ));

  const artifacts = await captureArtifacts(
    filesystemArtifactSource(dirname(workspaceDir)),
    basename(workspaceDir),
    task.meta.expectedArtifacts.map((artifact) => artifact.workspace),
    join(runDir, "artifacts"),
  );
  return { runDir, artifacts, issues: verifySubmission(task, runDir) };
}

export function writeManualRunState(runDir: string, state: ManualRunState): void {
  mkdirSync(runDir, { recursive: true });
  writeFileSync(join(runDir, "run-state.json"), JSON.stringify(state, null, 2));
}

export function readManualRunState(runDir: string): ManualRunState {
  const path = join(runDir, "run-state.json");
  if (!existsSync(path)) throw new Error(`manual run state not found: ${path}`);
  const state = JSON.parse(readFileSync(path, "utf8")) as ManualRunState;
  if (state.adapter !== "manual" || !state.taskId || !state.workspaceDir) {
    throw new Error(`invalid manual run state: ${path}`);
  }
  return state;
}

export function syntheticRunResult(taskId: string, sessionId: string, completed: boolean, started: number): RunResult {
  const event = { type: completed ? "RUN_FINISHED" : "RUN_ERROR", _ts: new Date().toISOString() };
  return {
    taskId,
    sessionId,
    events: [event],
    reason: completed ? "completed" : "error",
    signals: {
      completed,
      eventCount: 1,
      textContentEvents: 0,
      toolCalls: 0,
      errorEvents: completed ? 0 : 1,
      durationMs: Date.now() - started,
    },
  };
}
