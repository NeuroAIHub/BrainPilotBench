#!/usr/bin/env node
/** Regenerate public catalog metadata. This command never runs task code. */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { discoverTaskDirs } from "../dist/discover.js";
import { loadTask } from "../dist/loader.js";
import { validateTaskSchema } from "../dist/validate.js";
import { loadCategories } from "../dist/categories.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = path => JSON.parse(readFileSync(path, "utf8"));
const rel = path => relative(root, path).split(sep).join("/");
const original = new Set(["bciciv-2a", "sleep-edf", "tops-fmri", "neuro-rsc-place-cell"]);
// These are recorded first-stage checks, not tests launched by this generator.
const referenceChecks = new Set([
  "eeg-mi-bnci2014", "psych101-lefebvre2017behavioural-exp1",
  "celegans-structure-function-divergence", "brain-age-mri",
]);
const tasks = [];
const categories = loadCategories(root);
for (const dir of discoverTaskDirs([join(root, "tasks")])) {
  const task = loadTask(dir);
  const errors = validateTaskSchema(task, categories).filter(issue => issue.level === "error");
  if (errors.length) throw new Error(`${rel(dir)}: ${JSON.stringify(errors)}`);
  const contract = existsSync(join(dir, "contract.json")) ? read(join(dir, "contract.json")) : {};
  const id = task.meta.id;
  const publicOnly = id.startsWith("psych101-") || id.startsWith("eeg-");
  const row = {
    task_id: id, domain: rel(dir).split("/")[1], directory: rel(dir),
    entry_kind: "runnable", task_version: task.meta.version,
    validation: referenceChecks.has(id) ? "representative_run_passed"
      : original.has(id) ? "legacy_retained_structure_checked" : "structure_checked_not_data_run",
    evaluation_scope: publicOnly ? "public_validation_only" : "task_defined",
    primary_metric: task.meta.evaluation?.primaryMetric ?? null,
  };
  if (task.meta.evaluation?.profile) row.evaluation_profile = task.meta.evaluation.profile;
  if (contract.experiment_id) row.source_task_id = contract.experiment_id;
  else if (contract.source_task_id) row.source_task_id = contract.source_task_id;
  else if (contract.task_id && contract.task_id !== id) row.source_task_id = contract.task_id;
  if (referenceChecks.has(id)) row.validation_record = "docs/integration-validation.md";
  if (publicOnly) row.data_status = referenceChecks.has(id)
    ? "representative_public_package_prepared" : (contract.availability_status ?? "manifest_bound_package_required");
  const publicDatasets = task.datasets.filter(d => d.scope === "public");
  if (publicDatasets.length && publicDatasets.every(d =>
    /^hf:\/\/datasets\/BrainPilot-Bench\/Tasks-Data-Public@[0-9a-f]{40}\/bpb-public-data-[^/]+\//.test(d.uri)))
    row.data_status = "published_public_package";
  row.data_access = publicDatasets.some(d => d.uri.startsWith("local://"))
    ? "maintainer_package_required" : "pinned_source_download";
  const privateDatasets = task.datasets.filter(d => d.scope === "private");
  if (privateDatasets.length) row.private_data_access = privateDatasets.some(d => d.uri.startsWith("local://"))
    ? "maintainer_package_required" : "pinned_source_download";
  tasks.push(row);
}
for (const entry of readdirSync(join(root, "tasks/eeg"), { withFileTypes: true })) {
  const dir = join(root, "tasks/eeg", entry.name);
  const cardPath = join(dir, "candidate.json");
  if (!entry.isDirectory() || !existsSync(cardPath)) continue;
  if (existsSync(join(dir, "task.yaml"))) throw new Error(`Remove obsolete candidate card before promotion: ${rel(dir)}`);
  const card = read(cardPath);
  const preparation = existsSync(join(dir, "preparation.json"));
  tasks.push({
    task_id: card.id, domain: "eeg", directory: rel(dir), entry_kind: "candidate",
    validation: preparation ? "preparation_recipe_checked_data_pending" : "metadata_structure_checked",
    preparation_available: preparation, source_task_id: card.source_task_id,
    primary_metric: card.primary_metric,
    reason: preparation ? "Preparation recipe and checks exist; frozen full task arrays are not materialized"
      : card.id === "eeg-cvep-thielen2021" ? "Withheld from activation under the existing research scope choice"
      : "Frozen task/data binding not imported",
  });
}
const metadata = read(join(root, "tasks/psychology/metadata-only.json"));
for (const card of metadata.tasks) tasks.push({
  task_id: card.proposed_task_id, domain: "psychology", metadata_file: "tasks/psychology/metadata-only.json",
  entry_kind: "candidate", validation: "metadata_structure_checked",
  source_task_id: card.original_experiment_id, reason: "Response/scoring contract remains pending",
});
const ids = new Set(tasks.map(t => t.task_id));
if (ids.size !== tasks.length) throw new Error("Duplicate catalog task IDs");
tasks.sort((a,b) => a.task_id.localeCompare(b.task_id));
const catalog = {
  schema: "brainpilotbench-task-collection/1", date: "2026-10-12",
  release_status: "integration_candidate_not_released",
  validation_policy: "Four recorded real reference checks; new interfaces use structure/contract checks; no paid Agent or historical private Test replay",
  counts: {
    total: tasks.length, runnable: tasks.filter(t => t.entry_kind === "runnable").length,
    candidate: tasks.filter(t => t.entry_kind === "candidate").length,
    preparation_ready: tasks.filter(t => t.preparation_available).length,
    representative_runs: referenceChecks.size,
  }, tasks,
};
const text = JSON.stringify(catalog, null, 2) + "\n";
if (process.argv.includes("--check")) {
  if (readFileSync(join(root, "tasks/catalog.json"), "utf8") !== text)
    throw new Error("Collection catalog is stale. Run npm run catalog:refresh.");
} else {
  writeFileSync(join(root, "tasks/catalog.json"), text);
}
console.log(JSON.stringify(catalog.counts));
