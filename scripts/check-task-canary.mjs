#!/usr/bin/env node
/**
 * check-task-canary.mjs — 校验每个 tasks/<id>/task.yaml 首行含 canary GUID。
 * 用法:node scripts/check-task-canary.mjs <file1> ...;不带参数扫所有跟踪的 task.yaml。
 * 缺 canary 以非零退出(CI 用)。防训练集污染。
 */
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";

const CANARY = "brainpilot-bench-canary";
const args = process.argv.slice(2).filter(Boolean);
const files = args.length
  ? args.filter((f) => f.endsWith("task.yaml"))
  : execSync("git ls-files 'tasks/**/task.yaml'", { encoding: "utf8" }).split("\n").map((s) => s.trim()).filter(Boolean);

let failed = false;
for (const f of files) {
  let first = "";
  try { first = readFileSync(f, "utf8").split("\n", 1)[0] ?? ""; } catch { continue; }
  if (!first.includes(CANARY)) {
    console.error(`✗ ${f} 首行缺 canary GUID`);
    failed = true;
  }
}
if (failed) process.exit(1);
console.log(`✓ canary 检查通过(${files.length} 个 task.yaml)`);
