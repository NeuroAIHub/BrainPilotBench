import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { extractSentinelJson, setExecSandbox, resetExecSandbox } from "./exec.js";
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

function execTask(dir: string): Task {
  return {
    meta: { id: "t", domain: "d", summary: "s", expectedArtifacts: [{ workspace: "*.csv" }], timeoutMin: 5, budgetTokens: 1, requires: {}, version: "test" },
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
    assert.ok(String(res.explanation).toLowerCase().includes("timeout") || String(res.explanation).toLowerCase().includes("timed"));
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
