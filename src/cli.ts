#!/usr/bin/env node
/**
 * cli.ts — bp-bench command-line.
 *
 * proxy 初始化必须在 fetch 之前(fetch/https/hf 拉数据全部经全局 dispatcher)。
 * BPB_NO_PROXY=1 可关闭(测试/CI/离线场景)。
 *
 *   bp-bench list [--tasks <dir>]
 *   bp-bench prepare <taskId> [--workspace <dir>] [--fetch]
 *   bp-bench run <taskId|all> --adapter <brainpilot|command|manual> [adapter options]
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
import { existsSync, writeFileSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { loadTask } from "./loader.js";
import { discoverTaskDirs } from "./discover.js";
import { loadRunScores, buildLeaderboard } from "./leaderboard.js";
import { renderLeaderboard, type LeaderboardFormat } from "./leaderboard-format.js";
import { loadCategories } from "./categories.js";
import { resolveManifest, parseDatasetSelection, selectDatasets, type DatasetSelection } from "./data/index.js";
import { runScorers, type RunBundle, type RunScores } from "./score.js";
import { validateTask } from "./validate.js";
import { buildRelease, addRelease, loadRegistry, saveRegistry, verifyRegistry, checkFreezeVisibility } from "./registry.js";
import { loadSubmissionMeta, verifySubmission, type SubmissionMeta } from "./submission.js";
import { execFileSync } from "node:child_process";
import { BrainPilotAdapter, CommandAdapter, ManualAdapter, type AgentAdapter } from "./adapters.js";
import { buildSubmissionBundle, prepareWorkspace, readManualRunState, syntheticRunResult, writeManualRunState } from "./workflow.js";
import type { DatasetEntry, FetchProgress } from "./data/types.js";
import { runDoctor } from "./doctor.js";

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

function safeRunId(value: string): string {
  return value.replace(/[^A-Za-z0-9._@-]+/g, "-").replace(/^-+|-+$/g, "") || "run";
}

function formatBytes(bytes: number): string {
  const units = ["B", "KiB", "MiB", "GiB"];
  let value = bytes, unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function downloadProgress() {
  const lastBucket = new Map<string, number>();
  const started = new Map<string, { at: number; bytes: number }>();
  return (entry: DatasetEntry, progress: FetchProgress) => {
    const total = progress.totalBytes ?? entry.bytes;
    const percent = total > 0 ? Math.min(100, Math.floor(progress.downloadedBytes / total * 100)) : 0;
    const origin = started.get(entry.name) ?? { at: Date.now(), bytes: progress.downloadedBytes };
    started.set(entry.name, origin);
    const seconds = Math.max(0.001, (Date.now() - origin.at) / 1000);
    const speed = Math.max(0, (progress.downloadedBytes - origin.bytes) / seconds);
    const eta = speed > 0 ? Math.ceil((total - progress.downloadedBytes) / speed) : undefined;
    const rate = speed > 0 ? `, ${formatBytes(speed)}/s` : "";
    const remaining = eta !== undefined && eta >= 0 ? `, ETA ${eta}s` : "";
    if (process.stderr.isTTY) {
      const resume = progress.resumedFrom > 0 ? `, resumed ${formatBytes(progress.resumedFrom)}` : "";
      process.stderr.write(`\r  downloading ${entry.name}: ${percent}% (${formatBytes(progress.downloadedBytes)}/${formatBytes(total)}${rate}${remaining}${resume})`);
      if (progress.downloadedBytes >= total) process.stderr.write("\n");
      return;
    }
    const bucket = Math.floor(percent / 10);
    if (bucket > (lastBucket.get(entry.name) ?? -1)) {
      lastBucket.set(entry.name, bucket);
      console.error(`  downloading ${entry.name}: ${percent}%${rate}${remaining}`);
    }
  };
}

async function fetchPublicTaskData(task: ReturnType<typeof loadTask>): Promise<void> {
  const datasets = selectDatasets(task.datasets, "public");
  if (!datasets.length) return;
  console.log(`${B}— fetch ${task.meta.id}${X}  (${datasets.length} public 数据集)`);
  for (const result of await resolveManifest({ datasets }, { onProgress: downloadProgress() })) {
    const tag = result.fetched ? `${G}fetched${X}` : `${Y}cached${X}`;
    console.log(`  ${tag}  ${result.entry.name}  → ${result.path}`);
  }
}

async function main() {
  if (cmd === "list") {
    for (const d of filterByVisibility(listTaskDirs())) {
      const t = loadTask(d);
      const tag = t.meta.visibility === "heldout" ? `${Y}[heldout]${X} ` : "";
      console.log(`${tag}${B}${t.meta.id}${X}  [${t.meta.domain}]  ${t.meta.summary}`);
    }
    return;
  }

  if (cmd === "doctor") {
    const which = argv[1] && !argv[1].startsWith("--") ? argv[1] : undefined;
    const dir = which ? dirsByTaskId(which)[0] : undefined;
    if (which && !dir) { console.error(`找不到任务：${which}`); process.exit(2); }
    const checks = await runDoctor({
      task: dir ? loadTask(dir) : undefined,
      privateData: argv.includes("--private"),
      baseUrl: arg("--base-url"),
    });
    const icons = { pass: `${G}✓${X}`, warn: `${Y}!${X}`, fail: `${Y}✗${X}` };
    for (const check of checks) {
      console.log(`${icons[check.status]} ${check.id}: ${check.message}`);
      if (check.fix) for (const line of check.fix.split("\n")) console.log(`    ${line}`);
    }
    if (checks.some((check) => check.status === "fail")) process.exit(1);
    return;
  }

  if (cmd === "prepare") {
    const which = argv[1];
    const dir = dirsByTaskId(which)[0];
    if (!dir) { console.error(`找不到任务：${which}`); process.exit(2); }
    const task = loadTask(dir);
    if (argv.includes("--fetch")) await fetchPublicTaskData(task);
    const workspaceDir = resolve(arg("--workspace", join(".bpb", "workspaces", `${task.meta.id}-manual`))!);
    const prepared = prepareWorkspace(task, workspaceDir);
    console.log(`${G}✓${X} prepared ${task.meta.id} → ${workspaceDir}`);
    console.log(`  prompt: ${prepared.promptPath}`);
    console.log(`  setup: ${prepared.setupRan ? "public data staged" : "not required"}`);
    return;
  }

  if (cmd === "run") {
    const which = argv[1];
    const out = arg("--out", "runs")!;
    const adapterKind = arg("--adapter", "brainpilot")!;
    if (!(["brainpilot", "command", "manual"] as string[]).includes(adapterKind)) {
      console.error(`未知 adapter: ${adapterKind}`); process.exit(2);
    }
    const agent = arg("--agent", arg("--version", `${adapterKind}@unknown`))!;

    const resume = arg("--resume");
    if (resume) {
      const runDir = resolve(existsSync(resume) ? resume : join(out, resume));
      const state = readManualRunState(runDir);
      const taskDir = dirsByTaskId(state.taskId)[0];
      if (!taskDir) throw new Error(`找不到任务：${state.taskId}`);
      const task = loadTask(taskDir);
      if (which && which !== state.taskId) throw new Error(`resume task mismatch: command=${which}, state=${state.taskId}`);
      if (task.meta.version !== state.taskVersion) {
        throw new Error(`task changed since prepare: state=${state.taskVersion}, current=${task.meta.version}`);
      }
      const built = await buildSubmissionBundle({
        task,
        result: syntheticRunResult(task.meta.id, state.workspaceDir, true, Date.now()),
        workspaceDir: state.workspaceDir,
        runDir,
        agent: state.agent,
      });
      const errors = built.issues.filter((issue) => issue.level === "error");
      for (const issue of built.issues) console.log(`  ${issue.level}: ${issue.msg}`);
      if (errors.length) throw new Error(`manual submission is incomplete (${errors.length} errors); continue work in ${state.workspaceDir} and resume again`);
      console.log(`${G}✓${X} resumed and verified ${state.taskId} → ${runDir}`);
      return;
    }

    const dirs = which === "all" ? listTaskDirs() : dirsByTaskId(which);
    if (!dirs.length) { console.error(`找不到任务：${which}`); process.exit(2); }
    if (which === "all" && arg("--run-id")) { console.error("--run-id cannot be used with run all"); process.exit(2); }
    const autoFetch = argv.includes("--fetch");
    for (const d of dirs) {
      const t = loadTask(d);
      if (autoFetch) await fetchPublicTaskData(t);
      const runId = safeRunId(arg("--run-id", `${t.meta.id}-${agent}`)!);
      const runDir = resolve(join(out, runId));
      const configuredRoot = arg("--workspace-root", process.env.BRAINPILOT_WORKSPACE_ROOT);
      const localRoot = resolve(configuredRoot ?? join(".bpb", "workspaces"));
      const workspaceDir = resolve(arg("--workspace", join(localRoot, runId))!);

      let adapter: AgentAdapter;
      if (adapterKind === "brainpilot") {
        if (!configuredRoot) {
          console.error("brainpilot adapter 需要 --workspace-root，或设置 BRAINPILOT_WORKSPACE_ROOT");
          process.exit(2);
        }
        adapter = new BrainPilotAdapter({
          baseUrl: arg("--base-url", process.env.BRAINPILOT_BASE_URL ?? "http://127.0.0.1:9001")!,
          workspaceRoot: localRoot,
        });
      } else if (adapterKind === "command") {
        const command = arg("--command");
        if (!command) { console.error("command adapter 需要 --command"); process.exit(2); }
        adapter = new CommandAdapter({ command, workspaceDir });
      } else {
        adapter = new ManualAdapter(workspaceDir);
      }

      console.log(`${B}— run ${t.meta.id}${X}  adapter=${adapter.kind}`);
      const execution = await adapter.run(t);
      if (execution.status === "pending") {
        writeManualRunState(runDir, {
          taskId: t.meta.id,
          taskVersion: t.meta.version,
          agent,
          adapter: "manual",
          workspaceDir: execution.workspaceDir,
          createdAt: new Date().toISOString(),
        });
        console.log(`${Y}pending${X}: work in ${execution.workspaceDir}`);
        console.log(`  prompt: ${join(execution.workspaceDir, ".bpb", "TASK_PROMPT.md")}`);
        console.log("  security: run the Agent without HF_TOKEN or BPB_*_PRIVATE_* evaluator variables");
        console.log(`  resume: bp-bench run ${t.meta.id} --adapter manual --resume ${runDir}`);
        continue;
      }

      const built = await buildSubmissionBundle({
        task: t,
        result: execution.result!,
        workspaceDir: execution.workspaceDir,
        runDir,
        agent,
      });
      const errors = built.issues.filter((issue) => issue.level === "error");
      console.log(`  artifacts: ${built.artifacts.length} → ${join(runDir, "artifacts")}`);
      for (const issue of built.issues) console.log(`  ${issue.level}: ${issue.msg}`);
      if (errors.length) throw new Error(`submission bundle failed verification (${errors.length} errors): ${runDir}`);
      console.log(`${G}✓ completed and verified${X} → ${runDir}`);
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
    const format = arg("--format", "table") as LeaderboardFormat;
    if (!["table", "json", "markdown", "csv"].includes(format)) {
      console.error("--format must be table, json, markdown, or csv"); process.exit(2);
    }
    console.log(renderLeaderboard(tables, format));
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
        resolved = await resolveManifest({ datasets }, { onProgress: downloadProgress() });
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
    if (!runDir) { console.error("用法: bp-bench score <bundle>（必须含 meta.json + artifacts/）"); process.exit(2); }
    let meta: SubmissionMeta | null = null;
    try { meta = loadSubmissionMeta(runDir); }
    catch (e) { console.error(`${Y}${(e as Error).message}${X}`); process.exit(2); }
    if (!meta) { console.error("submission_invalid: 缺 meta.json；先生成并验证 submission bundle"); process.exit(2); }
    const sigPath = join(runDir, "signals.json");
    const signalsRaw: any = existsSync(sigPath) ? JSON.parse(readFileSync(sigPath, "utf8")) : null;
    const taskId = meta.taskId;
    if (!taskId) { console.error("submission_invalid: meta.json 缺 taskId"); process.exit(2); }
    if (typeof meta.agent !== "string" || !meta.agent) { console.error("submission_invalid: meta.json 缺 agent"); process.exit(2); }
    const dir = dirsByTaskId(taskId)[0];
    if (!dir) { console.error(`找不到任务：${taskId}`); process.exit(2); }
    const t = loadTask(dir);
    const evPath = join(runDir, "events.jsonl");
    const events = existsSync(evPath)
      ? readFileSync(evPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
      : [];
    const version = meta.agent;
    const runId = `${taskId}-${meta.agent}`.replace(/\s+/g, "-");
    const scoredAt = new Date().toISOString();
    const contractIssues = verifySubmission(t, runDir);
    const contractErrors = contractIssues.filter((issue) => issue.level === "error");
    if (signalsRaw?.completed === false) contractErrors.push({ level: "error", msg: "agent run is not completed" });
    if (contractErrors.length) {
      const invalid: RunScores = {
        taskId, runId, version, scoredAt, state: "submission_invalid",
        explanation: contractErrors.map((issue) => issue.msg).join("; "), results: [],
      };
      writeFileSync(join(runDir, "scores.json"), JSON.stringify(invalid, null, 2));
      console.error(`${Y}submission_invalid${X}: ${invalid.explanation}`);
      process.exitCode = 1;
      return;
    }
    console.log(`${G}ready_to_score${X}: bundle verified; scoring starts after Agent completion`);
    const bundle: RunBundle = { runDir, runId, version, events, signals: (signalsRaw ?? meta) as Record<string, unknown> };
    let scores: RunScores;
    try {
      scores = await runScorers(t, bundle, scoredAt);
    } catch (error) {
      scores = { taskId, runId, version, scoredAt, state: "scoring_failed", explanation: (error as Error).message, results: [] };
    }
    writeFileSync(join(runDir, "scores.json"), JSON.stringify(scores, null, 2));
    console.log(`${B}— score ${taskId}${X}  state=${scores.state} → ${join(runDir, "scores.json")}`);
    if (scores.explanation) console.log(`  ${scores.explanation}`);
    for (const r of scores.results) {
      const v = r.unscored ? `${Y}${r.state ?? "scoring_failed"}${X}` : (typeof r.value === "number" ? String(r.value) : JSON.stringify(r.value));
      console.log(`  ${r.kind}: ${v}${r.verdict ? ` [${r.verdict}]` : ""}${r.explanation ? ` — ${r.explanation}` : ""}`);
    }
    if (scores.state !== "scored") process.exitCode = 1;
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
    if (!errs.length) console.log(`${G}ready_to_score${X} ${meta.taskId} @ ${meta.agent}` + (warns.length ? `  (${warns.length} warn)` : ""));
    else console.log(`${Y}✗ ${meta.taskId} @ ${meta.agent}${X}`);
    for (const i of errs) console.log(`    ${Y}error${X}: ${i.msg}`);
    for (const i of warns) console.log(`    warn: ${i.msg}`);
    if (errs.length) process.exit(1);
    return;
  }

  console.log("用法: bp-bench list | doctor [id] [--private] [--base-url <url>] | prepare <id> [--workspace <dir>] [--fetch] | run <id|all> --adapter brainpilot|command|manual [--agent <id>] [--resume <runDir>] | fetch <id|all> [--public|--private|--all] | score <bundle> [--judge-model <id>] | validate <id|all> [--allow-heldout] | leaderboard <runsDir> [--format table|json|markdown|csv] | freeze <name> [--ref <git-ref>] | registry verify | submit verify <bundle>");
  console.log("       通用: --tasks <dir1,dir2>(多根) | --visibility public|heldout|all(list/leaderboard/freeze;缺省 public)");
}

main().catch((e) => {
  const error = e instanceof Error ? e : new Error(String(e));
  console.error(`${Y}${error.message}${X}`);
  if (argv.includes("--verbose") && error.stack) console.error(error.stack);
  process.exit(1);
});
