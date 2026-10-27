#!/usr/bin/env node
/**
 * Read-only task collection inventory check. Run after `npm run build`.
 * Imports built discovery/loading/schema modules; never calls task setup,
 * solution, scorer, fetch, Docker, network, or Agent execution code.
 */
import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { discoverTaskDirs } from "../dist/discover.js";
import { loadTask } from "../dist/loader.js";
import { loadCategories } from "../dist/categories.js";
import { readEvaluatorLock } from "../dist/evaluator.js";
import { readMouseAcceptance } from "./mouse-acceptance.mjs";
import { validateTaskSchema } from "../dist/validate.js";
import { readInvasiveCandidates, invasiveDomains, invasiveCatalogRow } from "./invasive-candidates.mjs";
import { readMouseCandidates, mouseDomains, mouseCatalogRow } from "./mouse-candidates.mjs";
import { readInvasiveAcceptance } from "./invasive-acceptance.mjs";
import { validatePrivateEvaluatorIncrement, privateScoreEntry } from "./private-evaluator-increment.mjs";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tasksRoot = join(repo, "tasks");
const errors = [];
const baseline = Object.freeze({ runnable: 19, total: 110, eeg: 30, psychology: 76 });
const legacyVersions = new Map([
  ["bciciv-2a", "0.2"],
  ["sleep-edf", "0.2"],
  ["tops-fmri", "0.1"],
  ["neuro-rsc-place-cell", "0.2"],
]);
const baselineNewRunnable = new Set([
  "eeg-mi-bnci2014", "celegans-structure-function-divergence", "brain-age-mri",
]);
const baselinePsychRunnable = new Set([
  "psych101-gershman2018deconstructing-exp1",
  "psych101-gershman2018deconstructing-exp2",
  "psych101-hilbig2014generalized-exp1",
  "psych101-lefebvre2017behavioural-exp1",
  "psych101-lefebvre2017behavioural-exp2",
  "psych101-ludwig2023human-exp2",
  "psych101-schulz2020finding-exp2",
  "psych101-speekenbrink2008learning-exp1",
  "psych101-steingroever2015data-exp1",
  "psych101-steingroever2015data-exp2",
  "psych101-steingroever2015data-exp3",
  "psych101-wilson2014humans-exp5",
]);
const domains = new Set(["eeg", "psychology", "mri", "connectomics", ...mouseDomains, ...invasiveDomains]);

function fail(message) { errors.push(message); }
function readJson(path, label) {
  try { return JSON.parse(readFileSync(path, "utf8")); }
  catch (error) { fail(`${label}: cannot parse JSON (${error.message})`); return null; }
}
function plainFile(path, label) {
  try {
    if (lstatSync(path).isFile()) return true;
    fail(`${label}: missing regular file or symlink forbidden`);
  } catch { fail(`${label}: missing regular file`); }
  return false;
}
function insideRepo(rel, label) {
  if (typeof rel !== "string" || isAbsolute(rel)) { fail(`${label}: expected repository-relative path`); return null; }
  const full = resolve(repo, rel);
  const back = relative(repo, full);
  if (back.startsWith(`..${sep}`) || back === ".." || isAbsolute(back)) {
    fail(`${label}: path escapes repository`); return null;
  }
  return full;
}
function primaryMetric(metric, label) {
  if (!metric || typeof metric.id !== "string" || !metric.id ||
      !["maximize", "minimize"].includes(metric.direction)) {
    fail(`${label}: missing parsed primary metric id/direction`);
  }
}
function addIdentity(map, id, origin) {
  if (typeof id !== "string" || !id) { fail(`${origin}: missing task id`); return; }
  if (map.has(id)) fail(`duplicate task id ${id}: ${map.get(id)} and ${origin}`);
  else map.set(id, origin);
}

