/** Explicit owner-side Test scoring. Public scores.json remains untouched. */
import { existsSync, lstatSync, mkdtempSync, readdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import type { Task } from "./task.js";
import { scoreMetadataForTask, type RunBundle, type RunScores } from "./score.js";
import { sha256File } from "./data/cache.js";
import { readEvaluatorLock, verifyEvaluatorData } from "./evaluator.js";
import { extractSentinelJson, resolveExecTimeoutMs } from "./scorer/exec.js";
import { localSubprocessSandbox, type ExecSandbox } from "./sandbox.js";
import { verifySubmission } from "./submission.js";

export interface PrivateRunScores extends RunScores {
  evaluationScope: "independent-evaluator-test";
  evaluatorVersion: "1";
  dataRevision: string;
  submissionFreezeSha256?: string;
}

/** Never follow a dangling symlink or retain permissive output permissions. */
export function writePrivateScores(path: string, scores: RunScores): void {
  try {
    const info = lstatSync(path);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) throw new Error("private score output must be a regular independent file");
  } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  const temporary = `${path}.tmp-${randomUUID()}`;
  try {
    writeFileSync(temporary, JSON.stringify(scores, null, 2) + "\n", { flag: "wx", mode: 0o600 });
    renameSync(temporary, path);
  } finally { rmSync(temporary, { force: true }); }
}

async function snapshotPrivateBundle(root: string): Promise<Record<string, string>> {
  const files: Record<string, string> = {};
  async function walk(dir: string, prefix: string) {
    for (const name of readdirSync(dir).sort()) {
      const path = join(dir, name), relative = prefix + name, info = lstatSync(path);
      if (info.isSymbolicLink()) throw new Error("private scoring bundle contains a symbolic link");
      if (info.isDirectory()) await walk(path, relative + "/");
      else if (info.isFile() && info.nlink === 1) files[relative] = await sha256File(path);
      else throw new Error("private scoring bundle contains a linked or special file");
    }
  }
  await walk(root, "");
  return files;
}

export function evaluatorTool(task: Task, name: "score.py" | "prepare.py"): string {
  for (let dir = resolve(task.dir); ; dir = dirname(dir)) {
    const script = join(dir, "_shared", "evaluator", name);
    if (existsSync(script)) {
      if (!lstatSync(script).isFile() || lstatSync(script).isSymbolicLink()) throw new Error("evaluator tool must be a regular trusted file");
      return script;
    }
    if (dirname(dir) === dir) throw new Error("trusted evaluator tool not found in this task collection");
  }
}

export async function runPrivateScorer(task: Task, bundle: RunBundle, scoredAt: string, options: {
  evaluatorRoot: string; python?: string; sandbox?: ExecSandbox;
}): Promise<PrivateRunScores> {
  const lock = readEvaluatorLock(task);
  const base = { taskId: task.meta.id, ...scoreMetadataForTask(task), runId: bundle.runId, version: bundle.version,
    scoredAt, evaluationScope: "independent-evaluator-test" as const, evaluatorVersion: "1" as const, dataRevision: lock.revision };
  if (process.env.BPB_SUBMISSION_ISOLATION !== "docker" ||
      !/^(?:sha256:[a-f0-9]{64}|[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64})$/i.test(process.env.BPB_INFERENCE_IMAGE ?? "")) {
    throw new Error("private Test scoring requires Docker isolation and an immutable inference image");
  }
  const issues = verifySubmission(task, bundle.runDir).filter((issue) => issue.level === "error");
  if (issues.length || bundle.signals.completed === false) throw new Error("private Test requires a completed, valid submission bundle");
  for (const path of [bundle.runDir, join(bundle.runDir, "artifacts")]) {
    if (lstatSync(path).isSymbolicLink()) throw new Error("submission bundle cannot be a symbolic link");
  }
  await verifyEvaluatorData(task, options.evaluatorRoot, [bundle.runDir]);
  const before = await snapshotPrivateBundle(bundle.runDir);
  const files = Object.fromEntries(Object.entries(before).filter(([name]) => name.startsWith("artifacts/")).map(([name, sha]) => [name.slice("artifacts/".length), sha]));
  if (!Object.keys(files).length) throw new Error("private Test requires nonempty frozen artifacts");
  const frozen = JSON.stringify({ schema: "bpb-private-submission-freeze/1", task_id: task.meta.id,
    task_version: task.meta.version, files }, null, 2) + "\n";
  const freezeSha = createHash("sha256").update(frozen).digest("hex");
  const owner = mkdtempSync(join(tmpdir(), "bpb-owner-score-"));
  try {
    const freezePath = join(owner, "submission-freeze.json");
    writeFileSync(freezePath, frozen, { mode: 0o600, flag: "wx" });
    const sandbox = options.sandbox ?? localSubprocessSandbox();
    const response = await sandbox.run({ command: options.python ?? "python3", cwd: owner,
      args: [evaluatorTool(task, "score.py"), "--task", resolve(task.dir), "--artifacts", resolve(bundle.runDir, "artifacts"),
        "--data", resolve(options.evaluatorRoot), "--frozen", freezePath],
      timeoutMs: resolveExecTimeoutMs(task, Math.max(...task.scorers.map((s) => typeof s.timeout_min === "number" ? s.timeout_min : 90))),
    });
    const after = await snapshotPrivateBundle(bundle.runDir);
    if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error("submission bundle changed during private scoring; results discarded");
    await verifyEvaluatorData(task, options.evaluatorRoot, [bundle.runDir]);
    const metrics = extractSentinelJson(response.stdout);
    if (response.exitCode !== 0 || response.timedOut || !metrics) {
      return { ...base, submissionFreezeSha256: freezeSha, state: "scoring_failed", results: [],
        explanation: response.timedOut ? "private Test scoring timed out; no score accepted" :
          `private Test scorer failed (exit ${response.exitCode}); no score accepted; verify the task environment and prepared evaluator data` };
    }
    if (task.meta.evaluation && !(task.meta.evaluation.primaryMetric.id in metrics)) {
      throw new Error("private scorer did not return the task primary metric");
    }
    return { ...base, submissionFreezeSha256: freezeSha, state: "scored", results: [
      { kind: "private-evaluator", value: metrics, explanation: "Frozen submission; isolated private Test; not an upstream official leaderboard score" },
    ] };
  } finally { rmSync(owner, { recursive: true, force: true }); }
}
