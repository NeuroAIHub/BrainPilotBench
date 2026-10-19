/** Read local engineering evidence only; never launch code, data, or model runs. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { validatePrivateEvaluatorIncrement } from "./private-evaluator-increment.mjs";

const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
const hex64 = value => /^[0-9a-f]{64}$/.test(value ?? "");
const hex40 = value => /^[0-9a-f]{40}$/.test(value ?? "");
const bridgeFiles = ["src/data/types.ts", "src/data/manifest.ts", "src/workflow.ts", "src/cli.ts"];
const optionalBridgeFiles = ["src/data/cache.ts", "src/data/fetch.ts", "src/data/resolve.ts"];
const hostedInvasiveIds = ["ieeg-finger-flexion-bciciv4", "falcon-h2-handwriting", "falcon-m1-emg",
  "falcon-m2-finger-velocity", "falcon-b1-birdsong", "ieeg-film-speech-music"];
// Original scientific acceptance records at 9d92b6738189d23607478ee1f71bdb6ff567d07b.
export const priorAcceptanceSha256 = Object.freeze({
  "ieeg-finger-flexion-bciciv4": "09de5cf540ad15310bb8d00a7a6e61df50bc868cc71676f1b7d114ee1717b47d",
  "falcon-h2-handwriting": "93f5318d1076a0ac1b7be0a0292872c8143018e560d7578da1e429e84af1d2f4",
  "falcon-m1-emg": "0678ea44a686cea66b2041befc8c39083e42f8b64b13dddaeb742e5c11dbef49",
  "falcon-m2-finger-velocity": "282581e0f6bfec0de25d8e1a3c975e730237f7c3799bf06e9545f9d00c0a6fba",
  "falcon-b1-birdsong": "0369a3f6eab9602d740bb46803182740c0c00fba2008db01ba0778a50cc56d51",
  "ieeg-film-speech-music": "b2e2927651129a36b6dd326fd51df786430ee0d209aaeeea7e69a60279707908",
});

export function validateUnifiedDeliveryReport(report, revision) {
  if (report.schema !== "bpb-unified-public-verification/1" || report.published_revision !== revision ||
      report.metadata?.scope !== "all" || report.metadata?.tasks !== 112 ||
      report.metadata?.hosted_tasks !== 111 || report.metadata?.source_only_tasks !== 1 ||
      report.metadata?.public_files !== 668 ||
      !["representative", "all"].includes(report.downloads?.scope) ||
      !Array.isArray(report.downloads?.verified_targets) || !report.downloads.verified_targets.length ||
      new Set(report.downloads.verified_targets).size !== report.downloads.verified_targets.length ||
      report.downloads.verified_targets.some(target =>
        typeof target !== "string" || !/^tasks\/(?:eeg|mri|psychology|connectomics|calcium-imaging|invasive)\/[^/]+\/public\/.+/.test(target)) ||
      (report.downloads.scope === "all" && report.downloads.verified_targets.length !== 668) ||
      (report.downloads.scope === "representative" && report.downloads.verified_targets.length >= 668) ||
      hostedInvasiveIds.some(id => report.setup?.public_output_checks?.[id]?.passed !== true ||
        report.setup.public_output_checks[id].manifest_hash_verified !== true) ||
      report.owner_test_run !== false)
    throw new Error("incomplete or overstated unified public verification report");
}

export function validatePublicPreviewMapping(id, publicEntries, planned, revision) {
  const uriPrefix = `hf://datasets/BrainPilot-Bench/Tasks-Data-Public@${revision}/tasks/invasive/${id}/public/`;
  const plannedByTarget = new Map(planned.map(op => [op.target, op]));
  const seenTargets = new Set();
  if (publicEntries.length !== planned.length || plannedByTarget.size !== planned.length ||
      publicEntries.some(entry => {
        const target = `tasks/invasive/${id}/public/${entry.path}`;
        const op = plannedByTarget.get(target);
        if (!entry.path || entry.path.startsWith("/") || entry.path.split("/").some(part => !part || part === "." || part === "..") ||
            !entry.uri.startsWith(uriPrefix) || entry.uri !== `${uriPrefix}${entry.path}` ||
            seenTargets.has(target) || !op || op.sha256 !== entry.sha256 || op.bytes !== entry.bytes) return true;
        seenTargets.add(target);
        return false;
      }) || seenTargets.size !== plannedByTarget.size)
    throw new Error(`${id}: public lock differs from the published preview mapping`);
}

function boundFile(root, file, allowedPrefixes) {
  if (typeof file !== "string" || file.startsWith("/") || file.split("/").some(part => !part || part === "." || part === "..") ||
      !allowedPrefixes.some(prefix => file.startsWith(prefix)))
    throw new Error(`unsafe evidence binding: ${file}`);
  let current = root;
  for (const component of file.split("/")) {
    current = join(current, component);
    if (lstatSync(current).isSymbolicLink()) throw new Error(`linked evidence file: ${file}`);
  }
  if (!lstatSync(current).isFile()) throw new Error(`missing evidence file: ${file}`);
  return readFileSync(current);
}

function validateDelivery(root, dir, task, acceptanceBytes, record, changedFiles) {
  const deliveryPath = join(dir, "delivery-acceptance.json");
  if (!existsSync(deliveryPath)) throw new Error(`${deliveryPath}: missing fresh delivery acceptance`);
  if (!lstatSync(deliveryPath).isFile() || lstatSync(deliveryPath).isSymbolicLink())
    throw new Error(`${deliveryPath}: expected a regular delivery receipt`);
  const delivery = JSON.parse(readFileSync(deliveryPath, "utf8"));
  const prefix = relative(root, dir).split(sep).join("/");
  const allowed = [`${prefix}/data.lock`, `${prefix}/env/setup.sh`];
  if (delivery.schema !== "bpb-unified-public-delivery/1" || delivery.status !== "passed" ||
      delivery.task_id !== task.meta.id || delivery.task_version !== task.meta.version ||
      !hex40(delivery.published_revision) || delivery.prior_acceptance_sha256 !== sha256(acceptanceBytes) ||
      (priorAcceptanceSha256[task.meta.id] && delivery.prior_acceptance_sha256 !== priorAcceptanceSha256[task.meta.id]) ||
      JSON.stringify(Object.keys(delivery.old_file_sha256 ?? {}).sort()) !== JSON.stringify(allowed.sort()) ||
      JSON.stringify(Object.keys(delivery.new_file_sha256 ?? {}).sort()) !== JSON.stringify(allowed.sort()) ||
      JSON.stringify(changedFiles.sort()) !== JSON.stringify(allowed.sort()))
    throw new Error(`${deliveryPath}: invalid delivery binding or changed scope`);
  let increment;
  const currentIncrement = () => {
    increment ??= validatePrivateEvaluatorIncrement(root);
    const item = increment.byId.get(task.meta.id);
    if (!item || item.prior_delivery_sha256 !== sha256(readFileSync(deliveryPath)))
      throw new Error(`${deliveryPath}: private increment does not bind this delivery receipt`);
    return item;
  };
  for (const file of allowed) {
    const actual = sha256(boundFile(root, file, [`${prefix}/`]));
    if (delivery.old_file_sha256[file] !== record.file_sha256[file] ||
        !hex64(delivery.new_file_sha256[file]) ||
        (actual !== delivery.new_file_sha256[file] &&
          (file !== `${prefix}/data.lock` || currentIncrement().data_lock_sha256 !== actual ||
            currentIncrement().prior_data_lock_sha256 !== delivery.new_file_sha256[file])))
      throw new Error(`${deliveryPath}: stale or incorrect delivery hash for ${file}`);
  }
  const bridge = delivery.bridge_file_sha256;
  if (!bridge || bridgeFiles.some(file => !hex64(bridge[file])) ||
      Object.keys(bridge).some(file => ![...bridgeFiles, ...optionalBridgeFiles].includes(file)))
    throw new Error(`${deliveryPath}: incomplete bridge bindings`);
  for (const [file, expected] of Object.entries(bridge)) {
    const actual = sha256(boundFile(root, file, ["src/"]));
    if (!hex64(expected)) throw new Error(`${deliveryPath}: invalid bridge hash for ${file}`);
    if (actual !== expected) {
      currentIncrement();
      if (increment.report.core_file_sha256[file] !== actual)
        throw new Error(`${deliveryPath}: stale bridge hash for ${file}`);
    }
  }
  const reportBinding = delivery.verification_report;
  if (!reportBinding || !hex64(reportBinding.sha256) ||
      !/^(?:tasks|reports)\/[A-Za-z0-9._/-]+\.json$/.test(reportBinding.path ?? ""))
    throw new Error(`${deliveryPath}: invalid verification report binding`);
  const reportBytes = boundFile(root, reportBinding.path, ["tasks/", "reports/"]);
  if (sha256(reportBytes) !== reportBinding.sha256)
    throw new Error(`${deliveryPath}: stale verification report`);
  const report = JSON.parse(reportBytes);
  try { validateUnifiedDeliveryReport(report, delivery.published_revision); }
  catch (error) { throw new Error(`${deliveryPath}: ${error.message}`); }
  const publicDatasets = task.datasets.filter(entry => entry.scope === "public");
  if (!publicDatasets.length || publicDatasets.some(entry =>
    !entry.uri.startsWith(`hf://datasets/BrainPilot-Bench/Tasks-Data-Public@${delivery.published_revision}/tasks/invasive/${task.meta.id}/public/`) ||
    !entry.path || entry.path.startsWith("/") || entry.path.split("/").some(part => !part || part === "." || part === "..")))
    throw new Error(`${deliveryPath}: public lock does not bind the published native snapshot`);
  if (task.datasets.filter(entry => entry.scope === "private").some(entry => entry.path !== undefined))
    throw new Error(`${deliveryPath}: private entry has a prepared path`);
}

export function requiredInvasiveBindings(root, dir) {
  const prefix = relative(root, dir).split(sep).join("/");
  const files = new Set(["task.yaml", "contract.json", "data.lock", "protocol.json", "prompt/turns.yaml", "checks/check.sh"]
    .map(name => `${prefix}/${name}`));
  const includeDirectory = directory => {
    for (const item of readdirSync(directory, { recursive: true, withFileTypes: true })) {
      if (item.isFile() && (/\.(py|sh)$/.test(item.name) || /^requirements.*\.txt$/.test(item.name) || item.name === "Dockerfile"))
        files.add(relative(root, join(item.parentPath, item.name)).split(sep).join("/"));
    }
  };
  includeDirectory(dir);
  for (const item of readdirSync(dir))
    if (/(^|_)source_manifest.*\.json$/.test(item)) files.add(`${prefix}/${item}`);
  if (existsSync(join(dir, "cohort_inventory.json"))) files.add(`${prefix}/cohort_inventory.json`);
  const id = prefix.split("/").at(-1);
  if (id.startsWith("falcon-")) {
    for (const name of ["assets.manifest.json", "prepare.py", "check_manifest.py", "make_manifest.py", "requirements.txt"])
      files.add(`tasks/intracortical/_preparation/${name}`);
    files.add("tasks/intracortical/_shared/native.py");
  }
  if (["falcon-m1-emg", "falcon-m2-finger-velocity"].includes(id))
    includeDirectory(join(root, "tasks/intracortical/_regression_shared"));
  if (["falcon-h2-handwriting", "falcon-b1-birdsong"].includes(id)) {
    includeDirectory(join(root, "tasks/intracortical/_sequence_shared"));
    files.add("tasks/intracortical/_shared/metrics.py");
  }
  if (["ieeg-finger-flexion-bciciv4", "falcon-h2-handwriting", "falcon-b1-birdsong"].includes(id))
    files.add("tasks/intracortical/falcon-h1-reach-grasp/checks/score.py");
  return [...files].sort();
}

export function readInvasiveAcceptance(root, dir, task) {
  const path = join(dir, "acceptance.json");
  if (!existsSync(path)) return null;
  if (!lstatSync(path).isFile()) throw new Error(`${path}: expected a regular record`);
  const acceptanceBytes = readFileSync(path);
  const record = JSON.parse(acceptanceBytes);
  if (record.schema !== "bpb-local-task-acceptance/1" || record.task_id !== task.meta.id ||
      record.task_version !== task.meta.version || record.status !== "passed" ||
      record.agent_benchmark_run !== false || record.public_validation?.status !== "passed" ||
      record.owner_test?.status !== "fixed_reference_interface_passed" || record.owner_test?.model_tuned !== false ||
      typeof record.source_task_id !== "string" || !record.source_task_id ||
      typeof record.source_verification !== "string" || !record.source_verification ||
      (record.data_status !== undefined && !["source_bound_reproducible_export", "owner_key_bound_prepared_export"].includes(record.data_status)) ||
      record.public_validation.metric_id !== task.meta.evaluation?.primaryMetric?.id ||
      record.public_validation.profile !== task.meta.evaluation?.profile ||
      !Number.isFinite(record.public_validation.value) ||
      !/^[0-9a-f]{64}$/.test(record.public_validation.cli_report_sha256 ?? "") ||
      !/^[0-9a-f]{64}$/.test(record.owner_test.report_sha256 ?? "") ||
      !/^[0-9a-f]{64}$/.test(record.owner_test.frozen_artifact_receipt_sha256 ?? "") ||
      record.owner_test.scores_published_as_agent_results !== false ||
      JSON.stringify(Object.keys(record.reference_artifact_sha256 ?? {}).sort()) !==
        JSON.stringify(["config.json", "model.py", "weights.safetensors"]) ||
      Object.values(record.reference_artifact_sha256 ?? {}).some(value => !/^[0-9a-f]{64}$/.test(value)) ||
      !Array.isArray(record.checks) || !record.checks.includes("cli_submission_and_isolated_scoring") ||
      !record.file_sha256 || typeof record.file_sha256 !== "object")
    throw new Error(`${path}: invalid engineering acceptance record`);
  for (const file of requiredInvasiveBindings(root, dir))
    if (!record.file_sha256[file]) throw new Error(`${path}: missing ${file} binding`);
  const changedFiles = [];
  for (const [file, expected] of Object.entries(record.file_sha256)) {
    const full = resolve(root, file);
    const back = relative(join(root, "tasks"), full);
    if (!file.startsWith("tasks/") || back.startsWith(`..${sep}`) || back === ".." ||
        !/^[0-9a-f]{64}$/.test(expected)) throw new Error(`${path}: unsafe evidence binding`);
    const actual = sha256(boundFile(root, file, ["tasks/"]));
    if (actual !== expected) {
      const prefix = relative(root, dir).split(sep).join("/");
      if (![`${prefix}/data.lock`, `${prefix}/env/setup.sh`].includes(file))
        throw new Error(`${path}: acceptance is stale for ${file}`);
      changedFiles.push(file);
    }
  }
  if (changedFiles.length || existsSync(join(dir, "delivery-acceptance.json")))
    validateDelivery(root, dir, task, acceptanceBytes, record, changedFiles);
  return record;
}
