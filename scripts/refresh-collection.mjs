#!/usr/bin/env node
/** Regenerate public catalog metadata. This command never runs task code. */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { discoverTaskDirs } from "../dist/discover.js";
import { loadTask } from "../dist/loader.js";
import { validateTaskSchema } from "../dist/validate.js";
import { loadCategories } from "../dist/categories.js";
import { readInvasiveCandidates, invasiveCatalogRow } from "./invasive-candidates.mjs";
import { readInvasiveAcceptance } from "./invasive-acceptance.mjs";
import { validatePrivateEvaluatorIncrement, privateScoreEntry } from "./private-evaluator-increment.mjs";

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
const privateIncrement = validatePrivateEvaluatorIncrement(root);
for (const dir of discoverTaskDirs([join(root, "tasks")])) {
  const task = loadTask(dir);
  const errors = validateTaskSchema(task, categories).filter(issue => issue.level === "error");
  if (errors.length) throw new Error(`${rel(dir)}: ${JSON.stringify(errors)}`);
  const contract = existsSync(join(dir, "contract.json")) ? read(join(dir, "contract.json")) : {};
  const id = task.meta.id;
  const invasive = ["ieeg", "intracortical"].includes(rel(dir).split("/")[1]);
  const accepted = invasive ? readInvasiveAcceptance(root, dir, task) : null;
  if (invasive && !accepted) throw new Error(`${rel(dir)}: runnable invasive entry lacks current acceptance evidence`);
  const publicOnly = id.startsWith("psych101-") || id.startsWith("eeg-") || invasive;
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
  const dataCategory = invasive ? "invasive" : row.domain;
  const canonicalPrefix = `tasks/${dataCategory}/${id}/public/`;
  const hostedPublic = publicDatasets.length > 0 && publicDatasets.every(d => {
    const match = /^hf:\/\/datasets\/BrainPilot-Bench\/Tasks-Data-Public@([0-9a-f]{40})\/(.+)$/.exec(d.uri);
    return match && match[2].startsWith(canonicalPrefix);
  });
  // Scientific readiness is recorded separately from where public bytes live.
  // Invasive acceptance below retains its existing scientific data_status.
  if (hostedPublic) {
    row.hosted_data_availability = "published_public_snapshot";
    if (!invasive) row.data_status = "published_public_package";
  } else if (id === "falcon-h1-reach-grasp") {
    row.hosted_data_availability = "source_only";
  }
  row.data_access = hostedPublic ? "pinned_public_snapshot"
    : publicDatasets.some(d => d.uri.startsWith("local://"))
      ? "maintainer_package_required" : "pinned_source_download";
  const privateDatasets = task.datasets.filter(d => d.scope === "private");
  if (privateDatasets.length) row.private_data_access = privateDatasets.some(d => d.uri.startsWith("local://"))
    ? "maintainer_package_required" : "pinned_source_download";
  if (privateIncrement.byId.has(id)) {
    if (!privateDatasets.length || !existsSync(join(dir, "evaluator.lock")))
      throw new Error(`${rel(dir)}: increment-backed private evaluator package is missing`);
    row.private_data_access = "pinned_private_snapshot";
    row.private_score_entry = privateScoreEntry;
  } else if (existsSync(join(dir, "evaluator.lock"))) {
    throw new Error(`${rel(dir)}: evaluator.lock is outside the frozen private increment`);
  }
  if (accepted) {
    row.validation = "local_fixed_reference_and_isolation_passed";
    row.validation_record = `${rel(dir)}/acceptance.json`;
    row.source_task_id = accepted.source_task_id;
    row.data_status = accepted.data_status ?? "source_bound_reproducible_export";
    row.source_verification = accepted.source_verification;
    row.owner_test = "fixed_reference_interface_passed_not_agent_benchmark";
    row.agent_benchmark_results = "not_available";
    if (accepted.data_status === "owner_key_bound_prepared_export")
      row.exact_export_requires_owner_key = true;
  }
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
for (const entry of readInvasiveCandidates(root)) tasks.push(invasiveCatalogRow(entry));
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
  schema: "brainpilotbench-task-collection/1", date: "2026-10-15",
  release_status: "integration_candidate_not_released",
  validation_policy: "Four first-batch reference checks; version-bound local invasive task acceptance with fixed references and isolated owner Test interface checks; no formal Agent results or historical private Test replay",
  counts: {
    total: tasks.length, runnable: tasks.filter(t => t.entry_kind === "runnable").length,
    candidate: tasks.filter(t => t.entry_kind === "candidate").length,
    preparation_ready: tasks.filter(t => t.preparation_available).length,
    representative_runs: referenceChecks.size + tasks.filter(t => t.validation === "local_fixed_reference_and_isolation_passed").length,
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
