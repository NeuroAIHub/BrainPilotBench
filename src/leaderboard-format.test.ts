import { test } from "node:test";
import assert from "node:assert/strict";
import { renderLeaderboard } from "./leaderboard-format.js";
import type { CategoryTable } from "./leaderboard.js";

const tables: CategoryTable[] = [{
  category: "fmri-analysis",
  metrics: ["score", "study4_score"],
  rows: [{
    taskId: "tops-fmri", version: "agent@1", states: { scored: 1, private_data_missing: 1 },
    cells: [
      { metric: "score", value: 0.449085, coverage: { scored: 1, total: 2 } },
      { metric: "study4_score", value: null, coverage: { scored: 0, total: 2 } },
    ],
  }],
}];

test("renderLeaderboard table uses a narrow-terminal-safe long layout", () => {
  const out = renderLeaderboard(tables, "table");
  assert.match(out, /tops-fmri@agent@1  \[scored=1, private_data_missing=1\]/);
  assert.match(out, /score\s+0\.4491\s+1\/2/);
  assert.match(out, /study4_score\s+—\s+0\/2/);
});

test("renderLeaderboard supports stable JSON, Markdown, and CSV", () => {
  assert.deepEqual(JSON.parse(renderLeaderboard(tables, "json")), tables);
  assert.match(renderLeaderboard(tables, "markdown"), /\| tops-fmri@agent@1 \|/);
  const csv = renderLeaderboard(tables, "csv");
  assert.match(csv, /^category,task_id,agent,states,metric,value,scored,total/);
  assert.match(csv, /fmri-analysis,tops-fmri,agent@1,"scored=1, private_data_missing=1",score,0\.449085,1,2/);
});
