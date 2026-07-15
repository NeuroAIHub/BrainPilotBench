/**
 * scorer/exec.ts — exec-script scorer:任务自带 checks/check.sh,离线在沙箱跑它对
 * 回收产物打分。脚本契约:在 >>>>> BPB_SCORES / <<<<< BPB_SCORES 之间输出一行 JSON
 * 指标(扁平 {string:number})。checks/ 跟任务走、离线评分,agent 看不到 grader(反作弊)。
 * 失败(缺脚本/超时/无哨兵/非法 JSON)→ unscored,绝不给 0。
 */
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import type { Task, ScorerSpec } from "../task.js";
import type { ScorerModule, Scorer, ScoreContext, ScoreResult } from "./types.js";
import { registerScorer } from "./registry.js";
import { localSubprocessSandbox, type ExecSandbox } from "../sandbox.js";

const START = ">>>>> BPB_SCORES";
const END = "<<<<< BPB_SCORES";

/**
 * exec-script scorer 的最短超时下限。原先硬编码 120_000ms;推理型 scorer(tops-fmri)
 * 只需要 2 分钟,但训练类 task(EEG 解码)在 A10 上要跑 30-180 分钟,会被 kill 在第一
 * 个 batch。改为从 task.meta.timeoutMin 派生上限,并允许通过环境变量再次收紧。
 *
 * 该逻辑设计约束:
 *  - 向后兼容:所有旧 task 的 timeoutMin ≥ 5 minute,派生值 ≥ 300_000ms > 120_000ms
 *    → 现有 tops-fmri / neuro-rsc-place-cell 行为不变(sandbox 内部只有极短的哨兵
 *    输出耗时,不会因超时变化而失败)。
 *  - 安全阀:BPB_EXEC_SCORER_MAX_TIMEOUT_MIN 环境变量给运维一个"防跑飞"上限
 *    (默认 240 分钟)。低于 task.timeoutMin 时以此为准,scorer 会 fail-closed
 *    (timed out) 而不是让脚本无限期占用 CI worker。
 *  - 不越过 task 声明:如果 task 显式要 180 分钟,scorer 不能给它 60 分钟,否则
 *    静默失败;必须在 task.yaml 里显式约束。
 */
const DEFAULT_MAX_TIMEOUT_MIN = 240;
const MIN_EXEC_TIMEOUT_MS = 120_000; // 兼容 tops-fmri 时代:即使 task.timeoutMin=1 也留够 120s

export function resolveExecTimeoutMs(task: Task): number {
  const taskMin = task.meta.timeoutMin;
  const capRaw = process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN;
  const capMin = Number.isFinite(Number(capRaw)) && Number(capRaw) > 0
    ? Number(capRaw)
    : DEFAULT_MAX_TIMEOUT_MIN;
  const effectiveMin = Math.min(taskMin, capMin);
  return Math.max(MIN_EXEC_TIMEOUT_MS, effectiveMin * 60_000);
}

/** 抽哨兵间 JSON;必须是扁平 {string: number},否则 null。 */
export function extractSentinelJson(stdout: string): Record<string, number> | null {
  const i = stdout.indexOf(START);
  if (i < 0) return null;
  const j = stdout.indexOf(END, i + START.length);
  if (j < 0) return null;
  const mid = stdout.slice(i + START.length, j).trim();
  let obj: any;
  try { obj = JSON.parse(mid); } catch { return null; }
  if (obj == null || typeof obj !== "object" || Array.isArray(obj)) return null;
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v !== "number" || !Number.isFinite(v)) return null;
    out[k] = v;
  }
  return Object.keys(out).length ? out : null;
}

let injectedSandbox: ExecSandbox | null = null;
/** 测试注入沙箱;非 null 时跳过本地沙箱直接用它。 */
export function setExecSandbox(s: ExecSandbox | null): void { injectedSandbox = s; }
export function resetExecSandbox(): void { injectedSandbox = null; }

const execModule: ScorerModule = {
  // exec 维度运行时才知道(脚本决定),静态返回空;leaderboard 按实际 value 的 key 出列。
  outputs: () => [],
  build: (spec: ScorerSpec, task: Task): Scorer => {
    return async (ctx: ScoreContext): Promise<ScoreResult> => {
      const rel = typeof spec.script === "string" ? spec.script : "checks/check.sh";
      const scriptPath = resolve(task.dir, rel); // 绝对路径:沙箱以 bundle 为 cwd,相对 task.dir 会找不到
      if (!existsSync(scriptPath)) {
        return { value: {}, unscored: true, state: "scoring_failed", explanation: `exec script not found: ${rel}` };
      }
      if (process.env.BPB_SUBMISSION_ISOLATION === "docker" && spec.submission_isolation !== "container") {
        return {
          value: {}, unscored: true, state: "scoring_failed",
          explanation: "task scorer does not declare a container-isolated submission program contract",
        };
      }
      if (process.env.BPB_OFFICIAL_SCORING === "1" && process.env.BPB_SUBMISSION_ISOLATION !== "docker") {
        return { value: {}, unscored: true, state: "scoring_failed", explanation: "official exec scoring requires Docker submission isolation" };
      }
      const sandbox = injectedSandbox ?? localSubprocessSandbox();
      // 在 bundle 的 runDir 下跑;脚本通过相对路径访问 artifacts/。
      // timeoutMs 由 task.meta.timeoutMin 派生(见 resolveExecTimeoutMs 注释)。
      const timeoutMs = resolveExecTimeoutMs(task);
      const r = await sandbox.run({ command: "/bin/bash", args: [scriptPath], cwd: ctx.runDir, timeoutMs });
      if (r.timedOut) {
        const timeoutMin = Math.round(timeoutMs / 60_000);
        return { value: {}, unscored: true, state: "scoring_failed", explanation: `exec script timed out after ${timeoutMin} min` };
      }
      const scores = extractSentinelJson(r.stdout);
      if (!scores) {
        const detail = `${r.stderr}\n${r.stdout}`;
        const state = /permission denied|access denied|forbidden|\b403\b/i.test(detail)
          ? "private_access_denied"
          : /no private eval data|private (?:eval )?data.*(?:missing|not found)|private cache missing/i.test(detail)
            ? "private_data_missing"
            : "scoring_failed";
        const hint = state === "private_data_missing"
          ? "private evaluator data is missing; maintainers should run `bp-bench fetch <task> --private` and evaluator setup"
          : state === "private_access_denied"
            ? "private evaluator access was denied; verify gated-dataset permission and evaluator filesystem access"
            : `exec script produced no valid BPB_SCORES JSON (exit ${r.exitCode})`;
        return { value: {}, unscored: true, state, explanation: hint };
      }
      return { value: scores, explanation: `exec-script ${rel} (exit ${r.exitCode})` };
    };
  },
};

let registered = false;
/** 幂等注册 exec-script。 */
export function registerExecScorer(): void {
  if (registered) return;
  registerScorer("exec-script", execModule);
  registered = true;
}
