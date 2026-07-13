#!/usr/bin/env node
/**
 * check-task-size.mjs — 大小门：tasks/ 下单文件 ≤25MB；一组改动文件总量 ≤100MB。
 * 用法：node scripts/check-task-size.mjs <file1> <file2> ...
 *   不带参数：扫描 tasks/ 下所有被 git 跟踪的文件。
 * 超限以非零退出码失败（CI 用）。data body 必须走 data.lock 引用外部存储，不进 git。
 */
import { statSync } from "node:fs";
import { execSync } from "node:child_process";

const PER_FILE = 25 * 1024 * 1024;   // 25 MB
const TOTAL = 100 * 1024 * 1024;     // 100 MB

function trackedTaskFiles() {
  const out = execSync("git ls-files tasks/", { encoding: "utf8" });
  return out.split("\n").map((s) => s.trim()).filter(Boolean);
}

const args = process.argv.slice(2).filter(Boolean);
const files = (args.length ? args : trackedTaskFiles()).filter((f) => f.startsWith("tasks/"));

let total = 0;
const tooBig = [];
for (const f of files) {
  let size = 0;
  try { size = statSync(f).size; } catch { continue; } // 删除的文件忽略
  total += size;
  if (size > PER_FILE) tooBig.push([f, size]);
}

const MB = (n) => (n / 1024 / 1024).toFixed(1) + "MB";
let failed = false;
for (const [f, size] of tooBig) {
  console.error(`✗ ${f} = ${MB(size)} 超过单文件上限 25MB —— 大数据必须走 data.lock 引用外部存储，不进 git`);
  failed = true;
}
if (total > TOTAL) {
  console.error(`✗ tasks/ 改动总量 ${MB(total)} 超过 100MB`);
  failed = true;
}
if (failed) process.exit(1);
console.log(`✓ 大小门通过（${files.length} 文件，合计 ${MB(total)}）`);
