import { readFileSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { discoverTaskDirs } from "../dist/discover.js";
import { loadTask } from "../dist/loader.js";
import { existsSync } from "node:fs";

const root = process.cwd();
const readme = readFileSync(join(root, "README.md"), "utf8");

function run(args) {
  const result = spawnSync(process.execPath, [join(root, "dist", "cli.js"), ...args], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, BPB_NO_PROXY: "1" },
  });
  if (result.status !== 0) {
    throw new Error(`docs smoke failed: bp-bench ${args.join(" ")}\n${result.stdout}\n${result.stderr}`);
  }
  return `${result.stdout}${result.stderr}`;
}

const listed = run(["list"]);
const taskIds = [...listed.matchAll(/\x1b\[1m([^\x1b]+)\x1b\[0m/g)].map((match) => match[1]);
if (taskIds.length < 1) throw new Error("bp-bench list returned no canonical tasks");
const catalog = JSON.parse(readFileSync(join(root, "tasks/catalog.json"), "utf8"));
for (const dir of discoverTaskDirs(["tasks"])) {
  const task = loadTask(dir);
  if (!catalog.tasks.some(row => row.task_id === task.meta.id && row.directory === dir && row.entry_kind === "runnable"))
    throw new Error(`Collection catalog is missing ${task.meta.id}`);
  if (!existsSync(join(dir, "README.md"))) throw new Error(`Task README is missing: ${dir}`);
}
if (!readme.includes("tasks/catalog.json")) throw new Error("README must link the collection catalog");

run(["submit", "verify", "examples/submission"]);
run(["score", "examples/submission"]);
run(["leaderboard", "examples"]);
rmSync(join(root, "examples", "submission", "scores.json"), { force: true });

for (const required of [
  "npm ci",
  "bp-bench doctor tops-fmri",
  "bp-bench fetch tops-fmri --public",
  "--adapter brainpilot",
  "--adapter manual",
  "bp-bench fetch tops-fmri --private",
]) {
  if (!readme.includes(required)) throw new Error(`README quick start is missing: ${required}`);
}

console.log(`docs smoke passed (${taskIds.length} canonical tasks)`);
