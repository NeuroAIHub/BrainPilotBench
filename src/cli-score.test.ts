import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const CLI = join(process.cwd(), "dist", "cli.js");

function scoreEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  delete env.BPB_SUBMISSION_ISOLATION;
  delete env.BPB_OFFICIAL_SCORING;
  delete env.BPB_INFERENCE_IMAGE;
  return env;
}

function writeBundle(dir: string, includeArtifact: boolean): void {
  mkdirSync(join(dir, "artifacts"), { recursive: true });
  writeFileSync(join(dir, "meta.json"), JSON.stringify({ taskId: "example-exec-task", agent: "cli-regression" }));
  writeFileSync(join(dir, "signals.json"), JSON.stringify({ completed: false, reason: "timeout" }));
  if (includeArtifact) writeFileSync(join(dir, "artifacts", "results.csv"), "id,score\n1,10\n2,20\n3,30\n");
}

test("score CLI grades valid artifacts from an incomplete run and marks them ineligible", () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-cli-score-incomplete-"));
  try {
    writeBundle(dir, true);
    const result = spawnSync(process.execPath, [CLI, "score", dir], { cwd: process.cwd(), env: scoreEnv(), encoding: "utf8" });
    assert.equal(result.status, 0, `${result.stderr}\n${result.stdout}`);
    const scores = JSON.parse(readFileSync(join(dir, "scores.json"), "utf8"));
    assert.equal(scores.state, "scored");
    assert.equal(scores.artifactState, "valid");
    assert.equal(scores.runState, "timeout");
    assert.equal(scores.graderState, "scored");
    assert.equal(scores.leaderboardEligible, false);
    assert.equal(scores.results[0].value.rows_ok, 1);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("score CLI still rejects missing artifacts and does not run the grader", () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-cli-score-invalid-"));
  try {
    writeBundle(dir, false);
    const result = spawnSync(process.execPath, [CLI, "score", dir], { cwd: process.cwd(), env: scoreEnv(), encoding: "utf8" });
    assert.equal(result.status, 1, `${result.stderr}\n${result.stdout}`);
    const scores = JSON.parse(readFileSync(join(dir, "scores.json"), "utf8"));
    assert.equal(scores.state, "submission_invalid");
    assert.equal(scores.artifactState, "invalid");
    assert.equal(scores.graderState, "not_run");
    assert.deepEqual(scores.results, []);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
