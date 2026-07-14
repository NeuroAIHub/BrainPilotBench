/**
 * submission.ts — 提交 bundle 契约(系统无关评测输入)。
 * 任何 agent(任何语言/harness)产出一个 bundle 目录即可被 score:
 *   <bundle>/meta.json            提交清单(taskId + agent + 可选 taskVersion/producedAt/notes)
 *   <bundle>/artifacts/<files>    必须满足任务 expected_artifacts 的 glob
 *   <bundle>/events.jsonl         可选轨迹(为将来 trajectory 评分预留)
 * verifySubmission 是契约门:格式/产物齐全性校验(不评分;评分由 score 跑任务声明的 scorer)。
 */
import { createHash } from "node:crypto";
import { readFileSync, existsSync, globSync, lstatSync, statSync } from "node:fs";
import { join } from "node:path";
import type { Task } from "./task.js";

export interface SubmissionMeta {
  /** 针对哪个任务(必须等于 task.meta.id)。 */
  taskId: string;
  /** 被评系统标识,如 "acme-agent@1.2.0";leaderboard 行身份(task@agent)。 */
  agent: string;
  /** 可选:针对的任务 spec 版本(记录/可比)。 */
  taskVersion?: string;
  /** 可选:产出时间(ISO)。 */
  producedAt?: string;
  /** 可选:备注。 */
  notes?: string;
}

export interface SubmissionIssue {
  level: "error" | "warn";
  msg: string;
}

/** 读 <dir>/meta.json;不存在→null;坏 JSON→throw 清晰。 */
export function loadSubmissionMeta(dir: string): SubmissionMeta | null {
  const p = join(dir, "meta.json");
  if (!existsSync(p)) return null;
  try { return JSON.parse(readFileSync(p, "utf8")) as SubmissionMeta; }
  catch (e) { throw new Error(`meta.json 解析失败: ${(e as Error).message}`); }
}

