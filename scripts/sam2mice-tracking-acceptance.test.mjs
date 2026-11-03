import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { TRACKING_BINDINGS, TRACKING_TASK_ID, readTrackingAcceptance } from "./sam2mice-tracking-acceptance.mjs";

function fixture(run) {
  const root = mkdtempSync(join(realpathSync(tmpdir()), "bpb-tracking-receipt-"));
  const taskPath = `tasks/animal-behavior/${TRACKING_TASK_ID}`;
  const record = join(root, "reports/sam2mice-tracking-20261103/acceptance.json");
  const bindings = {};
  const review = { status: "passed", author_gt_verified: true, image_label_alignment_verified: true,
    identity_continuity_verified: true, clean_input_verified: true };
  const split = { status: "frozen", no_model_scores_used: true };
  for (const file of TRACKING_BINDINGS) {
    const content = file.endsWith("/source-review.json") ? JSON.stringify(review)
      : file.endsWith("/split-review.json") ? JSON.stringify(split) : `fixture ${file}\n`;
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), content);
    bindings[file] = createHash("sha256").update(content).digest("hex");
  }
  const report = { schema: "bpb-sam2mice-tracking-acceptance/1", task_id: TRACKING_TASK_ID,
    task_version: "0.1", status: "local_cli_passed", kind: "fixed_reference_not_agent_benchmark",
    author_gt_verified: true, source_review_passed: true, split_frozen_before_model: true,
    private_interface_passed: true, private_metrics_published: false, public_score_executed: true,
    source_only: true, data_uploaded: false, image_id: "sha256:" + "a".repeat(64),
    private_result_sha256: "b".repeat(64), bindings,
    steps: ["fetch-public", "manual-prepare", "reference-public-train", "manual-resume", "verify-submission",
      "score-public", "prepare-evaluator", "score-private"].map(step => ({ step, ok: true, exit_code: 0 })) };
  const save = value => { mkdirSync(dirname(record), { recursive: true }); writeFileSync(record, JSON.stringify(value)); };
  const candidate = { meta: { id: TRACKING_TASK_ID, version: "0.1", domain: "animal-behavior" } };
  save(report);
  try { run({ root, taskPath, candidate, report, review, save }); }
  finally { rmSync(root, { recursive: true, force: true }); }
}

test("tracking acceptance requires source-reviewed GT and complete isolated CLI evidence", () => fixture(f => {
  assert.equal(readTrackingAcceptance(f.root, f.candidate).report.task_id, TRACKING_TASK_ID);
  for (const field of ["author_gt_verified", "source_review_passed", "split_frozen_before_model", "private_interface_passed"])
    assert.throws(() => { f.save({ ...f.report, [field]: false }); readTrackingAcceptance(f.root, f.candidate); }, /invalid or overstated/);
  f.save({ ...f.report, data_uploaded: true });
  assert.throws(() => readTrackingAcceptance(f.root, f.candidate), /invalid or overstated/);
  f.save({ ...f.report, steps: f.report.steps.slice(0, -1) });
  assert.throws(() => readTrackingAcceptance(f.root, f.candidate), /incomplete/);
}));

test("changed GT review or trusted implementation invalidates acceptance", () => fixture(f => {
  const file = `${f.taskPath}/source-review.json`;
  writeFileSync(join(f.root, file), JSON.stringify({ ...f.review, clean_input_verified: false }));
  assert.throws(() => readTrackingAcceptance(f.root, f.candidate), /stale tracking/);
  f.report.bindings[file] = createHash("sha256").update(readFileSync(join(f.root, file))).digest("hex");
  f.save(f.report);
  assert.throws(() => readTrackingAcceptance(f.root, f.candidate), /source review/);
}));

test("tracking profile does not accept another task or domain", () => fixture(f => {
  assert.equal(readTrackingAcceptance(f.root, { meta: { id: "unknown-task" } }), null);
  assert.throws(() => readTrackingAcceptance(f.root, { meta: { ...f.candidate.meta, domain: "calcium-imaging" } }), /domain mismatch/);
}));
