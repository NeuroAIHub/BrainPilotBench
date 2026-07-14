import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { loadTask } from "./loader.js";
import { blankScoresheet, scoresheetDimensions } from "./scoring.js";

const RUBRIC_TASK = fileURLToPath(new URL("../test/fixtures/rubric-task", import.meta.url));
const DEFAULT_RUBRIC_TASK = fileURLToPath(new URL("../test/fixtures/default-rubric-task", import.meta.url));

test("scoresheetDimensions: 默认单 rubric scorer = rubric 维度", () => {
  assert.deepEqual(scoresheetDimensions(loadTask(RUBRIC_TASK)),
    ["correctness", "completeness", "methodology", "presentation"]);
  assert.deepEqual(scoresheetDimensions(loadTask(DEFAULT_RUBRIC_TASK)),
    ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});

test("blankScoresheet: custom-rubric fixture golden remains stable", () => {
  const t = loadTask(RUBRIC_TASK);
  const sheet = blankScoresheet(t, "test-rubric-task-vTEST", "vTEST", "", "2026-07-14T00:00:00.000Z");
  const golden = JSON.stringify({
    taskId: "test-rubric-task",
    runId: "test-rubric-task-vTEST",
    version: "vTEST",
    judge: "",
    scoredAt: "2026-07-14T00:00:00.000Z",
    dimensions: [
      { dimension: "correctness", score: 0, comment: "" },
      { dimension: "completeness", score: 0, comment: "" },
      { dimension: "methodology", score: 0, comment: "" },
      { dimension: "presentation", score: 0, comment: "" },
    ],
  }, null, 2);
  assert.equal(JSON.stringify(sheet, null, 2), golden);
});

test("blankScoresheet: fixture without rubric falls back to DEFAULT_RUBRIC", () => {
  const t = loadTask(DEFAULT_RUBRIC_TASK);
  const sheet = blankScoresheet(t, "x", "v", "", "ts");
  assert.deepEqual(sheet.dimensions.map((d) => d.dimension),
    ["correctness", "completeness", "methodology", "reproducibility", "presentation"]);
});
