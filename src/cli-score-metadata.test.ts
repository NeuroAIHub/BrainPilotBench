import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import type { RunScores } from "./score.js";

const cli = join(dirname(fileURLToPath(import.meta.url)), "cli.js");

test("CLI score preserves task protocol metadata for invalid, scored, and failed bundles", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-cli-score-version-"));
  const tasks = join(root, "tasks");
  const task = join(tasks, "versioned-fixture");
  const bundle = join(root, "bundle");
  const script = join(task, "checks", "check.sh");
  try {
    mkdirSync(join(task, "prompt"), { recursive: true });
    mkdirSync(join(task, "checks"));
    mkdirSync(join(bundle, "artifacts"), { recursive: true });
    writeFileSync(join(task, "task.yaml"), [
      "id: versioned-fixture", "version: science-v2", "domain: test", "summary: versioned score fixture",
      "expected_artifacts:", "  - workspace: result.txt", "timeout_min: 1", "budget_tokens: 1",
      "requires: {gpu: false, network: false}", "evaluation:",
      "  primary_metric: {id: metric, direction: maximize, unit: fraction}", "  profile: public-v2",
      "scoring:", "  scorers:", "    - kind: exec-script", "      script: checks/check.sh", "",
    ].join("\n"));
    writeFileSync(join(task, "prompt", "turns.yaml"), '- send: "fixture"\n');
    writeFileSync(join(bundle, "artifacts", "result.txt"), "original\n");
    const writeMeta = (taskVersion?: string) => writeFileSync(join(bundle, "meta.json"), JSON.stringify({
      taskId: "versioned-fixture", agent: "fixture-agent", ...(taskVersion === undefined ? {} : { taskVersion }),
    }));
    const invoke = (): { exit: number | null; scores: RunScores } => {
      const result = spawnSync(process.execPath, [cli, "score", bundle, "--tasks", tasks], { encoding: "utf8" });
      const scores = JSON.parse(readFileSync(join(bundle, "scores.json"), "utf8")) as RunScores;
      return { exit: result.status, scores };
    };
    const protocol = { id: "metric", direction: "maximize", unit: "fraction" };
    const assertProtocol = (scores: RunScores) => {
      assert.equal(scores.taskVersion, "science-v2");
      assert.deepEqual(scores.primaryMetric, protocol);
      assert.equal(scores.evaluationProfile, "public-v2");
      assert.equal(scores.version, "fixture-agent");
    };

    writeMeta();
    let result = invoke();
    assert.equal(result.exit, 1);
    assert.equal(result.scores.state, "submission_invalid");
    assert.match(result.scores.explanation ?? "", /taskVersion/);
    assertProtocol(result.scores);

    writeMeta("science-v2");
    writeFileSync(script, "#!/bin/bash\nprintf '%s\\n' '>>>>> BPB_SCORES' '{\"metric\":0.5}' '<<<<< BPB_SCORES'\n");
    result = invoke();
    assert.equal(result.exit, 0);
    assert.equal(result.scores.state, "scored");
    assertProtocol(result.scores);

    writeFileSync(script, "#!/bin/bash\necho changed > \"$PWD/artifacts/result.txt\"\nprintf '%s\\n' '>>>>> BPB_SCORES' '{\"metric\":0.5}' '<<<<< BPB_SCORES'\n");
    result = invoke();
    assert.equal(result.exit, 1);
    assert.equal(result.scores.state, "scoring_failed");
    assert.match(result.scores.explanation ?? "", /changed during scoring/);
    assertProtocol(result.scores);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
