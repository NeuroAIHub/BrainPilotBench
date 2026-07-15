import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { extractSentinelJson, resolveExecTimeoutMs, setExecSandbox, resetExecSandbox } from "./exec.js";
import { getScorerModule } from "./registry.js";
import "./index.js"; // 注册 exec-script
import type { ExecSandbox } from "../sandbox.js";
import type { Task } from "../task.js";

test("extractSentinelJson: 抽哨兵间扁平 number JSON", () => {
  const out = "noise\n>>>>> BPB_SCORES\n{\"accuracy\": 0.83, \"runtime_ok\": 1}\n<<<<< BPB_SCORES\ntrailing";
  assert.deepEqual(extractSentinelJson(out), { accuracy: 0.83, runtime_ok: 1 });
});

test("extractSentinelJson: 无哨兵/非JSON/非扁平number → null", () => {
  assert.equal(extractSentinelJson("no sentinels"), null);
  assert.equal(extractSentinelJson(">>>>> BPB_SCORES\nnot json\n<<<<< BPB_SCORES"), null);
  assert.equal(extractSentinelJson('>>>>> BPB_SCORES\n{"a": "x"}\n<<<<< BPB_SCORES'), null); // 非 number
  assert.equal(extractSentinelJson('>>>>> BPB_SCORES\n{"a": {"b":1}}\n<<<<< BPB_SCORES'), null); // 非扁平
});

function execTask(dir: string, timeoutMin = 5): Task {
  return {
    meta: { id: "t", domain: "d", summary: "s", expectedArtifacts: [{ workspace: "*.csv" }], timeoutMin, budgetTokens: 1, requires: {}, version: "test" },
    turns: [{ send: "hi" }], askUser: {},
    rubric: { dimensions: ["x"] },
    scorers: [{ kind: "exec-script", script: "checks/check.sh", parser: "json" }], datasets: [], dir,
  };
}
function ctx(runDir: string, task: Task) {
  return { task, runDir, events: [], signals: {}, workspaceFiles: () => [] };
}

test("exec-script: 注入 fake sandbox → 哨兵指标进 value", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-exec-"));
  mkdirSync(join(dir, "checks"), { recursive: true });
  writeFileSync(join(dir, "checks", "check.sh"), "#!/bin/bash\n:");
  const fake: ExecSandbox = { run: async () => ({ stdout: ">>>>> BPB_SCORES\n{\"accuracy\":0.9}\n<<<<< BPB_SCORES", stderr: "", exitCode: 0, timedOut: false }) };
  setExecSandbox(fake);
  try {
    const t = execTask(dir);
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    const res = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(res.unscored, undefined);
    assert.deepEqual(res.value, { accuracy: 0.9 });
  } finally { resetExecSandbox(); rmSync(dir, { recursive: true, force: true }); }
});

test("exec-script: 缺 script 文件 → unscored", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-exec-"));
  setExecSandbox({ run: async () => ({ stdout: "", stderr: "", exitCode: 0, timedOut: false }) });
  try {
    const t = execTask(dir); // checks/check.sh 不存在
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    const res = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(res.unscored, true);
  } finally { resetExecSandbox(); rmSync(dir, { recursive: true, force: true }); }
});

test("exec-script: 脚本输出无哨兵 → unscored", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-exec-"));
  mkdirSync(join(dir, "checks"), { recursive: true });
  writeFileSync(join(dir, "checks", "check.sh"), "#!/bin/bash\n:");
  setExecSandbox({ run: async () => ({ stdout: "ran but no sentinel", stderr: "", exitCode: 0, timedOut: false }) });
  try {
    const t = execTask(dir);
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    const res = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(res.unscored, true);
  } finally { resetExecSandbox(); rmSync(dir, { recursive: true, force: true }); }
});

test("exec-script: 超时 → unscored", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-exec-"));
  mkdirSync(join(dir, "checks"), { recursive: true });
  writeFileSync(join(dir, "checks", "check.sh"), "#!/bin/bash\n:");
  setExecSandbox({ run: async () => ({ stdout: "", stderr: "", exitCode: null, timedOut: true }) });
  try {
    const t = execTask(dir);
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    const res = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(res.unscored, true);
    assert.equal(res.state, "scoring_failed");
    assert.ok(String(res.explanation).toLowerCase().includes("timeout") || String(res.explanation).toLowerCase().includes("timed"));
  } finally { resetExecSandbox(); rmSync(dir, { recursive: true, force: true }); }
});

