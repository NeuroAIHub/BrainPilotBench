/** Reusable adapters for BrainPilot, local commands, and manual agents. */
import { cpSync, existsSync, linkSync, lstatSync, mkdirSync, readdirSync, realpathSync, rmSync } from "node:fs";
import { spawn } from "node:child_process";
import { join } from "node:path";
import type { Task } from "./task.js";
import { BenchRunner, type RunResult } from "./runner.js";
import { prepareWorkspace, syntheticRunResult } from "./workflow.js";
import { runDockerIsolated, type DockerExecutionResult, type DockerIsolationOptions } from "./isolation.js";

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

/** JSON content types the Runtime uses on its API endpoints. */
function isJsonResponse(response: Response): boolean {
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.toLowerCase().includes("application/json");
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
      // Deployments that serve a Runtime API alongside a SPA front-end share
      // one origin. A SPA fallback route can answer `GET /health` or
      // `GET /sessions` with `200 text/html`, which used to convince the probe
      // that the SPA prefix was the API base — subsequent `POST /sessions`
      // then 404-ed. Require a JSON response before accepting a candidate.
      if (!healthResponse.ok || !isJsonResponse(healthResponse)) continue;
      const sessionsResponse = await fetchFn(sessions, { headers: { accept: "application/json" } });
      if (sessionsResponse.ok && isJsonResponse(sessionsResponse)) return candidate;
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

export type CommandIsolation =
  | { mode: "process" }
  | {
      mode: "docker";
      image: string;
      dockerBinary?: string;
      network?: string;
      cpus?: number;
      memory?: string;
      pidsLimit?: number;
      user?: string;
    };

export interface CommandAdapterOptions {
  command: string;
  workspaceDir: string;
  isolation?: CommandIsolation;
  dockerExecutor?: (options: DockerIsolationOptions) => Promise<DockerExecutionResult>;
}

/** Replace setup-created symlinks with local files before mounting the workspace. */
function materializeSymlinks(dir: string): void {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const stat = lstatSync(path);
    if (stat.isSymbolicLink()) {
      const target = realpathSync(path);
      const targetStat = lstatSync(target);
      rmSync(path, { recursive: true, force: true });
      if (targetStat.isFile()) {
        try { linkSync(target, path); }
        catch { cpSync(target, path); }
      } else if (targetStat.isDirectory()) {
        cpSync(target, path, { recursive: true, dereference: true });
      } else {
        throw new Error(`unsupported setup symlink target: ${path}`);
      }
      continue;
    }
    if (stat.isDirectory()) materializeSymlinks(path);
  }
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
  constructor(private opts: CommandAdapterOptions) {}

  async run(task: Task): Promise<AdapterResult> {
    const isolation = this.opts.isolation ?? { mode: "process" };
    if (isolation.mode === "docker" && existsSync(this.opts.workspaceDir) && readdirSync(this.opts.workspaceDir).length) {
      throw new Error(`Docker isolation requires a new empty workspace; remove or change: ${this.opts.workspaceDir}`);
    }
    prepareWorkspace(task, this.opts.workspaceDir);
    const started = Date.now();
    let code: number;
    if (isolation.mode === "docker") {
      materializeSymlinks(this.opts.workspaceDir);
      const readonlyInputs = readdirSync(this.opts.workspaceDir).map((entry) => join(this.opts.workspaceDir, entry));
      const result = await (this.opts.dockerExecutor ?? runDockerIsolated)({
        ...isolation,
        command: this.opts.command,
        workspaceDir: this.opts.workspaceDir,
        readonlyInputs,
        taskId: task.meta.id,
        timeoutMs: task.meta.timeoutMin * 60_000,
      });
      if (result.timedOut) throw new Error(`agent container exceeded the ${task.meta.timeoutMin} minute task limit`);
      code = result.code;
    } else {
      code = await runShell(this.opts.command, this.opts.workspaceDir, {
        ...agentEnvironment(this.opts.workspaceDir),
        BPB_TASK_ID: task.meta.id,
        BPB_TASK_PROMPT: join(this.opts.workspaceDir, ".bpb", "TASK_PROMPT.md"),
        BPB_WORKSPACE: this.opts.workspaceDir,
      });
    }
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