/** 契约门:校验 bundle 格式 + 产物齐全(不评分)。返回 issues(error 阻断)。 */
export function verifySubmission(task: Task, dir: string): SubmissionIssue[] {
  const issues: SubmissionIssue[] = [];

  let meta: SubmissionMeta | null = null;
  try { meta = loadSubmissionMeta(dir); }
  catch (e) { issues.push({ level: "error", msg: (e as Error).message }); return issues; }
  if (!meta) { issues.push({ level: "error", msg: "缺 meta.json(提交清单)" }); return issues; }

  if (typeof meta.taskId !== "string" || !meta.taskId) issues.push({ level: "error", msg: "meta.json 缺 taskId" });
  else if (meta.taskId !== task.meta.id) issues.push({ level: "error", msg: `meta.taskId(${meta.taskId})≠任务 id(${task.meta.id})` });
  if (typeof meta.agent !== "string" || !meta.agent) issues.push({ level: "error", msg: "meta.json 缺 agent(被评系统标识)" });

  const configuredPrivatePath = process.env.BPB_TOPS_PRIVATE_EVAL_DIR;
  for (const rel of globSync(["**/*", "**/.*", "**/.*/**/*"], { cwd: dir })) {
    if (rel.startsWith("artifacts/")) continue; // scanned with hashes below
    const path = join(dir, rel);
    try {
      const info = lstatSync(path);
      if (info.isSymbolicLink()) {
        issues.push({ level: "error", msg: `submission symlink is forbidden: ${rel}` });
        continue;
      }
      if (!info.isFile()) continue;
      if (/(^|\/)(?:private(?:_eval|_features|_labels)?|study[45]_(?:features|labels)(?:\.[^/]*)?)(?:\/|$)/i.test(rel)) {
        issues.push({ level: "error", msg: `possible private evaluator file in submission: ${rel}` });
      }
      if (info.size <= 2 * 1024 * 1024 && /\.(?:md|txt|json|jsonl|ya?ml|py|sh|csv)$/i.test(rel)) {
        const text = readFileSync(path, "utf8");
        const assignedPrivatePath = /BPB_TOPS_PRIVATE_EVAL_DIR\s*=\s*["']?\//.test(text);
        const knownPathLeaked = configuredPrivatePath ? text.includes(configuredPrivatePath) : false;
        if (assignedPrivatePath || knownPathLeaked) issues.push({ level: "error", msg: `submission contains a private evaluator path: ${rel}` });
      }
    } catch { issues.push({ level: "error", msg: `submission file cannot be inspected: ${rel}` }); }
  }

  // 产物齐全性:每个 expected_artifacts glob 在 artifacts/ 下至少匹配 1 个**文件**
  // (globSync 也会匹配目录;只数文件,否则 `notreally.csv/` 这种目录会假性通过契约门)。
  const artifactsDir = join(dir, "artifacts");
  const allArtifactFiles: string[] = [];
  if (existsSync(artifactsDir)) {
    for (const rel of globSync(["**/*", "**/.*", "**/.*/**/*"], { cwd: artifactsDir })) {
      const path = join(artifactsDir, rel);
      try {
        const info = lstatSync(path);
        if (info.isSymbolicLink()) {
          issues.push({ level: "error", msg: `artifact symlink is forbidden: ${rel}` });
          continue;
        }
        if (info.isFile()) allArtifactFiles.push(rel);
      } catch { issues.push({ level: "error", msg: `artifact cannot be inspected: ${rel}` }); }
    }
  }

  const privateEntries = task.datasets.filter((entry) => entry.scope === "private");
  const privateHashes = new Set([
    ...privateEntries.map((entry) => entry.sha256),
    ...(process.env.BPB_PRIVATE_LABEL_HASHES ?? "").split(",").map((value) => value.trim()).filter(Boolean),
  ]);
  const privateSizes = new Set(privateEntries.map((entry) => entry.bytes));
  for (const rel of allArtifactFiles) {
    const path = join(artifactsDir, rel);
    if (/(^|\/)(?:private(?:_eval|_features|_labels)?|study[45]_(?:features|labels)(?:\.[^/]*)?)(?:\/|$)/i.test(rel)) {
      issues.push({ level: "error", msg: `possible private evaluator artifact: ${rel}` });
    }
    let info;
    try { info = statSync(path); }
    catch { issues.push({ level: "error", msg: `artifact cannot be scanned: ${rel}` }); continue; }
    if (privateHashes.size && (privateSizes.has(info.size) || info.size <= 128 * 1024 * 1024)) {
      try {
        const digest = createHash("sha256").update(readFileSync(path)).digest("hex");
        if (privateHashes.has(digest)) issues.push({ level: "error", msg: `artifact matches a private dataset hash: ${rel}` });
      } catch { issues.push({ level: "error", msg: `artifact hash scan failed: ${rel}` }); }
    }
    if (info.size <= 2 * 1024 * 1024 && /\.(?:md|txt|json|ya?ml|py|sh|csv)$/i.test(rel)) {
      try {
        const text = readFileSync(path, "utf8");
        const assignedPrivatePath = /BPB_TOPS_PRIVATE_EVAL_DIR\s*=\s*["']?\//.test(text);
        const knownPathLeaked = configuredPrivatePath ? text.includes(configuredPrivatePath) : false;
        if (assignedPrivatePath || knownPathLeaked) {
          issues.push({ level: "error", msg: `artifact contains a private evaluator path: ${rel}` });
        }
      } catch { issues.push({ level: "error", msg: `artifact text scan failed: ${rel}` }); }
    }
  }

  for (const a of task.meta.expectedArtifacts) {
    if (a.workspace.includes("..")) { issues.push({ level: "error", msg: `expected_artifacts 含路径穿越: ${a.workspace}` }); continue; }
    let files: string[] = [];
    try {
      files = (existsSync(artifactsDir) ? globSync(a.workspace, { cwd: artifactsDir }) : [])
        .filter((rel) => {
          try { const info = lstatSync(join(artifactsDir, rel)); return info.isFile() && !info.isSymbolicLink(); }
          catch { return false; }
        });
    } catch { files = []; }
    if (!files.length) issues.push({ level: "error", msg: `缺产物(无文件匹配 expected_artifacts): ${a.workspace}` });
  }

  // 可选 events.jsonl:逐行 JSON.parse,坏行 → warn(不阻断;轨迹是可选物)。
  const evPath = join(dir, "events.jsonl");
  if (existsSync(evPath)) {
    const lines = readFileSync(evPath, "utf8").split("\n").filter((l) => l.trim());
    let bad = 0;
    for (const l of lines) { try { JSON.parse(l); } catch { bad++; } }
    if (bad) issues.push({ level: "warn", msg: `events.jsonl 有 ${bad} 行非法 JSON(轨迹可选,不阻断)` });
  }

  return issues;
}