test("exec-script: Docker scoring fails closed for tasks without an isolation contract", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-exec-isolation-"));
  const previous = process.env.BPB_SUBMISSION_ISOLATION;
  mkdirSync(join(dir, "checks"), { recursive: true });
  writeFileSync(join(dir, "checks", "check.sh"), "#!/bin/bash\n:");
  setExecSandbox({ run: async () => { throw new Error("must not run"); } });
  try {
    process.env.BPB_SUBMISSION_ISOLATION = "docker";
    const t = execTask(dir);
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    const res = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(res.unscored, true);
    assert.match(res.explanation ?? "", /does not declare/);
  } finally {
    if (previous === undefined) delete process.env.BPB_SUBMISSION_ISOLATION; else process.env.BPB_SUBMISSION_ISOLATION = previous;
    resetExecSandbox();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("exec-script: missing and denied private evaluator data get structured states", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-exec-state-"));
  mkdirSync(join(dir, "checks"), { recursive: true });
  writeFileSync(join(dir, "checks", "check.sh"), "#!/bin/bash\n:");
  try {
    const t = execTask(dir);
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    setExecSandbox({ run: async () => ({ stdout: "", stderr: "no private eval data found", exitCode: 0, timedOut: false }) });
    const missing = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(missing.state, "private_data_missing");
    setExecSandbox({ run: async () => ({ stdout: "", stderr: "Permission denied", exitCode: 1, timedOut: false }) });
    const denied = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(denied.state, "private_access_denied");
  } finally { resetExecSandbox(); rmSync(dir, { recursive: true, force: true }); }
});

// resolveExecTimeoutMs: 训练类 task 需要长 timeout,旧硬编码 120_000 会 kill 掉长跑 scorer。
test("resolveExecTimeoutMs: task.timeoutMin=5 → 300_000ms(向后兼容 tops-fmri/rsc)", () => {
  const t = execTask("/tmp/x", 5);
  assert.equal(resolveExecTimeoutMs(t), 300_000);
});

test("resolveExecTimeoutMs: task.timeoutMin=180 → 10_800_000ms(EEG 训练类可跑 3 小时)", () => {
  const t = execTask("/tmp/x", 180);
  assert.equal(resolveExecTimeoutMs(t), 180 * 60_000);
});

test("resolveExecTimeoutMs: BPB_EXEC_SCORER_MAX_TIMEOUT_MIN 环境变量作硬上限,可截断 task 请求", () => {
  const t = execTask("/tmp/x", 180);
  const previous = process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN;
  try {
    process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN = "30";
    assert.equal(resolveExecTimeoutMs(t), 30 * 60_000); // task 想要 180,cap 到 30
    // 非法值/负值 → 回落默认 240 上限,不影响 180 的请求
    process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN = "not-a-number";
    assert.equal(resolveExecTimeoutMs(t), 180 * 60_000);
    process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN = "-1";
    assert.equal(resolveExecTimeoutMs(t), 180 * 60_000);
  } finally {
    if (previous === undefined) delete process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN;
    else process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN = previous;
  }
});

test("resolveExecTimeoutMs: task.timeoutMin=1 → 仍保 120_000ms 下限(避免 script 极短意外 kill)", () => {
  const t = execTask("/tmp/x", 1);
  assert.equal(resolveExecTimeoutMs(t), 120_000);
});

test("exec-script: 超时 error message 携带派生分钟值", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-exec-"));
  mkdirSync(join(dir, "checks"), { recursive: true });
  writeFileSync(join(dir, "checks", "check.sh"), "#!/bin/bash\n:");
  setExecSandbox({ run: async () => ({ stdout: "", stderr: "", exitCode: null, timedOut: true }) });
  try {
    const t = execTask(dir, 180);
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    const res = await scorer(ctx(join(dir, "run"), t) as any);
    assert.equal(res.unscored, true);
    assert.match(res.explanation ?? "", /timed out after 180 min/);
  } finally { resetExecSandbox(); rmSync(dir, { recursive: true, force: true }); }
});

// 回归:task.dir 为相对路径 + bundle 为另一个 cwd 时,脚本路径必须绝对化才找得到(真沙箱)。
// 旧实现 join(task.dir, rel) 是相对 repo 根的路径,沙箱以 bundle 为 cwd 跑 bash → 找不到脚本 → unscored。
test("exec-script: 相对 task.dir + 异 cwd bundle 仍能跑(绝对化回归)", async () => {
  resetExecSandbox(); // 用真 localSubprocessSandbox
  const absTask = mkdtempSync(join(tmpdir(), "bpb-exectask-"));
  const bundle = mkdtempSync(join(tmpdir(), "bpb-bundle-"));
  mkdirSync(join(absTask, "checks"), { recursive: true });
  writeFileSync(join(absTask, "checks", "check.sh"), "#!/bin/bash\necho '>>>>> BPB_SCORES'\necho '{\"ok\":1}'\necho '<<<<< BPB_SCORES'\n");
  const relTask = relative(process.cwd(), absTask); // 相对路径 → 复现旧 bug
  try {
    const t = execTask(relTask);
    const scorer = getScorerModule("exec-script").build(t.scorers[0], t);
    const res = await scorer(ctx(bundle, t) as any); // runDir(cwd)=bundle ≠ task.dir
    assert.equal(res.unscored, undefined, JSON.stringify(res));
    assert.deepEqual(res.value, { ok: 1 });
  } finally { rmSync(absTask, { recursive: true, force: true }); rmSync(bundle, { recursive: true, force: true }); }
});
