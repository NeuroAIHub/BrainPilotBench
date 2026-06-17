import { test } from "node:test";
import assert from "node:assert/strict";
import { valueToFloat, medianFloat } from "./metrics.js";

test("valueToFloat rubric: 1-5 → [0,1]", () => {
  assert.equal(valueToFloat(1, { rubric: true }), 0);
  assert.equal(valueToFloat(3, { rubric: true }), 0.5);
  assert.equal(valueToFloat(5, { rubric: true }), 1);
  assert.equal(valueToFloat(0, { rubric: true }), null); // 越界
  assert.equal(valueToFloat(6, { rubric: true }), null);
});

test("valueToFloat 非rubric: 数值透传 + pass/partial/fail", () => {
  assert.equal(valueToFloat(0.83), 0.83);
  assert.equal(valueToFloat(3), 3);
  assert.equal(valueToFloat("pass"), 1);
  assert.equal(valueToFloat("partial"), 0.5);
  assert.equal(valueToFloat("fail"), 0);
  assert.equal(valueToFloat("nonsense"), null);
  assert.equal(valueToFloat(NaN), null);
  assert.equal(valueToFloat(Infinity), null);
  assert.equal(valueToFloat(null), null);
});

test("medianFloat", () => {
  assert.equal(medianFloat([]), null);
  assert.equal(medianFloat([4]), 4);
  assert.equal(medianFloat([3, 5, 4]), 4);     // 奇数
  assert.equal(medianFloat([3, 4]), 3.5);      // 偶数
});
