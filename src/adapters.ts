/** Reusable adapters for BrainPilot, local commands, and manual agents. */
import { mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { join } from "node:path";
import type { Task } from "./task.js";
import { BenchRunner, type RunResult } from "./runner.js";
import { prepareWorkspace, syntheticRunResult } from "./workflow.js";

export type AdapterStatus = "completed" | "pending";
export interface AdapterResult {
  status: AdapterStatus;
  workspaceDir: string;
  result?: RunResult;
}

export interface AgentAdapter {
  readonly kind: "brainpilot" | "command" | "manual";
  run(task: Task): Promise<AdapterResult>;
}

function baseCandidates(input: string): string[] {
  const base = input.replace(/\/+$/, "");
  const withoutApi = base.replace(/\/api$/, "");
  return [...new Set([base, withoutApi, `${withoutApi}/api`])];
}

/** Probe both common BrainPilot layouts and return the working API base. */
export async function detectBrainPilotBaseUrl(input: string, fetchFn: typeof fetch = fetch): Promise<string> {
  const attempts: string[] = [];
  for (const candidate of baseCandidates(input)) {
    const health = `${candidate}/health`;
    const sessions = `${candidate}/sessions`;
    attempts.push(`${health} + ${sessions}`);
    try {
      const healthResponse = await fetchFn(health, { headers: { accept: "application/json" } });
      if (!healthResponse.ok) continue;
      // /health can be served by a reverse proxy at both levels. A read-only
      // sessions probe confirms that the runtime routes share this prefix.
      const sessionsResponse = await fetchFn(sessions, { headers: { accept: "application/json" } });
      if (sessionsResponse.ok) return candidate;
    } catch { /* try next candidate */ }
  }
  throw new Error(`BrainPilot is not reachable; checked: ${attempts.join(", ")}`);
}

export class BrainPilotAdapter implements AgentAdapter {
  readonly kind = "brainpilot" as const;
  constructor(private opts: { baseUrl: string; workspaceRoot: string; fetchFn?: typeof fetch }) {}

  async run(task: Task): Promise<AdapterResult> {
    const baseUrl = await detectBrainPilotBaseUrl(this.opts.baseUrl, this.opts.fetchFn);
    const runner = new BenchRunner({ baseUrl, fetchFn: this.opts.fetchFn });
    let workspaceDir = "";
    const result = await runner.run(task, {
      onSessionReady: async (sessionId) => {
        workspaceDir = join(this.opts.workspaceRoot, sessionId);
        mkdirSync(workspaceDir, { recursive: true });
        prepareWorkspace(task, workspaceDir);
      },
    });
    return { status: "completed", workspaceDir, result };
  }
}

function runShell(command: string, cwd: string, env: NodeJS.ProcessEnv): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, { cwd, env, shell: true, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", (code, signal) => resolve(code ?? (signal ? 1 : 0)));
  });
}

function agentEnvironment(workspaceDir: string): NodeJS.ProcessEnv {
  const env = { ...process.env };
  for (const key of [
    "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "BPB_TOPS_PRIVATE_EVAL_DIR",
    "BPB_PRIVATE_EVAL_DIR", "BPB_PRIVATE_LABEL_HASHES",
  ]) delete env[key];
  // Prevent Hugging Face libraries from auto-loading the maintainer's saved
  // token. Public task files are already staged into the workspace.
  env.HF_HOME = join(workspaceDir, ".bpb", "agent-hf-home");
  env.BPB_NO_HF_TOKEN_FILE = "1";
  return env;
}

export class CommandAdapter implements AgentAdapter {
  readonly kind = "command" as const;
  constructor(private opts: { command: string; workspaceDir: string }) {}

  async run(task: Task): Promise<AdapterResult> {
    prepareWorkspace(task, this.opts.workspaceDir);
    const started = Date.now();
    const code = await runShell(this.opts.command, this.opts.workspaceDir, {
      ...agentEnvironment(this.opts.workspaceDir),
      BPB_TASK_ID: task.meta.id,
      BPB_TASK_PROMPT: join(this.opts.workspaceDir, ".bpb", "TASK_PROMPT.md"),
      BPB_WORKSPACE: this.opts.workspaceDir,
    });
    if (code !== 0) throw new Error(`agent command exited with status ${code}`);
    return {
      status: "completed",
      workspaceDir: this.opts.workspaceDir,
      result: syntheticRunResult(task.meta.id, this.opts.workspaceDir, true, started),
    };
  }
}

export class ManualAdapter implements AgentAdapter {
  readonly kind = "manual" as const;
  constructor(private workspaceDir: string) {}

  async run(task: Task): Promise<AdapterResult> {
    prepareWorkspace(task, this.workspaceDir);
    return { status: "pending", workspaceDir: this.workspaceDir };
  }
}
