#!/usr/bin/env node
/**
 * cli.ts — bp-bench command-line.
 *
 *   bp-bench list [--tasks <dir>]
 *   bp-bench run <taskId|all> --base-url <url> [--tasks <dir>] [--out <dir>] [--version <tag>]
 *   bp-bench score <runDir> --judge <name>        (生成空 scoresheet 待填)
 *   bp-bench leaderboard <scoresDir>
 *
 * run 的产出：每个 task 一个 run 目录，含 events.jsonl + signals.json + blank scoresheet。
 * 评分由人/LLM 填 scoresheet，leaderboard 汇总。
 */
import { readdirSync, existsSync, mkdirSync, writeFileSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { loadTask } from "./loader.js";
import { BenchRunner } from "./runner.js";
import { blankScoresheet, leaderboard, type ScoreRecord } from "./scoring.js";

const argv = process.argv.slice(2);
const cmd = argv[0];
const arg = (k: string, d?: string) => { const i = argv.indexOf(k); return i !== -1 ? argv[i + 1] : d; };
const G = "\x1b[32m", Y = "\x1b[33m", X = "\x1b[0m", B = "\x1b[1m";

const tasksDir = arg("--tasks", "tasks")!;
function listTaskDirs(): string[] {
  if (!existsSync(tasksDir)) return [];
  return readdirSync(tasksDir).map((d) => join(tasksDir, d)).filter((p) => statSync(p).isDirectory() && existsSync(join(p, "task.yaml")));
}

async function main() {
  if (cmd === "list") {
    for (const d of listTaskDirs()) {
      const t = loadTask(d);
      console.log(`${B}${t.meta.id}${X}  [${t.meta.domain}]  ${t.meta.summary}`);
    }
    return;
  }

  if (cmd === "run") {
    const which = argv[1];
    const baseUrl = arg("--base-url");
    if (!baseUrl) { console.error("需 --base-url"); process.exit(2); }
    const out = arg("--out", "runs")!;
    const version = arg("--version", "unknown")!;
    const dirs = which === "all" ? listTaskDirs() : listTaskDirs().filter((d) => d.endsWith("/" + which));
    if (!dirs.length) { console.error(`找不到任务：${which}`); process.exit(2); }
    const runner = new BenchRunner({ baseUrl });
    for (const d of dirs) {
      const t = loadTask(d);
      console.log(`${B}— run ${t.meta.id}${X}`);
      const res = await runner.run(t);
      const runId = `${t.meta.id}-${version}`;
      const runDir = join(out, runId);
      mkdirSync(runDir, { recursive: true });
      writeFileSync(join(runDir, "events.jsonl"), res.events.map((e) => JSON.stringify(e)).join("\n"));
      writeFileSync(join(runDir, "signals.json"), JSON.stringify({ ...res.signals, reason: res.reason, sessionId: res.sessionId, version }, null, 2));
      // 空 scoresheet（exportedAt 用 run 内最后事件 _ts，避免依赖时钟）
      const lastTs = res.events.length ? res.events[res.events.length - 1]._ts : new Date().toISOString();
      writeFileSync(join(runDir, "scoresheet.json"), JSON.stringify(blankScoresheet(t, runId, version, "", String(lastTs)), null, 2));
      const tag = res.signals.completed ? `${G}completed${X}` : `${Y}${res.reason}${X}`;
      console.log(`  ${tag}  events=${res.signals.eventCount} content=${res.signals.textContentEvents} tools=${res.signals.toolCalls} errors=${res.signals.errorEvents}  → ${runDir}`);
    }
    return;
  }

  if (cmd === "leaderboard") {
    const dir = argv[1] ?? "runs";
    const recs: ScoreRecord[] = [];
    for (const d of readdirSync(dir)) {
      const p = join(dir, d, "scoresheet.json");
      if (existsSync(p)) { try { recs.push(JSON.parse(readFileSync(p, "utf8"))); } catch {} }
    }
    const lb = leaderboard(recs);
    if (!lb.length) { console.log("（无已评分记录）"); return; }
    for (const row of lb) console.log(`${row.mean.toFixed(2)}  ${row.taskId} @ ${row.version}  (n=${row.n})`);
    return;
  }

  console.log("用法: bp-bench list | run <id|all> --base-url <url> [--version <tag>] | leaderboard <runsDir>");
}

main().catch((e) => { console.error(e); process.exit(1); });
