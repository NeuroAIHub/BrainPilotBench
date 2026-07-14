/** Docker-backed isolation for untrusted local command Agents. */
import { randomUUID } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { basename, resolve } from "node:path";

export interface DockerIsolationOptions {
  image: string;
  workspaceDir: string;
  readonlyInputs: string[];
  command: string;
  taskId: string;
  timeoutMs: number;
  dockerBinary?: string;
  network?: string;
  cpus?: number;
  memory?: string;
  pidsLimit?: number;
  user?: string;
  containerName?: string;
}

export interface DockerRunSpec {
  binary: string;
  args: string[];
  containerName: string;
}

export interface DockerExecutionResult {
  code: number;
  timedOut: boolean;
}

function mountValue(path: string, label: string): string {
  const absolute = resolve(path);
  if (absolute.includes(",") || /[\r\n]/.test(absolute)) {
    throw new Error(`${label} cannot contain commas or newlines: ${absolute}`);
  }
  return absolute;
}

function safeName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^[^a-z0-9]+/, "").slice(0, 40) || "task";
}

function containerUser(explicit?: string): string {
  if (explicit) {
    if (!/^[1-9]\d*:[1-9]\d*$/.test(explicit)) {
      throw new Error("--container-user must be a non-root numeric uid:gid");
    }
    return explicit;
  }
  const uid = process.getuid?.();
  const gid = process.getgid?.();
  if (uid === 0 || gid === 0) {
    throw new Error("refusing to run an Agent container as root; pass --container-user <non-root-uid:gid>");
  }
  return uid === undefined || gid === undefined ? "65532:65532" : `${uid}:${gid}`;
}

function positiveNumber(value: number, label: string): string {
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${label} must be positive`);
  return String(value);
}

function memoryValue(value: string): string {
  if (!/^[1-9]\d*(?:[kmgt]b?)?$/i.test(value)) throw new Error("--memory must look like 512m, 4g, or a positive byte count");
  return value;
}

function networkValue(value: string): string {
  if (!/^(?:none|bridge|[A-Za-z0-9_.-]+)$/.test(value) || value === "host") {
    throw new Error("--network must be none, bridge, or a named Docker network; host networking is forbidden");
  }
  return value;
}

/** Build a shell-free Docker CLI invocation that is straightforward to audit. */
export function buildDockerRunSpec(options: DockerIsolationOptions): DockerRunSpec {
  if (!options.image.trim()) throw new Error("Docker isolation requires --image <agent-image>");
  if (!options.command.trim()) throw new Error("Docker isolation requires a non-empty Agent command");
  const workspace = mountValue(options.workspaceDir, "workspace path");
  const user = containerUser(options.user);
  const network = networkValue(options.network ?? "none");
  const cpus = positiveNumber(options.cpus ?? 2, "--cpus");
  const pids = positiveNumber(options.pidsLimit ?? 256, "--pids-limit");
  const memory = memoryValue(options.memory ?? "4g");
  const containerName = options.containerName ?? `bpb-${safeName(options.taskId)}-${randomUUID().slice(0, 8)}`;
  const args = [
    "run", "--rm", "--init", "--name", containerName,
    "--network", network,
    "--read-only",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--pids-limit", pids,
    "--cpus", cpus,
    "--memory", memory,
    "--user", user,
    "--workdir", "/workspace",
    "--tmpfs", "/tmp:rw,nosuid,nodev,size=1g",
    "--env", `BPB_TASK_ID=${options.taskId}`,
    "--env", "BPB_TASK_PROMPT=/workspace/.bpb/TASK_PROMPT.md",
    "--env", "BPB_WORKSPACE=/workspace",
    "--env", "HOME=/tmp",
    "--mount", `type=bind,source=${workspace},target=/workspace`,
  ];

  const seenTargets = new Set<string>();
  for (const input of options.readonlyInputs) {
    const source = mountValue(input, "input path");
    const name = basename(source);
    const target = `/workspace/${name}`;
    if (seenTargets.has(target)) throw new Error(`duplicate read-only input mount: ${target}`);
    seenTargets.add(target);
    args.push("--mount", `type=bind,source=${source},target=${target},readonly`);
  }
  args.push(options.image, "/bin/sh", "-lc", options.command);
  return { binary: options.dockerBinary ?? "docker", args, containerName };
}

export function dockerStatus(
  dockerBinary = "docker",
  commandRunner: (command: string, args: string[]) => { ok: boolean; output: string } = (command, args) => {
    const result = spawnSync(command, args, { encoding: "utf8" });
    return { ok: result.status === 0, output: `${result.stdout ?? ""}${result.stderr ?? ""}`.trim() };
  },
): { ok: boolean; output: string } {
  return commandRunner(dockerBinary, ["info", "--format", "{{.ServerVersion}}"]);
}

export function dockerImageStatus(
  image: string,
  dockerBinary = "docker",
  commandRunner: (command: string, args: string[]) => { ok: boolean; output: string } = (command, args) => {
    const result = spawnSync(command, args, { encoding: "utf8" });
    return { ok: result.status === 0, output: `${result.stdout ?? ""}${result.stderr ?? ""}`.trim() };
  },
): { ok: boolean; output: string } {
  return commandRunner(dockerBinary, ["image", "inspect", "--format", "{{.Id}}", image]);
}

/** Run the container and forcibly remove it if the task time limit expires. */
export async function runDockerIsolated(options: DockerIsolationOptions): Promise<DockerExecutionResult> {
  const spec = buildDockerRunSpec(options);
  const status = dockerStatus(spec.binary);
  if (!status.ok) {
    throw new Error(`Docker isolation is unavailable: ${status.output || "docker info failed"}. Install/start Docker and rerun bp-bench doctor --isolation docker.`);
  }
  return new Promise((resolvePromise, reject) => {
    const child = spawn(spec.binary, spec.args, { stdio: "inherit", env: process.env });
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      spawnSync(spec.binary, ["rm", "-f", spec.containerName], { stdio: "ignore", env: process.env });
    }, options.timeoutMs);
    child.on("error", (error) => { clearTimeout(timer); reject(error); });
    child.on("exit", (code, signal) => {
      clearTimeout(timer);
      resolvePromise({ code: timedOut ? 124 : (code ?? (signal ? 1 : 0)), timedOut });
    });
  });
}
