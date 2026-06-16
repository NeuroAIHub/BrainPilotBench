import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDataManifest } from "./manifest.js";

test("parseDataManifest: 解析合法 data.lock", () => {
  const m = parseDataManifest({
    datasets: [
      { name: "ds-a", uri: "oss://bucket/a.parquet", sha256: "a".repeat(64), bytes: 123, format: "parquet" },
    ],
  });
  assert.equal(m.datasets.length, 1);
  assert.equal(m.datasets[0].name, "ds-a");
  assert.equal(m.datasets[0].uri, "oss://bucket/a.parquet");
  assert.equal(m.datasets[0].sha256, "a".repeat(64));
  assert.equal(m.datasets[0].bytes, 123);
  assert.equal(m.datasets[0].format, "parquet");
});

test("parseDataManifest: 空/缺 datasets → 空清单", () => {
  assert.deepEqual(parseDataManifest(undefined).datasets, []);
  assert.deepEqual(parseDataManifest({}).datasets, []);
  assert.deepEqual(parseDataManifest({ datasets: [] }).datasets, []);
});

test("parseDataManifest: 缺字段报清晰错误", () => {
  assert.throws(() => parseDataManifest({ datasets: [{ uri: "x", sha256: "a".repeat(64), bytes: 1 }] }),
    /datasets\[0\]: missing 'name'/);
  assert.throws(() => parseDataManifest({ datasets: [{ name: "x", sha256: "a".repeat(64), bytes: 1 }] }),
    /datasets\[0\]: missing 'uri'/);
});

test("parseDataManifest: sha256 必须是 64 位十六进制", () => {
  assert.throws(() => parseDataManifest({ datasets: [{ name: "x", uri: "u", sha256: "zzz", bytes: 1 }] }),
    /datasets\[0\]: sha256 must be 64 hex chars/);
});

test("parseDataManifest: bytes 必须是非负整数", () => {
  assert.throws(() => parseDataManifest({ datasets: [{ name: "x", uri: "u", sha256: "a".repeat(64), bytes: -1 }] }),
    /datasets\[0\]: bytes must be a non-negative integer/);
});

test("parseDataManifest: null 列表项报清晰错误", () => {
  assert.throws(() => parseDataManifest({ datasets: [null] }), /datasets\[0\] must be a mapping/);
});
