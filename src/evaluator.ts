/** Maintainer-only delivery of a frozen private dataset. Never stages an Agent workspace. */
import { chmodSync, constants, copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, unlinkSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { homedir } from "node:os";
import type { Task } from "./task.js";
import type { DatasetEntry, ResolvedDataset } from "./data/types.js";
import { cacheDir, cachePathFor, sha256File } from "./data/cache.js";
import { resolveManifest, type ResolveOptions } from "./data/resolve.js";

export interface EvaluatorFile { name: string; path: string; sha256: string; bytes: number }
export interface EvaluatorLock {
  schema: "bpb-evaluator-data/1"; task_id: string; repo_id: string; revision: string; files: EvaluatorFile[];
}

export function readEvaluatorLock(task: Task): EvaluatorLock {
  const path = join(task.dir, "evaluator.lock");
  if (!existsSync(path)) throw new Error("no hosted evaluator package for this task; use its documented source-only or legacy evaluation route");
  if (lstatSync(path).isSymbolicLink()) throw new Error("evaluator.lock cannot be a symbolic link");
  const lock = JSON.parse(readFileSync(path, "utf8")) as EvaluatorLock;
  if (lock.schema !== "bpb-evaluator-data/1" || lock.task_id !== task.meta.id ||
      lock.repo_id !== "BrainPilot-Bench/Tasks-Data-Private" || !/^[a-f0-9]{40}$/.test(lock.revision) ||
      !Array.isArray(lock.files) || !lock.files.length) throw new Error("invalid evaluator.lock identity");
  const paths: string[] = [], names = new Set<string>();
  const category = ({ eeg: "eeg", mri: "mri", psychology: "psychology", ieeg: "invasive", intracortical: "invasive",
    "structure-function-divergence": "connectomics" } as Record<string, string>)[task.meta.domain];
  if (!category) throw new Error("unsupported evaluator task domain");
  for (const file of lock.files) {
    if (typeof file.path !== "string" || !file.path || file.path.split("/").some((part) =>
      !/^[A-Za-z0-9._-]+$/.test(part) || part === "." || part === "..") ||
      file.path === ".bpb-evaluator.json" || !/^[a-f0-9]{64}$/.test(file.sha256) ||
      !Number.isSafeInteger(file.bytes) || file.bytes <= 0 || typeof file.name !== "string") {
      throw new Error("unsafe evaluator file mapping");
    }
    const folded = file.path.toLowerCase();
    if (names.has(file.name) || paths.some((p) => p === folded || p.startsWith(folded + "/") || folded.startsWith(p + "/"))) {
      throw new Error("duplicate or colliding evaluator mapping");
    }
    names.add(file.name); paths.push(folded);
    const entries = task.datasets.filter((entry) => entry.name === file.name);
    const entry = entries[0];
    const expectedUri = `hf://datasets/${lock.repo_id}@${lock.revision}/tasks/${category}/${task.meta.id}/evaluator/${file.path}`;
    if (entries.length !== 1 || entry.scope !== "private" || entry.sha256 !== file.sha256 || entry.bytes !== file.bytes ||
        entry.uri !== expectedUri) {
      throw new Error("evaluator mapping does not match a pinned private data.lock entry");
    }
  }
  return lock;
}

export function evaluatorDatasets(task: Task): DatasetEntry[] {
  const lock = readEvaluatorLock(task);
  return lock.files.map((file) => task.datasets.find((entry) => entry.name === file.name)!);
}

/** Resolve existing ancestors so aliases cannot bypass location checks. */
export function canonicalLocation(path: string): string {
  const absolute = resolve(path);
  if (existsSync(absolute)) {
    if (lstatSync(absolute).isSymbolicLink()) throw new Error("evaluator location cannot be a symbolic link");
    return realpathSync(absolute);
  }
  const parent = dirname(absolute);
  if (parent === absolute) return absolute;
  return join(canonicalLocation(parent), basename(absolute));
}

export function pathsOverlap(left: string, right: string): boolean {
  const inside = (a: string, b: string) => { const r = relative(a, b); return r === "" || (!r.startsWith(".." + "/") && r !== ".." && !isAbsolute(r)); };
  return inside(left, right) || inside(right, left);
}

export function assertEvaluatorLocation(path: string, task: Task, forbidden: string[] = []): string {
  const root = canonicalLocation(path);
  for (const unsafe of [task.dir, cacheDir(), join(process.cwd(), ".bpb", "workspaces"), ...forbidden]) {
    if (pathsOverlap(root, canonicalLocation(unsafe))) throw new Error("evaluator storage must be separate from task, Agent/public cache, and submission directories");
  }
  for (let part = root; ; part = dirname(part)) {
    if ((existsSync(join(part, "meta.json")) && existsSync(join(part, "artifacts"))) ||
        existsSync(join(part, ".bpb", "TASK_PROMPT.md"))) {
      throw new Error("evaluator storage must be separate from existing submission bundles and Agent workspaces");
    }
    if (dirname(part) === part) break;
  }
  return root;
}

export function evaluatorCacheRoot(task: Task, requested?: string, forbidden: string[] = []): string {
  const path = requested ?? process.env.BPB_EVALUATOR_CACHE_ROOT ??
    join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "brainpilot-bench-evaluator");
  const root = assertEvaluatorLocation(path, task, forbidden);
  mkdirSync(root, { recursive: true, mode: 0o700 });
  chmodSync(root, 0o700);
  const marker = join(root, ".bpb-private-cache.json");
  if (!existsSync(marker)) writeFileSync(marker, JSON.stringify({ schema: "bpb-private-cache/1", scope: "evaluator-only" }) + "\n", { mode: 0o600, flag: "wx" });
  else if (!lstatSync(marker).isFile() || lstatSync(marker).isSymbolicLink() || lstatSync(marker).nlink !== 1) throw new Error("unsafe private cache marker");
  return root;
}

