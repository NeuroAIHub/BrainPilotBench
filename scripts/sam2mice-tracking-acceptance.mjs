/** Verify source-reviewed tracking acceptance without running models. */
import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { readTrackingDelivery, readTransportCodeReview } from "./sam2mice-hf-delivery.mjs";

export const TRACKING_TASK_ID = "sam2mice-multi-animal-tracking";
const task = `tasks/animal-behavior/${TRACKING_TASK_ID}`;
const shared = "tasks/animal-behavior/_sam2mice_tracking";
export const TRACKING_BINDINGS = [
  ...["task.yaml", "contract.json", "data.lock", "evaluator.lock", "source-review.json", "split-review.json",
    "env/setup.sh", "checks/check.sh", "prompt/turns.yaml", "solution/reference.sh"].map(path => `${task}/${path}`),
  ...["fetch_sources.py", "prepare_source.py", "task_common.py", "package_task.py", "prepare_task.py",
    "score_task.py", "inference.py", "worker.py", "metrics.py", "reference.py", "requirements.txt", "Dockerfile"].map(path => `${shared}/${path}`),
  "tasks/animal-behavior/_shared/evaluator/score.py",
].sort();
const hex = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const steps = ["fetch-public", "manual-prepare", "reference-public-train", "manual-resume",
  "verify-submission", "score-public", "prepare-evaluator", "score-private"];

function bytes(path) {
  for (let cursor = path; ; cursor = dirname(cursor)) {
    const info = lstatSync(cursor);
    if (info.isSymbolicLink() || (cursor === path ? !info.isFile() || info.nlink !== 1 : !info.isDirectory()))
      throw new Error("tracking acceptance requires ordinary independent files");
    if (dirname(cursor) === cursor) break;
  }
  return readFileSync(path);
}

export function readTrackingAcceptance(root, candidate) {
  if (candidate.meta.id !== TRACKING_TASK_ID) return null;
  if (candidate.meta.domain !== "animal-behavior") throw new Error("tracking task domain mismatch");
  const record = "reports/sam2mice-tracking-20261103/acceptance.json";
  const report = JSON.parse(bytes(join(root, record)));
  if (report.schema !== "bpb-sam2mice-tracking-acceptance/1" || report.task_id !== TRACKING_TASK_ID ||
      report.task_version !== candidate.meta.version || report.status !== "local_cli_passed" ||
      report.kind !== "fixed_reference_not_agent_benchmark" || report.author_gt_verified !== true ||
      report.source_review_passed !== true || report.split_frozen_before_model !== true ||
      report.private_interface_passed !== true || report.private_metrics_published !== false ||
      report.source_only !== true || report.data_uploaded !== false || report.public_score_executed !== true ||
      !/^sha256:[a-f0-9]{64}$/.test(report.image_id ?? "") || !hex(report.private_result_sha256) ||
      JSON.stringify(Object.keys(report.bindings ?? {}).sort()) !== JSON.stringify(TRACKING_BINDINGS))
    throw new Error("invalid or overstated tracking acceptance");
  const codeReview = readTransportCodeReview(root, report);
  const delivery = readTrackingDelivery(root, candidate, report, codeReview);
  for (const path of TRACKING_BINDINGS) {
    const name = path.startsWith(task + "/") ? path.slice(task.length + 1) : null;
    const expected = delivery?.card.hosted_bindings?.[name]
      ?? codeReview?.review.changes?.[path]?.current_sha256 ?? report.bindings[path];
    if (!hex(report.bindings[path]) || createHash("sha256").update(bytes(join(root, path))).digest("hex") !== expected)
      throw new Error(`stale tracking acceptance: ${path}`);
  }
  const review = JSON.parse(bytes(join(root, task, "source-review.json")));
  const split = JSON.parse(bytes(join(root, task, "split-review.json")));
  if (review.status !== "passed" || review.author_gt_verified !== true ||
      review.image_label_alignment_verified !== true || review.identity_continuity_verified !== true ||
      review.clean_input_verified !== true || split.status !== "frozen" || split.no_model_scores_used !== true)
    throw new Error("tracking source review or frozen split is incomplete");
  if (!Array.isArray(report.steps) || report.steps.some(step => step.ok !== true || step.exit_code !== 0) ||
      new Set(report.steps.map(step => step.step)).size !== report.steps.length ||
      steps.some(name => !report.steps.some(step => step.step === name)))
    throw new Error("incomplete tracking CLI acceptance");
  return { record, report, privateOnly: false, delivery, transportCodeReview: codeReview };
}
