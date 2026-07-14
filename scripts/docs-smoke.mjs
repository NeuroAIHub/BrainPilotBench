import { readFileSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";

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
for (const id of taskIds) {
  if (!readme.includes(`tasks/${id}/README.md`) && !readme.includes(`tasks/${id}/task.yaml`)) {
    throw new Error(`README task table is missing a link for ${id}`);
  }
}

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
