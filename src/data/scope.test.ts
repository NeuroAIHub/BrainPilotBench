import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDatasetSelection, selectDatasets } from "./scope.js";
import type { DatasetEntry } from "./types.js";

const base = { uri: "file:///tmp/data", sha256: "a".repeat(64), bytes: 1 };
const entries: DatasetEntry[] = [
  { ...base, name: "legacy" },
  { ...base, name: "train", scope: "public" },
  { ...base, name: "labels", scope: "private" },
];

test("parseDatasetSelection: fetch defaults to public-only", () => {
  assert.equal(parseDatasetSelection(["fetch", "task"]), "public");
  assert.equal(parseDatasetSelection(["fetch", "task", "--private"]), "private");
  assert.equal(parseDatasetSelection(["fetch", "all", "--all"]), "all");
});

test("parseDatasetSelection: scope flags are mutually exclusive", () => {
  assert.throws(() => parseDatasetSelection(["--public", "--private"]), /mutually exclusive/);
});

test("selectDatasets: legacy entries are public and private is opt-in", () => {
  assert.deepEqual(selectDatasets(entries, "public").map((entry) => entry.name), ["legacy", "train"]);
  assert.deepEqual(selectDatasets(entries, "private").map((entry) => entry.name), ["labels"]);
  assert.equal(selectDatasets(entries, "all").length, 3);
});