const identities = new Map();
const runnables = new Map();
const registry = loadCategories(repo);
let privateIncrement = null;
try { privateIncrement = validatePrivateEvaluatorIncrement(repo); }
catch (error) { fail(`private evaluator increment: ${error.message}`); }
for (const dir of discoverTaskDirs([tasksRoot])) {
  const relDir = relative(repo, dir).split(sep).join("/");
  const components = relative(tasksRoot, dir).split(sep);
  if (components.length !== 2 || !domains.has(components[0])) {
    fail(`${relDir}: runnable task must be tasks/<domain>/<id>`);
  }
  let task;
  try { task = loadTask(dir); }
  catch (error) { fail(`${relDir}: loadTask failed (${error.message})`); continue; }
  const id = task.meta.id;
  if (components[0] === "animal-behavior") {
    try { readMouseAcceptance(repo, task); }
    catch (error) { fail(`${relDir}: ${error.message}`); }
  }
  addIdentity(identities, id, relDir);
  if (runnables.has(id)) fail(`duplicate runnable id ${id}`);
  runnables.set(id, { task, dir, relDir, domain: components[0] });
  if (id !== components[1]) fail(`${relDir}: task.yaml id differs from directory`);
  if (["ieeg", "intracortical"].includes(components[0])) {
    try {
      if (!readInvasiveAcceptance(repo, dir, task)) fail(`${relDir}: missing scientific acceptance`);
    } catch (error) { fail(`${relDir}: acceptance: ${error.message}`); }
  }

  for (const issue of validateTaskSchema(task, registry)) {
    if (issue.level === "error") fail(`${relDir}: schema: ${issue.msg}`);
  }
  for (const rel of ["README.md", "prompt/turns.yaml", "data.lock", "env/setup.sh"]) {
    plainFile(join(dir, rel), `${relDir}/${rel}`);
  }
  const execScorers = task.scorers.filter((scorer) => scorer.kind === "exec-script");
  if (!execScorers.length) fail(`${relDir}: no exec-script scorer`);
  if (!legacyVersions.has(id) && execScorers.some((scorer) => scorer.submission_isolation !== "container")) {
    fail(`${relDir}: new runnable must declare container-isolated submission execution`);
  }
  for (const scorer of execScorers) {
    const rel = scorer.script ?? "checks/check.sh";
    const full = resolve(dir, rel);
    const back = relative(dir, full);
    if (typeof rel !== "string" || back.startsWith(`..${sep}`) || back === ".." || isAbsolute(back)) {
      fail(`${relDir}: scorer path escapes task`);
    } else plainFile(full, `${relDir}/${rel}`);
  }
  if (legacyVersions.has(id)) {
    if (task.meta.version !== legacyVersions.get(id)) fail(`${relDir}: legacy task version changed`);
  } else {
    primaryMetric(task.meta.evaluation?.primaryMetric, relDir);
  }
}

for (const [id, version] of legacyVersions) {
  const entry = runnables.get(id);
  if (!entry || entry.task.meta.version !== version) fail(`legacy runnable ${id}@${version} missing`);
}
for (const id of [...baselineNewRunnable, ...baselinePsychRunnable]) {
  if (!runnables.has(id)) fail(`baseline runnable ${id} missing`);
}