function plainFile(path: string, root: string): void {
  for (let part = path; ; part = dirname(part)) {
    const info = lstatSync(part);
    if (info.isSymbolicLink() || (part === path ? !info.isFile() || info.nlink !== 1 : !info.isDirectory())) {
      throw new Error("evaluator files must be regular independent files without symbolic links");
    }
    if (part === root) break;
    if (dirname(part) === part) throw new Error("evaluator file escaped its root");
  }
}

async function checkFile(path: string, root: string, file: EvaluatorFile): Promise<void> {
  plainFile(path, root);
  if (lstatSync(path).size !== file.bytes || await sha256File(path) !== file.sha256) throw new Error(`private evaluator file failed size/SHA-256 verification: ${file.path}`);
}

export async function verifyEvaluatorData(task: Task, output: string, forbidden: string[] = []): Promise<EvaluatorLock> {
  const lock = readEvaluatorLock(task);
  const root = assertEvaluatorLocation(output, task, forbidden);
  if (basename(root) !== "evaluator") throw new Error("--evaluator-root must end in /evaluator");
  if (!existsSync(root)) throw new Error("private evaluator data is missing; run prepare-evaluator first");
  const marker = join(root, ".bpb-evaluator.json");
  if (!existsSync(marker)) throw new Error("private evaluator preparation is incomplete; use a fresh output directory");
  plainFile(marker, root);
  const receipt = JSON.parse(readFileSync(marker, "utf8"));
  const lockSha = createHash("sha256").update(readFileSync(join(task.dir, "evaluator.lock"))).digest("hex");
  if (receipt.schema !== "bpb-prepared-evaluator/1" || receipt.task_id !== task.meta.id || receipt.revision !== lock.revision ||
      receipt.evaluator_lock_sha256 !== lockSha || receipt.files !== lock.files.length) throw new Error("prepared evaluator receipt does not match the task lock");
  for (const file of lock.files) await checkFile(join(root, file.path), root, file);
  return lock;
}

export async function fetchEvaluatorData(task: Task, cache?: string, options?: ResolveOptions): Promise<ResolvedDataset[]> {
  return resolveManifest({ datasets: evaluatorDatasets(task) }, { ...options, cacheRoot: evaluatorCacheRoot(task, cache) });
}

