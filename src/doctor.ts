/** Preflight checks for a fast, predictable first run. */
import { existsSync, readFileSync, statfsSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import type { Task } from "./task.js";
import { hfResolve, resolveHfToken } from "./data/fetch.js";
import { isCached } from "./data/cache.js";
import { selectDatasets } from "./data/scope.js";
import { detectBrainPilotBaseUrl } from "./adapters.js";
import { dockerStatus } from "./isolation.js";

export type DoctorStatus = "pass" | "warn" | "fail";
export interface DoctorCheck {
  id: string;
  status: DoctorStatus;
  message: string;
  fix?: string;
}

interface CommandResult { ok: boolean; output: string }
export interface DoctorOptions {
  task?: Task;
  privateData?: boolean;
  baseUrl?: string;
  isolation?: "process" | "docker";
  dockerBinary?: string;
  fetchFn?: typeof fetch;
  commandRunner?: (command: string, args: string[]) => CommandResult;
  diskFreeBytes?: number;
  cacheChecker?: (sha256: string) => Promise<boolean>;
}

const defaultCommandRunner = (command: string, args: string[]): CommandResult => {
  const result = spawnSync(command, args, { encoding: "utf8" });
  return { ok: result.status === 0, output: `${result.stdout ?? ""}${result.stderr ?? ""}`.trim() };
};

function pythonRequirements(task?: Task): Array<{ spec: string; module: string }> {
  if (!task) return [];
  const path = join(task.dir, "env", "requirements.txt");
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8").split("\n")
    .map((line) => line.replace(/#.*/, "").trim()).filter(Boolean)
    .map((spec) => {
      const distribution = spec.split(/[<>=!~\[]/, 1)[0].trim();
      return { spec, module: distribution === "scikit-learn" ? "sklearn" : distribution.replaceAll("-", "_") };
    });
}

function selectedProxy(): string | undefined {
  return process.env.HTTPS_PROXY || process.env.https_proxy ||
    process.env.HTTP_PROXY || process.env.http_proxy ||
    process.env.ALL_PROXY || process.env.all_proxy;
}

export function sanitizedProxy(): string | undefined {
  const raw = selectedProxy();
  if (!raw) return undefined;
  try {
    const url = new URL(raw);
    return `${url.protocol}//${url.hostname}${url.port ? `:${url.port}` : ""}`;
  } catch { return "configured (invalid URL)"; }
}

function freeBytesAt(path: string): number {
  const fs = statfsSync(path);
  return Number(fs.bavail) * Number(fs.bsize);
}

function fmt(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
}

export async function runDoctor(options: DoctorOptions = {}): Promise<DoctorCheck[]> {
  const checks: DoctorCheck[] = [];
  const command = options.commandRunner ?? defaultCommandRunner;
  const task = options.task;

  const nodeMajor = Number(process.versions.node.split(".")[0]);
  checks.push(nodeMajor >= 22
    ? { id: "node", status: "pass", message: `Node ${process.versions.node}` }
    : { id: "node", status: "fail", message: `Node ${process.versions.node}; version 22+ is required`, fix: "Install Node.js 22 or newer." });

  const npm = command("npm", ["--version"]);
  checks.push(npm.ok
    ? { id: "npm", status: "pass", message: `npm ${npm.output.split("\n")[0]}` }
    : { id: "npm", status: "fail", message: "npm is not available", fix: "Install npm with Node.js 22+." });

  const requirements = pythonRequirements(task);
  const python = command("python3", ["--version"]);
  checks.push(python.ok
    ? { id: "python", status: "pass", message: python.output || "python3 available" }
    : {
        id: "python", status: requirements.length ? "fail" : "warn", message: "python3 is not available",
        fix: requirements.length ? "Install Python 3 before running this task." : undefined,
      });
  if (python.ok && requirements.length) {
    const missing = requirements.filter(({ module }) => !command("python3", ["-c", `import ${module}`]).ok);
    checks.push(missing.length
      ? { id: "python-packages", status: "fail", message: `missing: ${missing.map((item) => item.spec).join(", ")}`, fix: `python3 -m pip install -r ${join(task!.dir, "env", "requirements.txt")}` }
      : { id: "python-packages", status: "pass", message: requirements.map((item) => item.spec).join(", ") });
  }

  const setupPath = task ? join(task.dir, "env", "setup.sh") : "";
  const agentSetupPath = task ? join(task.dir, "env", "setup-agent.sh") : "";
  const needsZstd = Boolean(
    (setupPath && existsSync(setupPath) && readFileSync(setupPath, "utf8").includes("zstd")) ||
    (agentSetupPath && existsSync(agentSetupPath) && readFileSync(agentSetupPath, "utf8").includes("zstd")),
  );
  if (needsZstd) {
    const zstd = command("zstd", ["--version"]);
    checks.push(zstd.ok
      ? { id: "zstd", status: "pass", message: zstd.output.split("\n")[0] || "zstd available" }
      : { id: "zstd", status: "fail", message: "zstd is required by task setup", fix: "brew install zstd  # macOS\napt install zstd   # Ubuntu" });
  }

  const datasets = task ? selectDatasets(task.datasets, options.privateData ? "private" : "public") : [];
  if (task && datasets.length) {
    const required = Math.ceil(datasets.reduce((sum, entry) => sum + entry.bytes, 0) * 1.25);
    const free = options.diskFreeBytes ?? freeBytesAt(process.cwd());
    checks.push(free >= required
      ? { id: "disk", status: "pass", message: `${fmt(free)} free; ${fmt(required)} estimated` }
      : { id: "disk", status: "fail", message: `${fmt(free)} free; ${fmt(required)} estimated`, fix: "Free disk space or move XDG_CACHE_HOME to a larger volume." });

    const cacheChecker = options.cacheChecker ?? isCached;
    const missing: string[] = [];
    for (const entry of datasets) if (!(await cacheChecker(entry.sha256))) missing.push(entry.name);
    checks.push(missing.length
      ? { id: "cache", status: "warn", message: `not cached: ${missing.join(", ")}`, fix: `bp-bench fetch ${task.meta.id} --${options.privateData ? "private" : "public"}` }
      : { id: "cache", status: "pass", message: `${datasets.length} dataset(s) cached and checksum-verified` });
  }

  const proxy = sanitizedProxy();
  const proxyRaw = selectedProxy();
  checks.push(proxyRaw && /^socks/i.test(proxyRaw)
    ? { id: "proxy", status: "warn", message: `${proxy}; Node fetch requires an HTTP(S) proxy`, fix: "Set https_proxy=http://127.0.0.1:<port>." }
    : { id: "proxy", status: "pass", message: proxy ? `using ${proxy}` : "direct network (no proxy configured)" });

  if (options.isolation === "docker") {
    const docker = dockerStatus(options.dockerBinary ?? "docker", command);
    checks.push(docker.ok
      ? { id: "docker", status: "pass", message: `Docker daemon available${docker.output ? ` (${docker.output.split("\n")[0]})` : ""}` }
      : {
          id: "docker", status: "fail", message: "Docker isolation is unavailable",
          fix: "Install Docker Desktop (macOS) or Docker Engine (Ubuntu), start the daemon, then rerun this command.",
        });
  } else {
    checks.push({
      id: "isolation", status: "warn",
      message: "local process mode is not a security boundary",
      fix: "For untrusted Agents, use --adapter command --isolation docker --image <image>.",
    });
  }

  if (options.privateData) {
    checks.push(resolveHfToken()
      ? { id: "hf-auth", status: "pass", message: "Hugging Face token found (value hidden)" }
      : { id: "hf-auth", status: "fail", message: "Hugging Face token not found", fix: "Run `hf auth login` or set HF_TOKEN." });
  }

  const hfEntry = datasets.find((entry) => entry.uri.startsWith("hf://"));
  if (hfEntry) {
    const { url, headers } = hfResolve(hfEntry.uri);
    try {
      const response = await (options.fetchFn ?? fetch)(url, {
        method: "HEAD", headers, redirect: "follow", signal: AbortSignal.timeout(10_000),
      });
      if (response.ok) checks.push({ id: "huggingface", status: "pass", message: `reachable (${response.status})` });
      else if (response.status === 401) checks.push({ id: "huggingface", status: "fail", message: "authentication required (401)", fix: "Run `hf auth login` or set HF_TOKEN." });
      else if (response.status === 403) checks.push({ id: "huggingface", status: "fail", message: "dataset access denied (403)", fix: "Request access to the gated dataset." });
      else checks.push({ id: "huggingface", status: "fail", message: `HTTP ${response.status}` });
    } catch (error) {
      checks.push({ id: "huggingface", status: "fail", message: `connection failed: ${(error as Error).message}`, fix: "Check network and HTTP(S) proxy settings." });
    }
  }

  if (options.baseUrl) {
    try {
      const resolved = await detectBrainPilotBaseUrl(options.baseUrl, options.fetchFn);
      checks.push({ id: "brainpilot", status: "pass", message: `runtime at ${resolved}` });
    } catch (error) {
      checks.push({ id: "brainpilot", status: "fail", message: (error as Error).message, fix: "Start BrainPilot or correct --base-url." });
    }
  } else {
    checks.push({ id: "brainpilot", status: "warn", message: "not checked (pass --base-url when using the BrainPilot adapter)" });
  }

  return checks;
}
