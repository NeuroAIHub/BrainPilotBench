/** End-to-end workspace preparation and submission bundle assembly. */
import { closeSync, constants, existsSync, fstatSync, ftruncateSync, linkSync, lstatSync, mkdirSync, openSync, readFileSync, readdirSync, readSync, realpathSync, rmSync, unlinkSync, writeFileSync, writeSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { basename, dirname, join, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import type { Task } from "./task.js";
import type { RunResult } from "./runner.js";
import { blankScoresheet } from "./scoring.js";
import { captureArtifacts, filesystemArtifactSource } from "./artifacts.js";
import { verifySubmission, type SubmissionIssue, type SubmissionMeta } from "./submission.js";
import { cachePathFor } from "./data/cache.js";
import { validatePublicDatasetPaths } from "./data/manifest.js";
import type { DatasetEntry } from "./data/types.js";
import { readEvaluatorLock } from "./evaluator.js";

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
  if (Object.entries(process.env).some(([key, value]) => value && /^BPB_.*(?:PRIVATE|EVALUATOR)(?:_|$)/.test(key))) {
    throw new Error("private evaluator environment is present; unset it before starting an Agent run");
  }
  if (process.env.BPB_LOCAL_DATA_ROOT) {
    throw new Error("unset BPB_LOCAL_DATA_ROOT after fetching and before starting an Agent; the archive directory may also contain evaluator data");
  }
  if (process.env.BPB_PUBLIC_DATA_ROOT) {
    throw new Error("unset BPB_PUBLIC_DATA_ROOT before starting an Agent; prepareWorkspace supplies a verified public root to setup");
  }
  // Some source releases repeat immutable public metadata or all-zero input
  // objects in evaluation. Only a validated, explicit source-lock declaration
  // can distinguish those already-public bytes from private-only content.
  const publicEquivalent = new Set<string>();
  if (task.dir && existsSync(join(task.dir, "evaluator.lock"))) {
    const lock = readEvaluatorLock(task);
    for (const sha of lock.public_equivalent_sha256 ?? []) publicEquivalent.add(sha);
  }
  const cachedPrivate = task.datasets
    .filter((entry) => entry.scope === "private")
    .filter((entry) => !publicEquivalent.has(entry.sha256))
    .filter((entry) => existsSync(cachePathFor(entry.sha256)))
    .map((entry) => entry.name);
  if (cachedPrivate.length) {
    throw new Error(`private evaluator data exists in the Agent cache (${cachedPrivate.join(", ")}); use a separate evaluator cache and remove it from the Agent environment`);
  }
}

/** A private preparation/cache must never become an Agent workspace or ancestor mount. */
export function assertNoEvaluatorWorkspace(workspace: string): void {
  const markers = [".bpb-evaluator.json", ".bpb-preparing.json", ".bpb-private-cache.json", "PRIVATE_PREPARED.json"];
  const root = resolve(workspace);
  const inspect = (dir: string) => {
    if (markers.some((name) => existsSync(join(dir, name)))) throw new Error("evaluator data or cache cannot be used inside an Agent workspace");
  };
  const ancestors = (path: string) => {
    for (let dir = path; ; dir = dirname(dir)) {
      inspect(dir);
      if (dirname(dir) === dir) break;
    }
  };
  ancestors(root);
  if (!existsSync(root)) return;
  const pending = [root];
  const seen = new Set<string>();
  let visited = 0;
  while (pending.length) {
    const dir = pending.pop()!;
    const canonical = realpathSync(dir);
    if (seen.has(canonical)) continue;
    seen.add(canonical);
    inspect(dir);
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (++visited > 100_000) throw new Error("workspace is too large to verify private-data isolation; use a fresh dedicated Agent workspace");
      if (entry.isDirectory()) pending.push(join(dir, entry.name));
      if (entry.isSymbolicLink()) {
        let target: string;
        try { target = realpathSync(join(dir, entry.name)); }
        catch { continue; } // Existing workspace/materialization guards handle dangling links.
        ancestors(target);
        if (lstatSync(target).isDirectory()) pending.push(target);
      }
    }
  }
}

function ensurePlainDirectory(path: string): void {
  if (existsSync(path)) {
    if (!lstatSync(path).isDirectory()) throw new Error(`prepared public data path is not a plain directory: ${path}`);
    return;
  }
  ensurePlainDirectory(dirname(path));
  mkdirSync(path);
}