const eegCandidates = new Map();
const eegRoot = join(tasksRoot, "eeg");
for (const entry of readdirSync(eegRoot, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const dir = join(eegRoot, entry.name);
  const path = join(dir, "candidate.json");
  if (!existsSync(path)) continue;
  const relDir = relative(repo, dir).split(sep).join("/");
  if (!plainFile(path, `${relDir}/candidate.json`)) continue;
  if (existsSync(join(dir, "task.yaml"))) fail(`${relDir}: candidate must not have task.yaml`);
  const card = readJson(path, relDir);
  if (!card) continue;
  addIdentity(identities, card.id, relDir);
  eegCandidates.set(card.id, { card, relDir });
  if (card.id !== entry.name || !card.id.startsWith("eeg-")) fail(`${relDir}: candidate id/path mismatch`);
  if (!["metadata_only_not_runnable", "preparation_ready_data_pending", "withheld_by_owner"].includes(card.status))
    fail(`${relDir}: unsupported candidate status`);
  if (card.status === "preparation_ready_data_pending") {
    for (const file of ["preparation.json", "README.md", "env/prepare.py", "checks/verify_export.py"])
      plainFile(join(dir, file), `${relDir}/${file}`);
    const preparation = readJson(join(dir, "preparation.json"), `${relDir}/preparation.json`);
    if (preparation?.source_sha !== card.upstream_source_sha && preparation?.upstream_source_sha !== card.upstream_source_sha)
      fail(`${relDir}: preparation source SHA does not match candidate`);
  }
  if (typeof card.source_task_id !== "string" || !card.source_task_id) fail(`${relDir}: source_task_id missing`);
  if (typeof card.upstream_source_sha !== "string" || !/^[0-9a-f]{40}$/.test(card.upstream_source_sha)) fail(`${relDir}: upstream SHA missing`);
  for (const field of ["dataset_group_id", "input_description", "output_description", "native_split_description"]) {
    if (typeof card[field] !== "string" || !card[field]) fail(`${relDir}: ${field} missing`);
  }
  primaryMetric(card.primary_metric, relDir);
}

const invasiveCandidates = new Map();
try {
  for (const entry of readInvasiveCandidates(repo)) {
    addIdentity(identities, entry.card.id, entry.relDir);
    invasiveCandidates.set(entry.card.id, entry);
  }
} catch (error) { fail(`invasive candidates: ${error.message}`); }

const mouseCandidates = new Map();
try {
  for (const entry of readMouseCandidates(repo)) {
    addIdentity(identities, entry.card.id, entry.relDir);
    mouseCandidates.set(entry.card.id, entry);
  }
} catch (error) { fail(`mouse candidates: ${error.message}`); }

const psychMetadataPath = join(tasksRoot, "psychology", "metadata-only.json");
const psychMetadata = plainFile(psychMetadataPath, "tasks/psychology/metadata-only.json")
  ? readJson(psychMetadataPath, "psychology metadata") : null;
const psychCandidates = new Map();
if (psychMetadata) {
  if (!Array.isArray(psychMetadata.tasks)) fail("psychology metadata: tasks must be an array");
  else {
    if (psychMetadata.count !== psychMetadata.tasks.length) fail("psychology metadata: declared count mismatch");
    for (const card of psychMetadata.tasks) {
      const id = card.proposed_task_id;
      addIdentity(identities, id, "tasks/psychology/metadata-only.json");
      if (psychCandidates.has(id)) fail(`duplicate psychology metadata id ${id}`);
      psychCandidates.set(id, card);
      if (typeof id !== "string" || !id.startsWith("psych101-")) fail(`psychology candidate: invalid id ${id}`);
      if (typeof card.original_experiment_id !== "string" || !card.original_experiment_id) fail(`${id}: source experiment missing`);
      if (existsSync(join(tasksRoot, "psychology", id, "task.yaml"))) fail(`${id}: metadata candidate also has task.yaml`);
    }
  }
}

const counts = {
  runnable: runnables.size,
  eegCandidate: eegCandidates.size,
  psychologyMetadata: psychCandidates.size,
  invasiveCandidate: invasiveCandidates.size,
  mouseCandidate: mouseCandidates.size,
  candidate: eegCandidates.size + psychCandidates.size + invasiveCandidates.size + mouseCandidates.size,
  preparation_ready: [...eegCandidates.values(), ...invasiveCandidates.values(), ...mouseCandidates.values()]
    .filter(e => e.card.status === "preparation_ready_data_pending").length,
  total: identities.size,
};
if (counts.runnable < baseline.runnable || counts.total < baseline.total) {
  fail(`baseline inventory missing: expected at least ${JSON.stringify(baseline)}, observed ${JSON.stringify(counts)}`);
}
const runnableDomains = Object.fromEntries([...domains].map((domain) =>
  [domain, [...runnables.values()].filter((entry) => entry.domain === domain).length]));
if (runnableDomains.eeg + counts.eegCandidate < baseline.eeg ||
    runnableDomains.psychology + counts.psychologyMetadata < baseline.psychology)
  fail("baseline EEG/Psychology identity coverage was lost");
if (runnableDomains.eeg < 3 || runnableDomains.psychology < 12 ||
    runnableDomains.connectomics < 1 || runnableDomains.mri < 2 || runnableDomains["calcium-imaging"] < 1) {
  fail("baseline runnable domain split 3 EEG / 12 psychology / 1 connectomics / 2 MRI / 1 calcium-imaging missing");
}

const catalogPath = join(tasksRoot, "catalog.json");
const catalog = existsSync(catalogPath) ? readJson(catalogPath, "tasks/catalog.json") : null;
if (catalog) {
  if (!Array.isArray(catalog.tasks)) fail("catalog.tasks must be an array");
  else {
    const seen = new Set();
    for (const entry of catalog.tasks) {
      const id = entry.task_id;
      if (seen.has(id)) fail(`catalog duplicate task_id ${id}`);
      seen.add(id);
      const kind = runnables.has(id) ? "runnable" :
        eegCandidates.has(id) || psychCandidates.has(id) || invasiveCandidates.has(id) || mouseCandidates.has(id) ? "candidate" : null;
      if (!kind) { fail(`catalog unknown task_id ${id}`); continue; }
      if (entry.entry_kind !== kind) fail(`catalog ${id}: entry_kind mismatch`);
      const domain = runnables.get(id)?.domain ?? invasiveCandidates.get(id)?.domain ?? mouseCandidates.get(id)?.domain
        ?? (eegCandidates.has(id) ? "eeg" : "psychology");
      if (entry.domain !== domain) fail(`catalog ${id}: domain mismatch`);
      if (invasiveCandidates.has(id)) {
        for (const [field, expected] of Object.entries(invasiveCatalogRow(invasiveCandidates.get(id)))) {
          if (JSON.stringify(entry[field]) !== JSON.stringify(expected))
            fail(`catalog ${id}: candidate ${field} mismatch`);
        }
      }
      if (mouseCandidates.has(id)) {
        const expectedRow = mouseCatalogRow(mouseCandidates.get(id));
        if (JSON.stringify(Object.keys(entry).sort()) !== JSON.stringify(Object.keys(expectedRow).sort()))
          fail(`catalog ${id}: mouse candidate fields mismatch`);
        for (const [field, expected] of Object.entries(expectedRow)) {
          if (JSON.stringify(entry[field]) !== JSON.stringify(expected))
            fail(`catalog ${id}: candidate ${field} mismatch`);
        }
      }
      const expectedPath = runnables.get(id)?.relDir ?? eegCandidates.get(id)?.relDir
        ?? invasiveCandidates.get(id)?.relDir ?? mouseCandidates.get(id)?.relDir;
      if (kind === "runnable" || eegCandidates.has(id) || invasiveCandidates.has(id) || mouseCandidates.has(id)) {
        if (entry.directory !== expectedPath) fail(`catalog ${id}: directory mismatch`);
        const metric = runnables.get(id)?.task.meta.evaluation?.primaryMetric ?? eegCandidates.get(id)?.card.primary_metric
          ?? invasiveCandidates.get(id)?.card.primary_metric ?? mouseCandidates.get(id)?.card.primary_metric;
        if (metric && (entry.primary_metric?.id !== metric.id || entry.primary_metric?.direction !== metric.direction))
          fail(`catalog ${id}: primary metric mismatch`);
        if (kind === "runnable" && entry.task_version !== runnables.get(id).task.meta.version)
          fail(`catalog ${id}: task version mismatch`);
        if (kind === "runnable") {
          const datasets = runnables.get(id).task.datasets;
          const access = rows => rows.some(d => d.uri.startsWith("local://"))
            ? "maintainer_package_required" : "pinned_source_download";
          const publicDatasets = datasets.filter(d => d.scope === "public");
          const invasive = ["ieeg", "intracortical"].includes(domain);
          const dataCategory = invasive ? "invasive" : domain;
          const canonicalPrefix = `tasks/${dataCategory}/${id}/public/`;
          const hostedPublic = publicDatasets.length > 0 && publicDatasets.every(d => {
            const match = /^hf:\/\/datasets\/BrainPilot-Bench\/Tasks-Data-Public@([0-9a-f]{40})\/(.+)$/.exec(d.uri);
            return match && match[2].startsWith(canonicalPrefix);
          });
          const hostedAvailability = hostedPublic ? "published_public_snapshot"
            : id === "falcon-h1-reach-grasp" ? "source_only" : undefined;
          if (entry.hosted_data_availability !== hostedAvailability)
            fail(`catalog ${id}: hosted public availability mismatch`);
          const publicAccess = hostedPublic ? "pinned_public_snapshot" : access(publicDatasets);
          if (entry.data_access !== publicAccess)
            fail(`catalog ${id}: public data access mismatch`);
          if (invasive) {
            const accepted = readJson(join(runnables.get(id).dir, "acceptance.json"), `catalog ${id} acceptance`);
            if (entry.data_status !== (accepted?.data_status ?? "source_bound_reproducible_export"))
              fail(`catalog ${id}: scientific data status mismatch`);
          } else if (hostedPublic && entry.data_status !== "published_public_package") {
            fail(`catalog ${id}: public package status mismatch`);
          }
          const privateDatasets = datasets.filter(d => d.scope === "private");
          let sourceEvaluator = false;
          let hostedMouseEvaluator = false;
          if (existsSync(join(runnables.get(id).dir, "evaluator.lock")) && !privateIncrement?.byId.has(id)) {
            try {
              if (domain === "animal-behavior") {
                const acceptedMouse = readMouseAcceptance(repo, runnables.get(id).task);
                const lock = readEvaluatorLock(runnables.get(id).task);
                sourceEvaluator = !!acceptedMouse && lock.schema === "bpb-evaluator-source/1";
                hostedMouseEvaluator = !!acceptedMouse?.delivery?.privateHosted && lock.schema === "bpb-evaluator-data/1";
                if (entry.delivery_validation_record !== acceptedMouse?.delivery?.record)
                  fail(`catalog ${id}: mouse delivery record mismatch`);
              }
            } catch (error) { fail(`catalog ${id}: invalid source evaluator (${error.message})`); }
          }
          const privateAccess = privateIncrement?.byId.has(id) || hostedMouseEvaluator ? "pinned_private_snapshot"
            : sourceEvaluator ? "source_prepared_evaluator"
            : privateDatasets.length ? access(privateDatasets) : undefined;
          if (entry.private_data_access !== privateAccess)
            fail(`catalog ${id}: private data access mismatch`);
          const privateEntry = privateIncrement?.byId.has(id) || sourceEvaluator || hostedMouseEvaluator ? privateScoreEntry : undefined;
          if (entry.private_score_entry !== privateEntry)
            fail(`catalog ${id}: private score entry mismatch`);
          if (existsSync(join(runnables.get(id).dir, "evaluator.lock")) && !privateIncrement?.byId.has(id) && !sourceEvaluator && !hostedMouseEvaluator)
            fail(`catalog ${id}: evaluator.lock is outside the frozen private increment`);
        }
      } else {
        const metadataPath = insideRepo(entry.metadata_file, `catalog ${id} metadata_file`);
        if (metadataPath !== psychMetadataPath) fail(`catalog ${id}: psychology metadata_file mismatch`);
      }
    }
    for (const id of identities.keys()) if (!seen.has(id)) fail(`catalog missing task_id ${id}`);
    for (const [name, actual] of [["total", counts.total], ["runnable", counts.runnable],
      ["candidate", counts.candidate], ["mouse_candidate", counts.mouseCandidate],
      ["preparation_ready", counts.preparation_ready]]) {
      if (catalog.counts?.[name] !== actual) fail(`catalog count ${name} mismatch: ${catalog.counts?.[name]} vs ${actual}`);
    }
  }
}

const summary = {
  ok: errors.length === 0,
  read_only: true,
  task_code_executed: false,
  network_or_download_used: false,
  counts,
  baseline_minimum: baseline,
  runnable_domains: runnableDomains,
  catalog: { present: catalog !== null, entries: Array.isArray(catalog?.tasks) ? catalog.tasks.length : null },
  errors,
};
console.log(JSON.stringify(summary, null, 2));
if (errors.length) process.exitCode = 1;
