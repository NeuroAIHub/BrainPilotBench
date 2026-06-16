import { test } from "node:test";
import assert from "node:assert/strict";
import { registerScorer, getScorerModule, hasScorer, listScorers } from "./registry.js";
import type { ScorerModule } from "./types.js";

const dummy: ScorerModule = {
  outputs: () => ["dim_a", "dim_b"],
  build: () => async () => ({ value: 0, unscored: true }),
};

test("registerScorer + getScorerModule round-trips", () => {
  registerScorer("dummy-kind", dummy);
  assert.equal(hasScorer("dummy-kind"), true);
  assert.deepEqual(getScorerModule("dummy-kind").outputs({ kind: "dummy-kind" } as any, {} as any), ["dim_a", "dim_b"]);
});

test("getScorerModule throws a helpful error for unknown kind", () => {
  assert.throws(() => getScorerModule("no-such-kind"), /unknown scorer kind: no-such-kind/);
  assert.ok(listScorers().includes("dummy-kind"));
});
