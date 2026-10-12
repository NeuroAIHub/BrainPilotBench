import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTask } from "./loader.js";
import { resolveExecTimeoutMs } from "./scorer/exec.js";
import { runScorers } from "./score.js";

function withTask(meta: string, run: (dir: string) => void): void {
  const dir = mkdtempSync(join(tmpdir(), "bpb-shared-task-"));
  try {
    mkdirSync(join(dir, "prompt"));
    writeFileSync(join(dir, "prompt", "turns.yaml"), '[{"send":"model the public data"}]\n');
    writeFileSync(join(dir, "task.yaml"), [
      "id: shared-test",
      "domain: psychology-behavior",
      "summary: public response prediction",
      "expected_artifacts:",
      "  - workspace: report.md",
      "requires:",
      "  gpu: false",
      "scoring:",
      "  scorers:",
      "    - kind: exec-script",
      "      script: checks/check.sh",
      "      timeout_min: 30",
      meta,
    ].join("\n") + "\n");
    run(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("task metadata keeps explicit null research limits distinct from missing defaults", () => {
  withTask("timeout_min: null\nbudget_tokens: null", (dir) => {
    const task = loadTask(dir);
    assert.equal(task.meta.timeoutMin, null);
    assert.equal(task.meta.budgetTokens, null);
    assert.equal(task.scorers[0].timeout_min, 30);
  });
  withTask("", (dir) => {
    const task = loadTask(dir);
    assert.equal(task.meta.timeoutMin, 60);
    assert.equal(task.meta.budgetTokens, 500000);
  });
});

test("loader preserves an explicit scoring profile and rejects an empty profile", () => {
  const evaluation = "evaluation:\n  primary_metric: {id: nll, direction: minimize}\n";
  withTask(evaluation + "  profile: utf8-byte-eos-v1", dir => {
    assert.equal(loadTask(dir).meta.evaluation?.profile, "utf8-byte-eos-v1");
  });
  withTask(evaluation + "  profile: ''", dir => {
    assert.throws(() => loadTask(dir), /evaluation.profile/);
  });
});

test("primary metric direction is validated and survives scoring metadata", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bpb-primary-"));
  try {
    mkdirSync(join(dir, "prompt"));
    mkdirSync(join(dir, "checks"));
    mkdirSync(join(dir, "run", "artifacts"), { recursive: true });
    writeFileSync(join(dir, "prompt", "turns.yaml"), '[{"send":"model"}]\n');
    writeFileSync(join(dir, "checks", "check.sh"), "#!/bin/sh\nexit 0\n");
    const prefix = [
      "id: shared-test", "domain: psychology-behavior", "summary: public response prediction",
      "expected_artifacts:", "  - workspace: report.md", "timeout_min: null", "budget_tokens: null",
      "evaluation:", "  primary_metric:", "    id: mean_response_nll",
      "requires:", "  gpu: false", "scoring:", "  scorers:", "    - kind: exec-script",
      "      script: checks/check.sh", "      timeout_min: 2",
    ];
    writeFileSync(join(dir, "task.yaml"), [...prefix.slice(0, 10), "    direction: sideways", ...prefix.slice(10)].join("\n") + "\n");
    assert.throws(() => loadTask(dir), /maximize\|minimize direction/);
    writeFileSync(join(dir, "task.yaml"), [...prefix.slice(0, 10), "    direction: minimize", "    unit: nats\/response", ...prefix.slice(10)].join("\n") + "\n");
    const task = loadTask(dir);
    task.meta.version = "public-v1";
    task.meta.evaluation!.profile = "categorical-key-v1";
    const scored = await runScorers(task, {
      runDir: join(dir, "run"), runId: "run-1", version: "agent-v2", events: [], signals: {},
    }, "2026-10-12T00:00:00Z");
    assert.equal(scored.taskVersion, "public-v1");
    assert.deepEqual(scored.primaryMetric, { id: "mean_response_nll", direction: "minimize", unit: "nats/response" });
    assert.equal(scored.version, "agent-v2");
    assert.equal(scored.evaluationProfile, "categorical-key-v1");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("scorer timeout must be finite; a null research timeout still has a bounded scorer", () => {
  withTask("timeout_min: null\nbudget_tokens: null", (dir) => {
    const task = loadTask(dir);
    assert.equal(resolveExecTimeoutMs(task, Number(task.scorers[0].timeout_min)), 30 * 60_000);
    const previous = process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN;
    try {
      process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN = "10";
      assert.equal(resolveExecTimeoutMs(task, Number(task.scorers[0].timeout_min)), 10 * 60_000);
    } finally {
      if (previous === undefined) delete process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN;
      else process.env.BPB_EXEC_SCORER_MAX_TIMEOUT_MIN = previous;
    }
  });
  withTask("timeout_min: null\nbudget_tokens: null", (dir) => {
    const yaml = join(dir, "task.yaml");
    const content = "id: shared-test\ndomain: d\nsummary: s\nexpected_artifacts:\n  - workspace: report.md\n" +
      "timeout_min: null\nbudget_tokens: null\nscoring:\n  scorers:\n    - kind: exec-script\n      timeout_min: null\n";
    writeFileSync(yaml, content);
    assert.throws(() => loadTask(dir), /timeout_min must be finite/);
  });
});