/** Worm preparation also needs three public source files, kept in the owner cache. */
export function evaluatorSupportDatasets(task: Task): DatasetEntry[] {
  if (task.meta.id !== "celegans-structure-function-divergence") return [];
  const names = ["CElegansFunctionalConnectivity.xlsx", "witvliet_2020_7.csv", "neuron_master_sheet.csv"];
  return names.map((name) => {
    const entries = task.datasets.filter((entry) => entry.name === name && entry.scope === "public");
    if (entries.length !== 1) throw new Error("worm evaluator public support data is missing from data.lock");
    return { ...entries[0], scope: "private" as const };
  });
}

export async function prepareEvaluatorData(task: Task, output: string, options: {
  fetch?: boolean; cacheRoot?: string; onProgress?: ResolveOptions["onProgress"];
} = {}): Promise<{ root: string; files: number; bytes: number; revision: string }> {
  const lock = readEvaluatorLock(task);
  const root = assertEvaluatorLocation(output, task);
  if (basename(root) !== "evaluator") throw new Error("--evaluator-root must end in /evaluator");
  const cache = evaluatorCacheRoot(task, options.cacheRoot, [root]);
  const support = evaluatorSupportDatasets(task);
  if (options.fetch && support.length) await resolveManifest({ datasets: support }, { cacheRoot: cache, onProgress: options.onProgress });
  if (existsSync(root)) {
    // Resume only a complete matching publication. Never overwrite existing data.
    await verifyEvaluatorData(task, root, [cache]);
    return { root, files: lock.files.length, bytes: lock.files.reduce((sum, f) => sum + f.bytes, 0), revision: lock.revision };
  }
  if (options.fetch) await resolveManifest({ datasets: evaluatorDatasets(task) }, { cacheRoot: cache, onProgress: options.onProgress });
  for (const entry of support) {
    const source = cachePathFor(entry.sha256, cache);
    if (!existsSync(source)) throw new Error("private preparation cache lacks public support files; use --fetch");
    await checkFile(source, cache, { ...entry, path: entry.name });
  }
  for (const file of lock.files) {
    const source = cachePathFor(file.sha256, cache);
    if (!existsSync(source)) throw new Error("private cache missing; use prepare-evaluator --fetch with an authorized HF token");
    await checkFile(source, cache, file);
  }
  mkdirSync(dirname(root), { recursive: true, mode: 0o700 });
  // Exclusive directory creation reserves this exact destination. We never use
  // rename-over-an-existing-directory, even if a competing writer creates one.
  mkdirSync(root, { mode: 0o700 });
  const preparing = join(root, ".bpb-preparing.json");
  writeFileSync(preparing, JSON.stringify({ task_id: task.meta.id, revision: lock.revision }), { mode: 0o600, flag: "wx" });
  try {
    for (const file of lock.files) {
      const dest = join(root, file.path);
      mkdirSync(dirname(dest), { recursive: true, mode: 0o700 });
      for (let dir = dirname(dest); ; dir = dirname(dir)) {
        if (lstatSync(dir).isSymbolicLink() || !lstatSync(dir).isDirectory()) throw new Error("unsafe evaluator destination directory");
        if (dir === root) break;
      }
      copyFileSync(cachePathFor(file.sha256, cache), dest, constants.COPYFILE_EXCL);
      chmodSync(dest, 0o600);
      await checkFile(dest, root, file);
    }
    writeFileSync(join(root, ".bpb-evaluator.json"), JSON.stringify({
      schema: "bpb-prepared-evaluator/1", task_id: task.meta.id, revision: lock.revision,
      evaluator_lock_sha256: createHash("sha256").update(readFileSync(join(task.dir, "evaluator.lock"))).digest("hex"),
      files: lock.files.length, prepared_at: new Date().toISOString(),
    }, null, 2) + "\n", { mode: 0o600, flag: "wx" });
    unlinkSync(preparing);
  } catch (error) {
    // Keep incomplete owner files for diagnosis. Without the completion receipt
    // neither scoring nor repeated prepare can mistake them for accepted data.
    throw error;
  }
  return { root, files: lock.files.length, bytes: lock.files.reduce((sum, f) => sum + f.bytes, 0), revision: lock.revision };
}
