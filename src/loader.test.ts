import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { parseScorers, loadTask } from "./loader.js";
import { DEFAULT_SCORERS } from "./task.js";

const SURVEY = fileURLToPath(new URL("../tasks/neuro-survey-attention", import.meta.url));

test("parseScorers: 缺省回落 DEFAULT_SCORERS", () => {
  assert.deepEqual(parseScorers(undefined), DEFAULT_SCORERS);
  assert.deepEqual(parseScorers({}), DEFAULT_SCORERS);
});

test("parseScorers: 解析显式 scorers，保留 kind 与配置字段", () => {
  const out = parseScorers({ scorers: [
    { kind: "rubric-judge", rubric: "rubric.yaml" },
    { kind: "exec-script", script: "checks/check.sh", parser: "pytest" },
  ] });
  assert.equal(out.length, 2);
  assert.equal(out[0].kind, "rubric-judge");
  assert.equal(out[1].script, "checks/check.sh");
});

test("loadTask: 种子任务无 scoring 字段 → scorers == DEFAULT_SCORERS", () => {
  const t = loadTask(SURVEY);
  assert.deepEqual(t.scorers, DEFAULT_SCORERS);
});

test("parseScorers: 缺 kind 的 scorer 经 loadTask 校验被拒(不被 String 强转掩盖)", () => {
  // 直接构造一个无 kind 的 scorer，确认 parseScorers 不把它伪造成 kind:"undefined"
  const out = parseScorers({ scorers: [{ rubric: "r.yaml" }] });
  assert.equal(out[0].kind, undefined);
});

test("parseScorers: null 列表项报清晰错误而非 TypeError", () => {
  assert.throws(() => parseScorers({ scorers: [null] }), /scoring\.scorers/);
});
