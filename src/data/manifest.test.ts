import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDataManifest } from "./manifest.js";

test("parseDataManifest: 解析合法 data.lock", () => {
  const m = parseDataManifest({
    datasets: [
      { name: "ds-a", uri: "https://example.org/a.parquet", sha256: "a".repeat(64), bytes: 123, format: "parquet" },
    ],
  });
  assert.equal(m.datasets.length, 1);
  assert.equal(m.datasets[0].name, "ds-a");
  assert.equal(m.datasets[0].uri, "https://example.org/a.parquet");
  assert.equal(m.datasets[0].sha256, "a".repeat(64));
  assert.equal(m.datasets[0].bytes, 123);
  assert.equal(m.datasets[0].format, "parquet");
  assert.equal(m.datasets[0].scope, "public");
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

test("parseDataManifest: scope 仅允许 public/private，旧清单缺省 public", () => {
  const make = (scope?: string) => ({
    datasets: [{ name: "x", uri: "u", sha256: "a".repeat(64), bytes: 1, ...(scope ? { scope } : {}) }],
  });
  assert.equal(parseDataManifest(make()).datasets[0].scope, "public");
  assert.equal(parseDataManifest(make("private")).datasets[0].scope, "private");
  assert.throws(() => parseDataManifest(make("secret")), /scope must be 'public' or 'private'/);
});

test("parseDataManifest: null 列表项报清晰错误", () => {
  assert.throws(() => parseDataManifest({ datasets: [null] }), /datasets\[0\] must be a mapping/);
});

test("parseDataManifest: name 拒绝路径穿越(../ 、/ 、..)", () => {
  const bad = (name: string) =>
    parseDataManifest({ datasets: [{ name, uri: "u", sha256: "a".repeat(64), bytes: 1 }] });
  assert.throws(() => bad("../../etc/x"), /name must match \[A-Za-z0-9._-\]/);
  assert.throws(() => bad("sub/dir"), /name must match \[A-Za-z0-9._-\]/);
  assert.throws(() => bad(".."), /name must match \[A-Za-z0-9._-\]/);
  assert.equal(
    parseDataManifest({ datasets: [{ name: "ds_a-1.parquet", uri: "u", sha256: "a".repeat(64), bytes: 1 }] }).datasets[0].name,
    "ds_a-1.parquet");
});
