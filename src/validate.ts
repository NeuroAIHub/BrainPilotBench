/**
 * validate.ts — 贡献 CI 门(本地可算):任务有效性 lint + 两侧 Oracle/NOP 有效性门。
 * schema:canary 首行 / 必填 / 无相对路径 / category 存在 / exec 脚本存在 / gate 合法。
 * Oracle/NOP(仅 exec-script + 有 solution/):参考解必出指标、空 NOP 必出不了指标。
 * 真模型信号 + rubric-judge Oracle 留待有凭证的后续切片。
 */
import { readFileSync, existsSync, mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { Task } from "./task.js";
import { loadTask } from "./loader.js";
import type { CategoryRegistry } from "./categories.js";
import { loadCategories } from "./categories.js";
import { getScorerModule } from "./scorer/registry.js";
import "./scorer/index.js"; // 副作用:注册内置 scorer(exec-script 等),让 ./validate 子路径自足
import { setExecSandbox } from "./scorer/exec.js";
import { requiredMetricsFor } from "./categories.js";
import type { ScoreContext } from "./scorer/types.js";
import { localSubprocessSandbox, type ExecSandbox } from "./sandbox.js";

export interface ValidationIssue {
  level: "error" | "warn";
  msg: string;
}

const CANARY = "brainpilot-bench-canary";

let validateSandbox: ExecSandbox | null = null;
/** 测试注入沙箱:同时给 check.sh(exec scorer)和 solution.sh(本模块跑)用。 */
export function setValidateSandbox(s: ExecSandbox | null): void {
  validateSandbox = s;
  setExecSandbox(s);
}

/** 静态 schema 校验(纯本地,不跑脚本)。 */
export function validateTaskSchema(task: Task, reg: CategoryRegistry): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const m = task.meta;
  const yamlPath = join(task.dir, "task.yaml");
  if (existsSync(yamlPath)) {
    const firstLine = readFileSync(yamlPath, "utf8").split("\n", 1)[0] ?? "";
    if (!firstLine.includes(CANARY)) issues.push({ level: "error", msg: "task.yaml 首行缺 canary GUID 注释" });
  } else {
    issues.push({ level: "error", msg: "task.yaml 不存在" });
  }
  if (!m.id) issues.push({ level: "error", msg: "缺 id" });
  if (!m.summary) issues.push({ level: "error", msg: "缺 summary" });
  if (!m.createdAt) issues.push({ level: "error", msg: "缺 created_at(provenance/污染防御)" });
  else if (!/^\d{4}-\d{2}-\d{2}$/.test(m.createdAt)) issues.push({ level: "error", msg: `created_at 非法,需 YYYY-MM-DD: ${m.createdAt}` });
  if (!m.expectedArtifacts?.length) issues.push({ level: "error", msg: "expected_artifacts 不能为空" });
  for (const a of m.expectedArtifacts ?? []) {
    if (a.workspace.includes("..")) issues.push({ level: "error", msg: `expected_artifacts 含相对路径穿越: ${a.workspace}` });
  }
  if (m.category && !reg[m.category]) {
    issues.push({ level: "error", msg: `未知 category: ${m.category}(不在 categories.yaml)` });
  }
  if (m.gate && m.gate.oracleMin != null && m.gate.nopMax != null && !(m.gate.oracleMin > m.gate.nopMax)) {
    issues.push({ level: "error", msg: `gate 无效: oracleMin(${m.gate.oracleMin}) 必须 > nopMax(${m.gate.nopMax})` });
  }
  for (const s of task.scorers) {
    if (s.kind === "exec-script") {
      const rel = typeof s.script === "string" ? s.script : "checks/check.sh";
      if (rel.includes("..")) issues.push({ level: "error", msg: `scorer script 含相对路径穿越: ${rel}` });
      else if (!existsSync(join(task.dir, rel))) issues.push({ level: "error", msg: `exec-script 脚本不存在: ${rel}` });
    }
  }
  // category 必备 metric 覆盖:scorer 的静态 outputs 并集须覆盖该类别必备集。
  // exec-script 的 outputs 是运行时决定(静态返回 []),由 Oracle 门验证产出,故有 exec-script 时跳过静态覆盖检查。
  const required = requiredMetricsFor(m.category, reg);
  if (required.length && !task.scorers.some((s) => s.kind === "exec-script")) {
    const produced = new Set<string>();
    for (const s of task.scorers) {
      try { for (const o of getScorerModule(s.kind).outputs(s, task)) produced.add(o); } catch { /* 未知 kind 已由别处报 */ }
    }
    const missing = required.filter((r) => !produced.has(r));
    if (missing.length) issues.push({ level: "error", msg: `category ${m.category} 必备 metric 未被 scorer 覆盖: ${missing.join(", ")}` });
  }
  return issues;
}

