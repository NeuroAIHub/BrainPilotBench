/** Harness-neutral, auditable per-run telemetry. */
import { createHash } from "node:crypto";
import {
  existsSync, readFileSync, readdirSync, statSync, writeFileSync,
} from "node:fs";
import { basename, join, resolve } from "node:path";

export const TELEMETRY_SCHEMA_VERSION = "1.0" as const;
export type TelemetryCondition = "full" | "base";
export type TelemetryStatus = "ok" | "missing" | "invalid";
export type TelemetryFormat = "table" | "json" | "markdown" | "csv";

export interface TokenTelemetry {
  input: number | null;
  output: number | null;
  cacheRead: number | null;
  cacheWrite: number | null;
  total: number | null;
}

export interface RunTelemetry {
  schemaVersion: typeof TELEMETRY_SCHEMA_VERSION;
  harness: string;
  model: string;
  condition: TelemetryCondition;
  domainToolNames: string[];
  tokens: TokenTelemetry;
  domainToolCalls: number | null;
  skillSearches: number | null;
  skillLoads: number | null;
  sourceEvents: {
    path: "events.jsonl";
    sha256: string;
  };
}

export interface RunTelemetryInput {
  harness: string;
  model: string;
  condition: TelemetryCondition;
  domainToolNames: string[];
  tokens: Omit<TokenTelemetry, "total">;
  domainToolCalls: number | null;
  skillSearches: number | null;
  skillLoads: number | null;
}

export interface TelemetryLoadResult {
  status: TelemetryStatus;
  telemetry: RunTelemetry | null;
  errors: string[];
}

export interface TelemetryStatsRow {
  bundle: string;
  taskId: string | null;
  agent: string | null;
  harness: string | null;
  model: string | null;
  condition: TelemetryCondition | null;
  tokens: number | null;
  domainToolCalls: number | null;
  skillSearches: number | null;
  skillLoads: number | null;
  status: TelemetryStatus;
  errors: string[];
}

const countFields = ["domainToolCalls", "skillSearches", "skillLoads"] as const;
const tokenFields = ["input", "output", "cacheRead", "cacheWrite", "total"] as const;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function validNullableCount(value: unknown): boolean {
  return value === null || (Number.isSafeInteger(value) && (value as number) >= 0);
}

