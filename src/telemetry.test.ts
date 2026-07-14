import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import {
  collectTelemetryStats,
  loadRunTelemetry,
  renderTelemetryStats,
  telemetryBundles,
  validateRunTelemetry,
  writeRunTelemetry,
  type RunTelemetryInput,
} from "./telemetry.js";

const full: RunTelemetryInput = {
  harness: "brainpilot",
  model: "test-model",
  condition: "full",
  domainToolNames: ["get_domain_knowledge_local", "search_papers_local"],
  tokens: { input: 100, output: 20, cacheRead: 5, cacheWrite: 3 },
  domainToolCalls: 4,
  skillSearches: 2,
  skillLoads: 1,
};
const CLI = join(process.cwd(), "dist", "cli.js");

function makeBundle(parent?: string, name = "run"): string {
  const root = parent ?? mkdtempSync(join(tmpdir(), "bpb-telemetry-"));
  const dir = parent ? join(root, name) : root;
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "meta.json"), JSON.stringify({ taskId: "task", agent: `${name}@1` }));
  writeFileSync(join(dir, "events.jsonl"), '{"type":"raw","secret":"not copied into telemetry"}\n');
  return dir;
}

test("telemetry round trip derives token total and binds raw events", () => {
  const dir = makeBundle();
  try {
    const written = writeRunTelemetry(dir, full);
    assert.equal(written.tokens.total, 128);
    assert.match(written.sourceEvents.sha256, /^[a-f0-9]{64}$/);

    const loaded = loadRunTelemetry(dir);
    assert.equal(loaded.status, "ok");
    assert.deepEqual(loaded.telemetry, written);
    assert.doesNotMatch(readFileSync(join(dir, "telemetry.json"), "utf8"), /secret/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("missing measurements remain null and are never coerced to zero", () => {
  const dir = makeBundle();
  try {
    const telemetry = writeRunTelemetry(dir, {
      ...full,
      tokens: { input: 100, output: 20, cacheRead: null, cacheWrite: null },
      domainToolCalls: null,
      skillSearches: null,
      skillLoads: null,
    });
    assert.equal(telemetry.tokens.total, null);
    assert.equal(telemetry.domainToolCalls, null);
    const row = collectTelemetryStats(dir)[0];
    assert.equal(row.status, "missing");
    assert.equal(row.tokens, null);
    assert.match(renderTelemetryStats([row], "table"), /—/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("telemetry fails closed on event tampering and base resource leakage", () => {
  const dir = makeBundle();
  try {
    writeRunTelemetry(dir, full);
    writeFileSync(join(dir, "events.jsonl"), '{"type":"tampered"}\n');
    const tampered = loadRunTelemetry(dir);
    assert.equal(tampered.status, "invalid");
    assert.ok(tampered.errors.some((error) => /SHA-256/.test(error)));

    const baseMissing = { ...full, condition: "base", domainToolCalls: 0, skillSearches: null, skillLoads: 0 };
    assert.ok(validateRunTelemetry({
      ...baseMissing,
      schemaVersion: "1.0",
      tokens: { ...full.tokens, total: 128 },
      sourceEvents: { path: "events.jsonl", sha256: "0".repeat(64) },
    }).some((error) => /skillSearches=0/.test(error)));

    assert.throws(() => writeRunTelemetry(dir, {
      ...full,
      condition: "base",
      domainToolCalls: 1,
      skillSearches: 0,
      skillLoads: 0,
    }), /base condition requires measured domainToolCalls=0/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("stats discovers bundle children and renders table, JSON, Markdown, and CSV", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-telemetry-runs-"));
  try {
    const measured = makeBundle(root, "measured");
    makeBundle(root, "missing");
    writeRunTelemetry(measured, full);

    assert.deepEqual(telemetryBundles(root).map((dir) => dir.split("/").at(-1)), ["measured", "missing"]);
    const rows = collectTelemetryStats(root);
    assert.deepEqual(rows.map((row) => row.status), ["ok", "missing"]);
    assert.match(renderTelemetryStats(rows, "table"), /Domain Tool Calls/);
    assert.equal(JSON.parse(renderTelemetryStats(rows, "json"))[0].tokens, 128);
    assert.match(renderTelemetryStats(rows, "markdown"), /\| Tokens \| Domain Tool Calls \|/);
    assert.match(renderTelemetryStats(rows, "csv"), /^bundle,task_id,agent,harness,/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("stats CLI succeeds only when every discovered bundle has valid telemetry", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-telemetry-cli-"));
  try {
    const measured = makeBundle(root, "measured");
    makeBundle(root, "missing");
    writeRunTelemetry(measured, full);

    const direct = spawnSync(process.execPath, [CLI, "stats", measured, "--format", "json"], { encoding: "utf8" });
    assert.equal(direct.status, 0, direct.stderr);
    assert.equal(JSON.parse(direct.stdout)[0].status, "ok");

    const mixed = spawnSync(process.execPath, [CLI, "stats", root, "--format", "csv"], { encoding: "utf8" });
    assert.equal(mixed.status, 1, mixed.stderr);
    assert.match(mixed.stdout, /missing,task,missing@1/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
