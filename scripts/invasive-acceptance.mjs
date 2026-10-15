/** Read local engineering evidence only; never launch code, data, or model runs. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";

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
  const record = JSON.parse(readFileSync(path, "utf8"));
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
  for (const [file, expected] of Object.entries(record.file_sha256)) {
    const full = resolve(root, file);
    const back = relative(join(root, "tasks"), full);
    if (!file.startsWith("tasks/") || back.startsWith(`..${sep}`) || back === ".." ||
        !/^[0-9a-f]{64}$/.test(expected)) throw new Error(`${path}: unsafe evidence binding`);
    let current = root;
    for (const component of file.split("/")) {
      current = join(current, component);
      if (lstatSync(current).isSymbolicLink()) throw new Error(`${path}: linked evidence file`);
    }
    if (!lstatSync(full).isFile() || createHash("sha256").update(readFileSync(full)).digest("hex") !== expected)
      throw new Error(`${path}: acceptance is stale for ${file}`);
  }
  return record;
}
