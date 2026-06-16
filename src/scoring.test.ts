import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { loadTask } from "./loader.js";
import { blankScoresheet, scoresheetDimensions } from "./scoring.js";

const SURVEY = fileURLToPath(new URL("../tasks/neuro-survey-attention", import.meta.url));
const TRENDS = fileURLToPath(new URL("../tasks/neuro-trends-connectomics", import.meta.url));

test("scoresheetDimensions: 默认单 rubric scorer = rubric 维度", () => {
  assert.deepEqual(scoresheetDimensions(loadTask(SURVEY)),
    ["correctness", "completeness", "methodology", "presentation"]);
  assert.deepEqual(scoresheetDimensions(loadTask(TRENDS)),
    ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});

test("blankScoresheet: survey 逐字节 golden 不变", () => {
  const t = loadTask(SURVEY);
  const sheet = blankScoresheet(t, "neuro-survey-attention-vTEST", "vTEST", "", "2026-06-15T00:00:00.000Z");
  const golden = JSON.stringify({
    taskId: "neuro-survey-attention",
    runId: "neuro-survey-attention-vTEST",
    version: "vTEST",
    judge: "",
    scoredAt: "2026-06-15T00:00:00.000Z",
    dimensions: [
      { dimension: "correctness", score: 0, comment: "" },
      { dimension: "completeness", score: 0, comment: "" },
      { dimension: "methodology", score: 0, comment: "" },
      { dimension: "presentation", score: 0, comment: "" },
    ],
  }, null, 2);
  assert.equal(JSON.stringify(sheet, null, 2), golden);
});

test("blankScoresheet: trends 回落 DEFAULT_RUBRIC 5 维", () => {
  const t = loadTask(TRENDS);
  const sheet = blankScoresheet(t, "x", "v", "", "ts");
  assert.deepEqual(sheet.dimensions.map((d) => d.dimension),
    ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});