function assertPlainWorkspaceAncestors(path: string): void {
  const ancestors: string[] = [];
  for (let current = path; dirname(current) !== current; current = dirname(current)) ancestors.push(current);
  for (const current of ancestors.reverse()) {
    try {
      if (lstatSync(current).isSymbolicLink()) throw new Error(`prepared workspace has a symlink parent: ${current}`);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
}

function hashFd(fd: number): { sha256: string; bytes: number } {
  const hash = createHash("sha256");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  let bytes = 0;
  for (;;) {
    const count = readSync(fd, buffer, 0, buffer.length, bytes);
    if (count === 0) break;
    hash.update(buffer.subarray(0, count));
    bytes += count;
  }
  return { sha256: hash.digest("hex"), bytes };
}

function checkedCacheFd(entry: DatasetEntry, taskId: string, verifyHash = true): number {
  const cachePath = cachePathFor(entry.sha256);
  let fd: number;
  try {
    fd = openSync(cachePath, constants.O_RDONLY | constants.O_NOFOLLOW);
  } catch {
    throw new Error(`public dataset ${entry.name} is missing or unsafe in cache; run bp-bench prepare ${taskId} --fetch`);
  }
  try {
    const stat = fstatSync(fd);
    if (!stat.isFile() || stat.size !== entry.bytes || (verifyHash && hashFd(fd).sha256 !== entry.sha256)) {
      throw new Error(`public dataset ${entry.name} failed cache size/SHA-256 verification; run bp-bench prepare ${taskId} --fetch`);
    }
    return fd;
  } catch (error) {
    closeSync(fd);
    throw error;
  }
}

function materializePublicData(task: Task, workspaceDir: string): string | undefined {
  const mapped = validatePublicDatasetPaths(task.datasets);
  if (!mapped.length) return undefined;
  const root = join(workspaceDir, ".bpb", "public-data");
  // Verify every source before making any public-data destination visible.
  // Close each descriptor so large manifests do not exhaust the process limit.
  for (const entry of mapped) closeSync(checkedCacheFd(entry, task.meta.id));
  ensurePlainDirectory(root);
  for (const entry of mapped) {
    // Reopen without retaining prior descriptors. The copy hashes these bytes
    // again before its destination becomes visible.
    const fd = checkedCacheFd(entry, task.meta.id, false);
    try {
      const dest = join(root, ...entry.path!.split("/"));
      ensurePlainDirectory(dirname(dest));
      if (existsSync(dest)) {
        const stat = lstatSync(dest);
        if (!stat.isFile() || stat.nlink !== 1) throw new Error(`prepared public data destination is unsafe: ${dest}`);
        const existing = openSync(dest, constants.O_RDONLY | constants.O_NOFOLLOW);
        try {
          const digest = hashFd(existing);
          if (digest.bytes !== entry.bytes || digest.sha256 !== entry.sha256) {
            throw new Error(`prepared public data destination differs from manifest: ${dest}; use a fresh workspace`);
          }
        } finally { closeSync(existing); }
        continue;
      }
      const temp = join(dirname(dest), `.bpb-copy-${randomUUID()}`);
      let out: number | undefined;
      try {
        out = openSync(temp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o644);
        const hash = createHash("sha256");
        const buffer = Buffer.allocUnsafe(1024 * 1024);
        let bytes = 0;
        for (;;) {
          const count = readSync(fd, buffer, 0, buffer.length, bytes);
          if (count === 0) break;
          hash.update(buffer.subarray(0, count));
          let written = 0;
          while (written < count) written += writeSync(out, buffer, written, count - written);
          bytes += count;
        }
        if (bytes !== entry.bytes || hash.digest("hex") !== entry.sha256) {
          throw new Error(`public dataset ${entry.name} changed during copy; prepare aborted`);
        }
        closeSync(out);
        out = undefined;
        // Exclusive link refuses to replace an existing file or symlink.
        linkSync(temp, dest);
      } finally {
        if (out !== undefined) closeSync(out);
        if (existsSync(temp)) unlinkSync(temp);
      }
    } finally { closeSync(fd); }
  }
  return root;
}

/** Prepare a concrete agent workspace using public data only. */
export function prepareWorkspace(task: Task, workspaceDir: string): { setupRan: boolean; promptPath: string; publicDataRoot?: string } {
  assertAgentDataBoundary(task);
  const absoluteWorkspaceDir = resolve(workspaceDir);
  assertNoEvaluatorWorkspace(absoluteWorkspaceDir);
  const hasMappedPublicData = validatePublicDatasetPaths(task.datasets).length > 0;
  if (hasMappedPublicData) assertPlainWorkspaceAncestors(absoluteWorkspaceDir);
  mkdirSync(absoluteWorkspaceDir, { recursive: true });
  if (hasMappedPublicData) assertPlainWorkspaceAncestors(absoluteWorkspaceDir);
  if (!lstatSync(absoluteWorkspaceDir).isDirectory()) throw new Error(`unsafe workspace directory: ${absoluteWorkspaceDir}`);
  // Keep harness-owned files under a hidden directory so broad artifact globs
  // such as "*.md" cannot mistake the task prompt for agent output.
  ensurePlainDirectory(join(absoluteWorkspaceDir, ".bpb"));
  const publicDataRoot = materializePublicData(task, absoluteWorkspaceDir);
  const promptPath = join(absoluteWorkspaceDir, ".bpb", "TASK_PROMPT.md");
  try {
    const promptStat = lstatSync(promptPath);
    if (!promptStat.isFile() || promptStat.nlink !== 1) throw new Error(`unsafe task prompt path: ${promptPath}`);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  let promptFd: number;
  try {
    promptFd = openSync(promptPath, constants.O_WRONLY | constants.O_CREAT | constants.O_NOFOLLOW, 0o644);
  } catch {
    throw new Error(`unsafe task prompt path: ${promptPath}`);
  }
  try {
    const stat = fstatSync(promptFd);
    if (!stat.isFile() || stat.nlink !== 1) throw new Error(`unsafe task prompt path: ${promptPath}`);
    ftruncateSync(promptFd, 0);
    writeFileSync(promptFd, taskPromptMarkdown(task));
  } finally { closeSync(promptFd); }
  // setup runs with cwd switched to the Agent workspace, so task-relative
  // paths must be resolved while we are still in the benchmark repository.
  const setupPath = resolve(task.dir, "env", "setup.sh");
  if (!existsSync(setupPath)) return { setupRan: false, promptPath, publicDataRoot };
  execFileSync("/bin/bash", [setupPath, "--role", "agent"], {
    cwd: absoluteWorkspaceDir,
    env: publicDataRoot ? { ...process.env, BPB_PUBLIC_DATA_ROOT: publicDataRoot } : process.env,
    stdio: "inherit",
    timeout: 300_000,
  });
  return { setupRan: true, promptPath, publicDataRoot };
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
  rmSync(join(runDir, "scores.private.json"), { force: true });
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
