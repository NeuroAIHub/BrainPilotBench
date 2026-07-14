/** Public/private dataset selection shared by the CLI and programmatic API. */
import type { DatasetEntry, DatasetSelection } from "./types.js";

const FLAGS: Array<[string, DatasetSelection]> = [
  ["--public", "public"],
  ["--private", "private"],
  ["--all", "all"],
];

/** Parse fetch flags. The safe default is public-only. */
export function parseDatasetSelection(args: string[]): DatasetSelection {
  const selected = FLAGS.filter(([flag]) => args.includes(flag));
  if (selected.length > 1) {
    throw new Error("data scope flags are mutually exclusive: use one of --public, --private, or --all");
  }
  return selected[0]?.[1] ?? "public";
}

/** Select entries without mutating the manifest; legacy entries are public. */
export function selectDatasets(entries: DatasetEntry[], selection: DatasetSelection): DatasetEntry[] {
  if (selection === "all") return [...entries];
  return entries.filter((entry) => (entry.scope ?? "public") === selection);
}