function sha256(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

/** Build telemetry and bind it to the exact raw event stream in the bundle. */
export function createRunTelemetry(bundleDir: string, input: RunTelemetryInput): RunTelemetry {
  const eventsPath = join(bundleDir, "events.jsonl");
  if (!existsSync(eventsPath)) throw new Error(`events.jsonl is required before telemetry can be created: ${eventsPath}`);
  const components = [input.tokens.input, input.tokens.output, input.tokens.cacheRead, input.tokens.cacheWrite];
  const total = components.every((value): value is number => typeof value === "number")
    ? components.reduce((sum, value) => sum + value, 0)
    : null;
  return {
    schemaVersion: TELEMETRY_SCHEMA_VERSION,
    harness: input.harness,
    model: input.model,
    condition: input.condition,
    domainToolNames: [...input.domainToolNames],
    tokens: { ...input.tokens, total },
    domainToolCalls: input.domainToolCalls,
    skillSearches: input.skillSearches,
    skillLoads: input.skillLoads,
    sourceEvents: { path: "events.jsonl", sha256: sha256(eventsPath) },
  };
}

/** Create, validate, and persist <bundle>/telemetry.json. */
export function writeRunTelemetry(bundleDir: string, input: RunTelemetryInput): RunTelemetry {
  const telemetry = createRunTelemetry(bundleDir, input);
  const errors = validateRunTelemetry(telemetry, bundleDir);
  if (errors.length) throw new Error(`invalid telemetry: ${errors.join("; ")}`);
  writeFileSync(join(bundleDir, "telemetry.json"), JSON.stringify(telemetry, null, 2) + "\n");
  return telemetry;
}

/** Strict validation: absent measurements must be explicit null, never implicit zero. */
export function validateRunTelemetry(value: unknown, bundleDir?: string): string[] {
  const errors: string[] = [];
  if (!isObject(value)) return ["telemetry.json must contain a JSON object"];
  if (value.schemaVersion !== TELEMETRY_SCHEMA_VERSION) errors.push(`schemaVersion must be ${TELEMETRY_SCHEMA_VERSION}`);
  for (const field of ["harness", "model"] as const) {
    if (typeof value[field] !== "string" || !(value[field] as string).trim()) errors.push(`${field} must be a non-empty string`);
  }
  if (!(value.condition === "full" || value.condition === "base")) errors.push("condition must be full or base");

  if (!Array.isArray(value.domainToolNames) || value.domainToolNames.some((name) => typeof name !== "string" || !name.trim())) {
    errors.push("domainToolNames must be an array of non-empty strings");
  } else if (new Set(value.domainToolNames).size !== value.domainToolNames.length) {
    errors.push("domainToolNames must not contain duplicates");
  }

  if (!isObject(value.tokens)) {
    errors.push("tokens must be an object with explicit nullable components");
  } else {
    for (const field of tokenFields) {
      if (!hasOwn(value.tokens, field)) errors.push(`tokens.${field} is required (use null when unavailable)`);
      else if (!validNullableCount(value.tokens[field])) errors.push(`tokens.${field} must be a non-negative safe integer or null`);
    }
    const components = [value.tokens.input, value.tokens.output, value.tokens.cacheRead, value.tokens.cacheWrite];
    const allMeasured = components.every((component) => typeof component === "number");
    if (allMeasured) {
      const expected = (components as number[]).reduce((sum, component) => sum + component, 0);
      if (value.tokens.total !== expected) errors.push(`tokens.total must equal input + output + cacheRead + cacheWrite (${expected})`);
    } else if (value.tokens.total !== null) {
      errors.push("tokens.total must be null when any token component is unavailable");
    }
  }

  for (const field of countFields) {
    if (!hasOwn(value, field)) errors.push(`${field} is required (use null when unavailable)`);
    else if (!validNullableCount(value[field])) errors.push(`${field} must be a non-negative safe integer or null`);
  }
  if (value.condition === "base") {
    for (const field of countFields) {
      if (value[field] !== 0) errors.push(`base condition requires measured ${field}=0`);
    }
  }

  if (!isObject(value.sourceEvents)) {
    errors.push("sourceEvents must bind telemetry to events.jsonl");
  } else {
    if (value.sourceEvents.path !== "events.jsonl") errors.push("sourceEvents.path must be events.jsonl");
    if (typeof value.sourceEvents.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(value.sourceEvents.sha256)) {
      errors.push("sourceEvents.sha256 must be a lowercase SHA-256 digest");
    } else if (bundleDir) {
      const eventsPath = join(bundleDir, "events.jsonl");
      if (!existsSync(eventsPath)) errors.push("source events.jsonl is missing");
      else if (sha256(eventsPath) !== value.sourceEvents.sha256) errors.push("events.jsonl SHA-256 does not match telemetry.json");
    }
  }
  return errors;
}

export function loadRunTelemetry(bundleDir: string): TelemetryLoadResult {
  const path = join(bundleDir, "telemetry.json");
  if (!existsSync(path)) return { status: "missing", telemetry: null, errors: ["telemetry.json is missing"] };
  let value: unknown;
  try { value = JSON.parse(readFileSync(path, "utf8")); }
  catch (error) { return { status: "invalid", telemetry: null, errors: [`telemetry.json cannot be parsed: ${(error as Error).message}`] }; }
  const errors = validateRunTelemetry(value, bundleDir);
  if (errors.length) return { status: "invalid", telemetry: null, errors };
  const telemetry = value as RunTelemetry;
  const unavailable = [
    telemetry.tokens.total === null ? "tokens.total" : null,
    ...countFields.map((field) => telemetry[field] === null ? field : null),
  ].filter((field): field is string => field !== null);
  return unavailable.length
    ? { status: "missing", telemetry, errors: unavailable.map((field) => `${field} is unavailable`) }
    : { status: "ok", telemetry, errors: [] };
}

function readIdentity(bundleDir: string): { taskId: string | null; agent: string | null; error?: string } {
  try {
    const meta = JSON.parse(readFileSync(join(bundleDir, "meta.json"), "utf8")) as Record<string, unknown>;
    return {
      taskId: typeof meta.taskId === "string" ? meta.taskId : null,
      agent: typeof meta.agent === "string" ? meta.agent : null,
    };
  } catch (error) {
    return { taskId: null, agent: null, error: `meta.json cannot be parsed: ${(error as Error).message}` };
  }
}

export function telemetryBundles(inputPath: string): string[] {
  const root = resolve(inputPath);
  if (existsSync(join(root, "meta.json"))) return [root];
  if (!existsSync(root) || !statSync(root).isDirectory()) return [];
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(join(root, entry.name, "meta.json")))
    .map((entry) => join(root, entry.name))
    .sort();
}

