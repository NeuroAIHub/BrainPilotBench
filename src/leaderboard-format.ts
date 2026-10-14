import type { CategoryTable } from "./leaderboard.js";

export type LeaderboardFormat = "table" | "json" | "markdown" | "csv";

function value(value: number | null): string {
  return value == null ? "—" : value.toFixed(4);
}

function rowLabel(row: CategoryTable["rows"][number]): string {
  return `${row.taskId}${row.taskVersion ? ` [task ${row.taskVersion}]` : ""}${row.evaluationProfile ? ` [${row.evaluationProfile}]` : ""}@${row.version}`;
}

function stateSummary(states: CategoryTable["rows"][number]["states"]): string {
  return Object.entries(states).map(([state, count]) => `${state}=${count}`).join(", ");
}

function table(tables: CategoryTable[]): string {
  const lines: string[] = [];
  for (const category of tables) {
    if (lines.length) lines.push("");
    lines.push(`# ${category.category}`);
    for (const row of category.rows) {
      lines.push(`${rowLabel(row)}  [${stateSummary(row.states)}]`);
      lines.push("  metric                           value       coverage");
      for (const cell of row.cells) {
        lines.push(`  ${cell.metric.slice(0, 32).padEnd(32)} ${value(cell.value).padStart(10)}   ${cell.coverage.scored}/${cell.coverage.total}`);
      }
    }
  }
  return lines.join("\n");
}

function markdown(tables: CategoryTable[]): string {
  const lines: string[] = [];
  for (const category of tables) {
    if (lines.length) lines.push("");
    lines.push(`## ${category.category}`, "", "| Task / agent | State | Metric | Score | Coverage |", "|---|---|---|---:|---:|");
    for (const row of category.rows) {
      for (const cell of row.cells) {
        const label = rowLabel(row).replaceAll("|", "\\|");
        lines.push(`| ${label} | ${stateSummary(row.states)} | ${cell.metric} | ${value(cell.value)} | ${cell.coverage.scored}/${cell.coverage.total} |`);
      }
    }
  }
  return lines.join("\n");
}

function csvEscape(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

function csv(tables: CategoryTable[]): string {
  const hasVersion = tables.some(t => t.rows.some(r => r.taskVersion !== undefined));
  const hasProfile = tables.some(t => t.rows.some(r => r.evaluationProfile !== undefined));
  const rows = [["category", "task_id", "agent", "states", "metric", "value", "scored", "total"]];
  if (hasVersion) rows[0].push("task_version");
  if (hasProfile) rows[0].push("evaluation_profile");
  for (const category of tables) for (const row of category.rows) for (const cell of row.cells) {
    rows.push([
      category.category, row.taskId, row.version, stateSummary(row.states), cell.metric,
      cell.value == null ? "" : String(cell.value), String(cell.coverage.scored), String(cell.coverage.total),
    ]);
    if (hasVersion) rows[rows.length - 1].push(row.taskVersion ?? "");
    if (hasProfile) rows[rows.length - 1].push(row.evaluationProfile ?? "");
  }
  return rows.map((row) => row.map(csvEscape).join(",")).join("\n");
}

export function renderLeaderboard(tables: CategoryTable[], format: LeaderboardFormat): string {
  if (format === "json") return JSON.stringify(tables, null, 2);
  if (format === "markdown") return markdown(tables);
  if (format === "csv") return csv(tables);
  return table(tables);
}
