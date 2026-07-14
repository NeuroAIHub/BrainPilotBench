#!/usr/bin/env node
/**
 * cli.ts — bp-bench command-line.
 *
 * proxy 初始化必须在 fetch 之前(fetch/https/hf 拉数据全部经全局 dispatcher)。
 * BPB_NO_PROXY=1 可关闭(测试/CI/离线场景)。
 *
 *   bp-bench list [--tasks <dir>]
 *   bp-bench run <taskId|all> --base-url <url> [--tasks <dir>] [--out <dir>] [--version <tag>] [--workspace-root <dir>]
 *   bp-bench fetch <taskId|all> [--public|--private|--all] [--tasks <dir>]
 *   bp-bench score <runDir>                       (离线跑 scorer 写 scores.json)
 *   bp-bench leaderboard <scoresDir>
 *
 * run 的产出：每个 task 一个 run 目录，含 events.jsonl + signals.json + blank scoresheet
 * (+ artifacts/ 当 --workspace-root)。score 离线跑任务声明的 scorer 写 scores.json；
 * 人工 rubric 仍可填 scoresheet，leaderboard 汇总。
 */
import { installProxyFromEnv } from "./proxy.js";
installProxyFromEnv();
import { existsSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { loadTask } from "./loader.js";
import { discoverTaskDirs } from "./discover.js";
import { BenchRunner } from "./runner.js";
import { blankScoresheet } from "./scoring.js";
import { loadRunScores, buildLeaderboard } from "./leaderboard.js";
import { loadCategories } from "./categories.js";
import { resolveManifest, parseDatasetSelection, selectDatasets, type DatasetSelection } from "./data/index.js";
import { captureArtifacts, filesystemArtifactSource } from "./artifacts.js";
import { runScorers, type RunBundle } from "./score.js";
import { validateTask } from "./validate.js";
import { buildRelease, addRelease, loadRegistry, saveRegistry, verifyRegistry, checkFreezeVisibility } from "./registry.js";
import { loadSubmissionMeta, verifySubmission, type SubmissionMeta } from "./submission.js";
import { execFileSync } from "node:child_process";

const argv = process.argv.slice(2);
const cmd = argv[0];
const arg = (k: string, d?: string) => { const i = argv.indexOf(k); return i !== -1 ? argv[i + 1] : d; };
const G = "\x1b[32m", Y = "\x1b[33m", X = "\x1b[0m", B = "\x1b[1m";

const taskRoots = (arg("--tasks", "tasks")!).split(",").map((s) => s.trim()).filter(Boolean);
const tasksDir = taskRoots[0] ?? "tasks";
/** canonical 任务(排除 `_*` 示例):list / run all / fetch all / leaderboard / freeze 用。 */
function listTaskDirs(): string[] {
  return discoverTaskDirs(taskRoots, { includeExamples: false });
}
/** 全部任务(含 `_*` 示例):validate all + by-id 查找用(显式点名就该找得到)。 */
function listAllTaskDirs(): string[] {
  return discoverTaskDirs(taskRoots, { includeExamples: true });
}
/** by-id 解析:按 task 声明的 meta.id 匹配(非目录名),与 registry 层一致。 */
function dirsByTaskId(which: string): string[] {
  return listAllTaskDirs().filter((d) => { try { return loadTask(d).meta.id === which; } catch { return false; } });
}
/** --visibility public|heldout|all(缺省 public):list/leaderboard/freeze 默认只露 public。 */
const visibility = arg("--visibility", "public")!;
/** 按 visibility 过滤任务目录(all 不过滤;默认 public 隐藏 held-out)。 */
function filterByVisibility(dirs: string[]): string[] {
  if (visibility === "all") return dirs;
  return dirs.filter((d) => { try { return (loadTask(d).meta.visibility ?? "public") === visibility; } catch { return false; } });
}
/** 给定 taskId 集合中,visibility 命中的那部分(leaderboard 行按任务 visibility 过滤)。 */
function visibleTaskIds(): Set<string> {
  const ids = new Set<string>();
  for (const d of filterByVisibility(listAllTaskDirs())) { try { ids.add(loadTask(d).meta.id); } catch { /* skip */ } }
  return ids;
}

/** 当前 HEAD 的 commit sha;非 git 仓/git 缺失 → 清晰报错退出。 */
function gitHead(): string {
  try { return execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(); }
  catch { console.error("无法解析 git HEAD(需在 git 仓内且装了 git)"); process.exit(2); }
}
/** commit sha 是否可达(已 push/存在于本地对象库)。 */
function gitCommitExists(sha: string): boolean {
  try { execFileSync("git", ["cat-file", "-e", `${sha}^{commit}`], { stdio: "ignore" }); return true; }
  catch { return false; }
}
/** registry 路径(默认仓根 registry.json)。 */
function registryPath(): string { return arg("--registry", "registry.json")!; }

async function main() {
  if (cmd === "list") {
    for (const d of filterByVisibility(listTaskDirs())) {
      const t = loadTask(d);
      const tag = t.meta.visibility === "heldout" ? `${Y}[heldout]${X} ` : "";
      console.log(`${tag}${B}${t.meta.id}${X}  [${t.meta.domain}]  ${t.meta.summary}`);
    }
    return;
  }

  if (cmd === "run") {
    const which = argv[1];
    const baseUrl = arg("--base-url");
    if (!baseUrl) { console.error("需 --base-url"); process.exit(2); }
    const out = arg("--out", "runs")!;
    const version = arg("--version", "unknown")!;
    const dirs = which === "all" ? listTaskDirs() : dirsByTaskId(which);
    if (!dirs.length) { console.error(`找不到任务：${which}`); process.exit(2); }
    const autoFetch = argv.includes("--fetch");
    const runner = new BenchRunner({ baseUrl });
    for (const d of dirs) {
      const t = loadTask(d);
      if (autoFetch && t.datasets.length) {
        const datasets = selectDatasets(t.datasets, "public");
        console.log(`${B}— fetch ${t.meta.id}${X}  (${datasets.length} public 数据集)`);
        for (const r of await resolveManifest({ datasets })) {
          const tag = r.fetched ? `${G}fetched${X}` : `${Y}cached${X}`;
          console.log(`  ${tag}  ${r.entry.name}  → ${r.path}`);
        }
      }
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
    const runsDir = argv[1] ?? "runs";
    const repoDir = tasksDir === "tasks" ? "." : tasksDir + "/..";
    const reg = loadCategories(repoDir);
    // taskId → category(task SSOT):用全集(含示例),否则示例任务的 run 会因 categoryOf=undefined 被丢、榜空。
    const catById = new Map<string, string | undefined>();
    for (const d of listAllTaskDirs()) {
      try { const t = loadTask(d); catById.set(t.meta.id, t.meta.category); } catch { /* 跳过坏 task */ }
    }
    // 默认只渲染 public 任务的行(--visibility heldout|all 切换);按任务 visibility 过滤 runs。
    const visIds = visibleTaskIds();
    const runs = loadRunScores(runsDir).filter((r) => visIds.has(r.taskId));
    const tables = buildLeaderboard(runs, (id) => catById.get(id), reg);
    if (!tables.length) { console.log("（无 scores.json 或无 category 记录）"); return; }
    for (const tbl of tables) {
      console.log(`\n${B}# ${tbl.category}${X}`);
      console.log(`task / version            ` + tbl.metrics.map((m) => m.padEnd(14)).join(""));
      for (const row of tbl.rows) {
        const label = `${row.taskId}@${row.version}`.padEnd(26);
        const cells = row.cells.map((c) => {
          const v = c.value == null ? `${Y}—${X}` : c.value.toFixed(2);
          return `${v} (${c.coverage.scored}/${c.coverage.total})`.padEnd(14);
        }).join("");
        console.log(`${label}${cells}`);
      }
    }
    return;
  }

  if (cmd === "validate") {
    const which = argv[1];
    const dirs = which === "all" ? listAllTaskDirs() : dirsByTaskId(which);
    if (!dirs.length) { console.error(`找不到任务：${which}`); process.exit(2); }
    const repoDir = tasksDir === "tasks" ? "." : tasksDir + "/..";
    const heldoutAllowed = argv.includes("--allow-heldout");
    let hadError = false;
    for (const d of dirs) {
      const issues = await validateTask(d, repoDir, { heldoutAllowed });
      const errs = issues.filter((i) => i.level === "error");
      const warns = issues.filter((i) => i.level === "warn");
      const id = d.split("/").pop();
      if (!errs.length) console.log(`${G}✓${X} ${id}` + (warns.length ? `  (${warns.length} warn)` : ""));
      else { hadError = true; console.log(`${Y}✗ ${id}${X}`); }
      for (const i of errs) console.log(`    ${Y}error${X}: ${i.msg}`);
      for (const i of warns) console.log(`    warn: ${i.msg}`);
    }
    if (hadError) process.exit(1);
    return;
  }

  if (cmd === "fetch") {
    const which = argv[1];
    const dirs = which === "all" ? listTaskDirs() : dirsByTaskId(which);
    if (!dirs.length) { console.error(`找不到任务：${which}`); process.exit(2); }
    let selection: DatasetSelection;
    try { selection = parseDatasetSelection(argv.slice(2)); }
    catch (e) { console.error(`${Y}${(e as Error).message}${X}`); process.exit(2); }
    for (const d of dirs) {
      const t = loadTask(d);
      if (!t.datasets.length) { console.log(`${B}${t.meta.id}${X}  (无 data.lock，跳过)`); continue; }
      const datasets = selectDatasets(t.datasets, selection!);
      if (!datasets.length) { console.log(`${B}${t.meta.id}${X}  (无 ${selection!} 数据，跳过)`); continue; }
      console.log(`${B}— fetch ${t.meta.id}${X}  (${datasets.length} ${selection!} 数据集)`);
      let resolved;
      try {
        resolved = await resolveManifest({ datasets });
      } catch (e) {
        if (selection === "private" || selection === "all") {
          console.error(`${Y}私有评测数据获取失败。请先获得数据集权限并设置 HF_TOKEN。${X}`);
          console.error("申请地址: https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Private");
        }
        throw e;
      }
      for (const r of resolved) {
        const tag = r.fetched ? `${G}fetched${X}` : `${Y}cached${X}`;
        console.log(`  ${tag}  ${r.entry.name}  → ${r.path}`);
      }
    }
    return;
  }

  if (cmd === "score") {
    const judgeModel = arg("--judge-model");
    if (judgeModel) process.env.BPB_JUDGE_MODEL = judgeModel;
    const runDir = argv[1];
    if (!runDir) { console.error("用法: bp-bench score <bundle|runDir>（提交 bundle 含 meta.json,或内部 run 含 signals.json）"); process.exit(2); }
    let meta: SubmissionMeta | null = null;
    try { meta = loadSubmissionMeta(runDir); }
    catch (e) { console.error(`${Y}${(e as Error).message}${X}`); process.exit(2); }
    const sigPath = join(runDir, "signals.json");
    const signalsRaw: any = existsSync(sigPath) ? JSON.parse(readFileSync(sigPath, "utf8")) : null;
    const manifest: any = meta ?? signalsRaw;
    if (!manifest) { console.error("缺 meta.json(提交 bundle)或 signals.json(内部 run)"); process.exit(2); }
    const taskId = manifest.taskId;
    if (!taskId) { console.error("清单缺 taskId（meta.json/signals.json）"); process.exit(2); }
    if (meta && (typeof meta.agent !== "string" || !meta.agent)) { console.error("meta.json 缺 agent(被评系统标识;先跑 submit verify)"); process.exit(2); }
    const dir = dirsByTaskId(taskId)[0];
    if (!dir) { console.error(`找不到任务：${taskId}`); process.exit(2); }
    const t = loadTask(dir);
    const evPath = join(runDir, "events.jsonl");
    const events = existsSync(evPath)
      ? readFileSync(evPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
      : [];
    const version = meta ? meta.agent : (signalsRaw.version ?? "unknown");
    const runId = (meta ? `${taskId}-${meta.agent}` : (signalsRaw.runId ?? `${taskId}-${signalsRaw.version ?? "unknown"}`)).replace(/\s+/g, "-");
    const bundle: RunBundle = { runDir, runId, version, events, signals: manifest as Record<string, unknown> };
    const scores = await runScorers(t, bundle, new Date().toISOString());
    writeFileSync(join(runDir, "scores.json"), JSON.stringify(scores, null, 2));
    console.log(`${B}— score ${taskId}${X}  → ${join(runDir, "scores.json")}`);
    for (const r of scores.results) {
      const v = r.unscored ? `${Y}unscored${X}` : (typeof r.value === "number" ? String(r.value) : JSON.stringify(r.value));
      console.log(`  ${r.kind}: ${v}${r.verdict ? ` [${r.verdict}]` : ""}`);
    }
    return;
  }

  if (cmd === "freeze") {
    const name = argv[1];
    if (!name) { console.error("用法: bp-bench freeze <name> [--ref <git-ref>]（冻结当前 canonical 任务集为不可变发布）"); process.exit(2); }
    // canonical(排除 _* 示例)按 visibility 过滤:默认冻 public;--visibility heldout 冻 held-out 评测集。
    const tasks = filterByVisibility(listTaskDirs()).map((d) => loadTask(d));
    if (!tasks.length) { console.error(`无任务可冻结(visibility=${visibility})`); process.exit(2); }
    const path = registryPath();
    // 误提交守卫:held-out id/provenance 绝不进公开默认 registry.json(对称于 validate 的守卫)。
    // 判据=用户是否显式给了 --registry(给了=有意选私有目标,放行)。
    const freezeErr = checkFreezeVisibility(tasks, argv.includes("--registry"));
    if (freezeErr) { console.error(`${Y}${freezeErr}${X}`); process.exit(1); }
    const release = buildRelease(name, gitHead(), arg("--ref"), new Date().toISOString().slice(0, 10), tasks);
    let reg;
    try { reg = addRelease(loadRegistry(path), release); }
    catch (e) { console.error(`${Y}${(e as Error).message}${X}`); process.exit(1); }
    saveRegistry(path, reg);
    console.log(`${B}wrote ${path}${X}: ${name} @ ${release.commit.slice(0, 7)}${release.ref ? ` (${release.ref})` : ""}, ${release.tasks.length} tasks`);
    for (const ft of release.tasks) console.log(`  ${ft.id}@${ft.version}`);
    return;
  }

  if (cmd === "registry" && argv[1] === "verify") {
    const path = registryPath();
    const reg = loadRegistry(path);
    if (!reg.releases.length) { console.log("（无 registry.json 或无 release）"); return; }
    const taskById = new Map(listAllTaskDirs().map((d) => loadTask(d)).map((t) => [t.meta.id, t]));
    const repoDir = tasksDir === "tasks" ? "." : tasksDir + "/..";
    const cats = loadCategories(repoDir);
    const verdicts = verifyRegistry(reg, {
      taskById,
      commitExists: gitCommitExists,
      categoryExists: (c) => c in cats,
    });
    let bad = false;
    for (const v of verdicts) {
      if (v.ok) console.log(`${G}✓${X} ${v.release}  (${reg.releases.find((r) => r.name === v.release)?.tasks?.length ?? 0} tasks)`);
      else { bad = true; console.log(`${Y}✗ ${v.release}${X}`); for (const p of v.problems) console.log(`    ${p}`); }
    }
    if (bad) process.exit(1);
    return;
  }

  if (cmd === "submit" && argv[1] === "verify") {
    const dir = argv[2];
    if (!dir) { console.error("用法: bp-bench submit verify <bundle>（含 meta.json + artifacts/ 的提交目录）"); process.exit(2); }
    let meta;
    try { meta = loadSubmissionMeta(dir); }
    catch (e) { console.error(`${Y}${(e as Error).message}${X}`); process.exit(1); }
    if (!meta) { console.error(`${Y}✗${X} ${dir}: 缺 meta.json(提交清单)`); process.exit(1); }
    const taskDir = dirsByTaskId(meta.taskId)[0];
    if (!taskDir) { console.error(`找不到任务：${meta.taskId}（meta.taskId 指向未知任务）`); process.exit(2); }
    const issues = verifySubmission(loadTask(taskDir), dir);
    const errs = issues.filter((i) => i.level === "error");
    const warns = issues.filter((i) => i.level === "warn");
    if (!errs.length) console.log(`${G}✓${X} ${meta.taskId} @ ${meta.agent}` + (warns.length ? `  (${warns.length} warn)` : ""));
    else console.log(`${Y}✗ ${meta.taskId} @ ${meta.agent}${X}`);
    for (const i of errs) console.log(`    ${Y}error${X}: ${i.msg}`);
    for (const i of warns) console.log(`    warn: ${i.msg}`);
    if (errs.length) process.exit(1);
    return;
  }

  console.log("用法: bp-bench list | run <id|all> --base-url <url> [--version <tag>] [--workspace-root <dir>] [--fetch] | fetch <id|all> [--public|--private|--all] | score <bundle|runDir> [--judge-model <id>] | validate <id|all> [--allow-heldout] | leaderboard <runsDir> | freeze <name> [--ref <git-ref>] | registry verify | submit verify <bundle>");
  console.log("       通用: --tasks <dir1,dir2>(多根) | --visibility public|heldout|all(list/leaderboard/freeze;缺省 public)");
}

main().catch((e) => { console.error(e); process.exit(1); });