export function collectTelemetryStats(inputPath: string): TelemetryStatsRow[] {
  return telemetryBundles(inputPath).map((bundleDir) => {
    const identity = readIdentity(bundleDir);
    const loaded = loadRunTelemetry(bundleDir);
    const telemetry = loaded.telemetry;
    const identityErrors = identity.error ? [identity.error] : [];
    return {
      bundle: basename(bundleDir),
      taskId: identity.taskId,
      agent: identity.agent,
      harness: telemetry?.harness ?? null,
      model: telemetry?.model ?? null,
      condition: telemetry?.condition ?? null,
      tokens: telemetry?.tokens.total ?? null,
      domainToolCalls: telemetry?.domainToolCalls ?? null,
      skillSearches: telemetry?.skillSearches ?? null,
      skillLoads: telemetry?.skillLoads ?? null,
      status: identityErrors.length ? "invalid" : loaded.status,
      errors: [...identityErrors, ...loaded.errors],
    };
  });
}

const display = (value: string | number | null): string => value === null ? "—" : String(value);
const identityLabel = (row: TelemetryStatsRow): string => row.taskId && row.agent ? `${row.taskId}@${row.agent}` : row.bundle;
const markdownValue = (value: string | number | null): string => display(value).replaceAll("|", "\\|").replaceAll("\n", " ");
const csvValue = (value: string | number | null): string => value === null ? "" : String(value);

function renderTable(rows: TelemetryStatsRow[]): string {
  const lines = ["Run", "  harness/model  condition  Tokens  Domain Tool Calls  Skill Searches  Skill Loads  status"];
  for (const row of rows) {
    lines.push(identityLabel(row));
    lines.push(`  ${display(row.harness)}/${display(row.model)}  ${display(row.condition)}  ${display(row.tokens)}  ${display(row.domainToolCalls)}  ${display(row.skillSearches)}  ${display(row.skillLoads)}  ${row.status}`);
    for (const error of row.errors) lines.push(`    ! ${error}`);
  }
  return lines.join("\n");
}

function renderMarkdown(rows: TelemetryStatsRow[]): string {
  const lines = [
    "| Run | Harness | Model | Condition | Tokens | Domain Tool Calls | Skill Searches | Skill Loads | Status |",
    "|---|---|---|---|---:|---:|---:|---:|---|",
  ];
  for (const row of rows) lines.push(`| ${markdownValue(identityLabel(row))} | ${markdownValue(row.harness)} | ${markdownValue(row.model)} | ${markdownValue(row.condition)} | ${markdownValue(row.tokens)} | ${markdownValue(row.domainToolCalls)} | ${markdownValue(row.skillSearches)} | ${markdownValue(row.skillLoads)} | ${row.status} |`);
  return lines.join("\n");
}

function csvEscape(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

function renderCsv(rows: TelemetryStatsRow[]): string {
  const data = [["bundle", "task_id", "agent", "harness", "model", "condition", "tokens", "domain_tool_calls", "skill_searches", "skill_loads", "status", "errors"]];
  for (const row of rows) data.push([
    row.bundle, csvValue(row.taskId), csvValue(row.agent), csvValue(row.harness), csvValue(row.model), csvValue(row.condition),
    row.tokens === null ? "" : String(row.tokens), row.domainToolCalls === null ? "" : String(row.domainToolCalls),
    row.skillSearches === null ? "" : String(row.skillSearches), row.skillLoads === null ? "" : String(row.skillLoads),
    row.status, row.errors.join("; "),
  ]);
  return data.map((row) => row.map(csvEscape).join(",")).join("\n");
}

export function renderTelemetryStats(rows: TelemetryStatsRow[], format: TelemetryFormat): string {
  if (format === "json") return JSON.stringify(rows, null, 2);
  if (format === "markdown") return renderMarkdown(rows);
  if (format === "csv") return renderCsv(rows);
  return renderTable(rows);
}
