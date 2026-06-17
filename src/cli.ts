#!/usr/bin/env node
/**
 * cli.ts — bp-bench command-line.
 *
 *   bp-bench list [--tasks <dir>]
 *   bp-bench run <taskId|all> --base-url <url> [--tasks <dir>] [--out <dir>] [--version <tag>] [--workspace-root <dir>]
 *   bp-bench fetch <taskId|all> [--tasks <dir>]   (按 data.lock 拉取数据集)
 *   bp-bench score <runDir>                       (离线跑 scorer 写 scores.json)
 *   bp-bench leaderboard <scoresDir>
 *
 * run 的产出：每个 task 一个 run 目录，含 events.jsonl + signals.json + blank scoresheet
 * (+ artifacts/ 当 --workspace-root)。score 离线跑任务声明的 scorer 写 scores.json；
 * 人工 rubric 仍可填 scoresheet，leaderboard 汇总。
 */
import { readdirSync, existsSync, mkdirSync, writeFileSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { loadTask } from "./loader.js";
import { BenchRunner } from "./runner.js";
import { blankScoresheet, leaderboard, type ScoreRecord } from "./scoring.js";
import { resolveManifest } from "./data/index.js";
import { captureArtifacts, filesystemArtifactSource } from "./artifacts.js";
import { runScorers, type RunBundle } from "./score.js";

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
      writeFileSync(join(runDir, "signals.json"), JSON.stringify({ taskId: t.meta.id, ...res.signals, reason: res.reason, sessionId: res.sessionId, version }, null, 2));
      // 空 scoresheet（exportedAt 用 run 内最后事件 _ts，避免依赖时钟）
      const lastTs = res.events.length ? res.events[res.events.length - 1]._ts : new Date().toISOString();
      writeFileSync(join(runDir, "scoresheet.json"), JSON.stringify(blankScoresheet(t, runId, version, "", String(lastTs)), null, 2));
      const wsRoot = arg("--workspace-root");
      if (wsRoot) {
        const globs = t.meta.expectedArtifacts.map((a) => a.workspace);
        const got = await captureArtifacts(filesystemArtifactSource(wsRoot), res.sessionId, globs, join(runDir, "artifacts"));
        console.log(`  artifacts: ${got.length} 个回收 → ${join(runDir, "artifacts")}`);
      }
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

  if (cmd === "fetch") {
    const which = argv[1];
    const dirs = which === "all" ? listTaskDirs() : listTaskDirs().filter((d) => d.endsWith("/" + which));
    if (!dirs.length) { console.error(`找不到任务：${which}`); process.exit(2); }
    for (const d of dirs) {
      const t = loadTask(d);
      if (!t.datasets.length) { console.log(`${B}${t.meta.id}${X}  (无 data.lock，跳过)`); continue; }
      console.log(`${B}— fetch ${t.meta.id}${X}  (${t.datasets.length} 数据集)`);
      const resolved = await resolveManifest({ datasets: t.datasets });
      for (const r of resolved) {
        const tag = r.fetched ? `${G}fetched${X}` : `${Y}cached${X}`;
        console.log(`  ${tag}  ${r.entry.name}  → ${r.path}`);
      }
    }
    return;
  }

  if (cmd === "score") {
    const runDir = argv[1];
    if (!runDir || !existsSync(join(runDir, "signals.json"))) {
      console.error("用法: bp-bench score <runDir>（需含 signals.json 的 run 目录）"); process.exit(2);
    }
    const signals = JSON.parse(readFileSync(join(runDir, "signals.json"), "utf8"));
    const taskId = signals.taskId;
    if (!taskId) { console.error("signals.json 缺 taskId（用新版 run 重跑，或手动补）"); process.exit(2); }
    const dir = listTaskDirs().find((d) => d.endsWith("/" + taskId));
    if (!dir) { console.error(`找不到任务：${taskId}`); process.exit(2); }
    const t = loadTask(dir);
    const evPath = join(runDir, "events.jsonl");
    const events = existsSync(evPath)
      ? readFileSync(evPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
      : [];
    const bundle: RunBundle = { runDir, runId: signals.runId ?? `${taskId}-${signals.version ?? "unknown"}`, version: signals.version ?? "unknown", events, signals };
    const scores = await runScorers(t, bundle, new Date().toISOString());
    writeFileSync(join(runDir, "scores.json"), JSON.stringify(scores, null, 2));
    console.log(`${B}— score ${taskId}${X}  → ${join(runDir, "scores.json")}`);
    for (const r of scores.results) {
      const v = r.unscored ? `${Y}unscored${X}` : (typeof r.value === "number" ? String(r.value) : JSON.stringify(r.value));
      console.log(`  ${r.kind}: ${v}${r.verdict ? ` [${r.verdict}]` : ""}`);
    }
    return;
  }

  console.log("用法: bp-bench list | run <id|all> --base-url <url> [--version <tag>] [--workspace-root <dir>] | fetch <id|all> | score <runDir> | leaderboard <runsDir>");
}

main().catch((e) => { console.error(e); process.exit(1); });
