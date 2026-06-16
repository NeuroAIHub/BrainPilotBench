import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { loadTask } from "../loader.js";
import { getScorerModule } from "./registry.js";
import "./index.js"; // 触发 rubric 注册

const SURVEY = fileURLToPath(new URL("../../tasks/neuro-survey-attention", import.meta.url));
const TRENDS = fileURLToPath(new URL("../../tasks/neuro-trends-connectomics", import.meta.url));

test("rubric-judge 注册并对有 rubric.yaml 的任务给出 4 维", () => {
  const t = loadTask(SURVEY);
  const dims = getScorerModule("rubric-judge").outputs(t.scorers[0], t);
  assert.deepEqual(dims, ["correctness", "completeness", "methodology", "presentation"]);
});

test("rubric 对无 rubric.yaml 的任务回落 DEFAULT_RUBRIC 5 维", () => {
  const t = loadTask(TRENDS);
  const dims = getScorerModule("rubric-judge").outputs(t.scorers[0], t);
  assert.deepEqual(dims, ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});

test("rubric.build().score() 本期返回 unscored（Phase 3 承重墙）", async () => {
  const t = loadTask(SURVEY);
  const scorer = getScorerModule("rubric-human").build(t.scorers[0], t);
  const res = await scorer({ task: t, runDir: "/tmp", events: [], signals: {}, workspaceFiles: () => [] });
  assert.equal(res.unscored, true);
  assert.deepEqual(Object.keys(res.value as Record<string, number>), ["correctness", "completeness", "methodology", "presentation"]);
});