/** 跑 task 的 exec scorer 对给定 bundle 打分;返回是否出了指标(!unscored)。 */
async function execScores(task: Task, runDir: string): Promise<boolean> {
  const spec = task.scorers.find((s) => s.kind === "exec-script");
  if (!spec) return false;
  const scorer = getScorerModule("exec-script").build(spec, task);
  const ctx: ScoreContext = { task, runDir, events: [], signals: {}, workspaceFiles: () => [] };
  const r = await scorer(ctx);
  return r.unscored !== true;
}

/** 在 bundle 里跑 solution.sh 生成参考产物(经注入/本地沙箱)。 */
async function runSolution(task: Task, runDir: string): Promise<void> {
  const sandbox = validateSandbox ?? localSubprocessSandbox();
  const sol = resolve(task.dir, "solution", "solution.sh"); // 绝对:沙箱 cwd=bundle,相对会找不到
  await sandbox.run({ command: "/bin/bash", args: [sol], cwd: runDir, timeoutMs: 120_000 });
}

/** 两侧 Oracle/NOP 门(仅 exec-script + 有 solution/solution.sh)。 */
export async function validateOracleNop(task: Task, _repoDir: string): Promise<ValidationIssue[]> {
  const issues: ValidationIssue[] = [];
  const hasExec = task.scorers.some((s) => s.kind === "exec-script");
  const solScript = join(task.dir, "solution", "solution.sh");
  if (!hasExec || !existsSync(solScript)) {
    issues.push({ level: "warn", msg: "oracle/nop skipped(无 exec-script 或无 solution/solution.sh;真模型/judge Oracle 留待后续切片)" });
    return issues;
  }
  // Oracle bundle 路径含 "oracle";NOP bundle 空。
  const oracleBundle = mkdtempSync(join(tmpdir(), "bpb-oracle-"));
  mkdirSync(join(oracleBundle, "artifacts"), { recursive: true });
  const nopBundle = mkdtempSync(join(tmpdir(), "bpb-nop-"));
  mkdirSync(join(nopBundle, "artifacts"), { recursive: true });
  try {
    await runSolution(task, oracleBundle);          // 生成参考产物进 oracleBundle/artifacts
    const oracleOk = await execScores(task, oracleBundle);
    if (!oracleOk) issues.push({ level: "error", msg: "Oracle 跑参考解未出指标——任务可能无解或 grader 太严" });
    const nopOk = await execScores(task, nopBundle); // 空提交
    if (nopOk) issues.push({ level: "error", msg: "NOP 空提交竟出了指标——grader 太松(啥都不干也过)" });
  } finally {
    rmSync(oracleBundle, { recursive: true, force: true });
    rmSync(nopBundle, { recursive: true, force: true });
  }
  return issues;
}

/** 汇总:schema + oracle/nop。 */
export async function validateTask(dir: string, repoDir: string): Promise<ValidationIssue[]> {
  const task = loadTask(dir);
  const reg = loadCategories(repoDir);
  const issues = validateTaskSchema(task, reg);
  issues.push(...(await validateOracleNop(task, repoDir)));
  return issues;
}
