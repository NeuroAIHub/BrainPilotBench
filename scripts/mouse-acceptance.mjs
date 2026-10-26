/** Verify recorded local CLI acceptance; never replay data or model execution. */
import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { join } from "node:path";

const TASKS = new Set(["calms21-classic-classification", "calms21-annotation-style-transfer",
  "calms21-few-shot-behavior", "mabe22-supervised-segmentation", "mabe22-representation-classification"]);
const PRIVATE_ONLY = new Set(["calms21-few-shot-behavior", "mabe22-representation-classification"]);
const FILES = ["contract.json", "data.lock", "evaluator.lock", "task.yaml"];
const STEPS = ["fetch-public", "manual-prepare", "reference-public-train", "manual-resume",
  "verify-submission", "prepare-evaluator", "score-private"];
const hex = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
function bytes(path) {
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.nlink !== 1) throw new Error(`${path}: ordinary independent evidence file required`);
  return readFileSync(path);
}

export function readMouseAcceptance(root, task) {
  if (task.meta.domain !== "animal-behavior") return null;
  if (!TASKS.has(task.meta.id)) throw new Error("mouse task lacks a reviewed acceptance profile");
  const id = task.meta.id;
  const record = `reports/mouse-closeout-20261026/${id}-cli-acceptance.json`;
  const report = JSON.parse(bytes(join(root, record)));
  if (report.schema !== "bpb-mouse-cli-acceptance/1" || report.task_id !== id ||
      report.task_version !== task.meta.version || report.kind !== "fixed_reference_not_agent_benchmark" ||
      report.private_interface_passed !== true || report.private_metrics_published !== false ||
      report.source_only !== true || report.data_uploaded !== false ||
      report.public_score_executed !== !PRIVATE_ONLY.has(id) ||
      !/^sha256:[0-9a-f]{64}$/.test(report.image_id ?? "") || !hex(report.private_result_sha256) ||
      JSON.stringify(Object.keys(report.bindings ?? {}).sort()) !== JSON.stringify(FILES))
    throw new Error(`${id}: invalid or overstated CLI acceptance`);
  for (const file of FILES) {
    if (!hex(report.bindings[file]) || createHash("sha256").update(bytes(join(task.dir, file))).digest("hex") !== report.bindings[file])
      throw new Error(`${id}: stale accepted ${file}`);
  }
  if (!Array.isArray(report.steps) || report.steps.some(step => step.ok !== true || step.exit_code !== 0) ||
      new Set(report.steps.map(step => step.step)).size !== report.steps.length ||
      [...STEPS, ...(!PRIVATE_ONLY.has(id) ? ["score-public"] : [])].some(name => !report.steps.some(step => step.step === name)))
    throw new Error(`${id}: incomplete CLI acceptance steps`);
  return { record, report, privateOnly: PRIVATE_ONLY.has(id) };
}
