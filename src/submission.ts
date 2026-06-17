/**
 * submission.ts — 提交 bundle 契约(系统无关评测输入)。
 * 任何 agent(任何语言/harness)产出一个 bundle 目录即可被 score:
 *   <bundle>/meta.json            提交清单(taskId + agent + 可选 taskVersion/producedAt/notes)
 *   <bundle>/artifacts/<files>    必须满足任务 expected_artifacts 的 glob
 *   <bundle>/events.jsonl         可选轨迹(为将来 trajectory 评分预留)
 * verifySubmission 是契约门:格式/产物齐全性校验(不评分;评分由 score 跑任务声明的 scorer)。
 */
import { readFileSync, existsSync, globSync } from "node:fs";
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
  for (const [k, v] of Object.entries(meta)) {
    if (typeof v === "string" && v.includes("..")) issues.push({ level: "error", msg: `meta.${k} 含路径穿越(..)` });
  }

  // 产物齐全性:每个 expected_artifacts glob 在 artifacts/ 下至少匹配 1 个文件。
  const artifactsDir = join(dir, "artifacts");
  for (const a of task.meta.expectedArtifacts) {
    if (a.workspace.includes("..")) { issues.push({ level: "error", msg: `expected_artifacts 含路径穿越: ${a.workspace}` }); continue; }
    let matched: string[] = [];
    try { matched = existsSync(artifactsDir) ? globSync(a.workspace, { cwd: artifactsDir }) : []; } catch { matched = []; }
    if (!matched.length) issues.push({ level: "error", msg: `缺产物(无文件匹配 expected_artifacts): ${a.workspace}` });
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
