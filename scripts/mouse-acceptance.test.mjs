import test from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readMouseAcceptance } from "./mouse-acceptance.mjs";

const repo = fileURLToPath(new URL("..", import.meta.url));
const ids = ["calms21-classic-classification", "calms21-annotation-style-transfer",
  "calms21-few-shot-behavior", "mabe22-supervised-segmentation", "mabe22-representation-classification"];
function fixture(id, run) {
  const root = mkdtempSync(join(tmpdir(), "bpb-mouse-acceptance-"));
  const dir = join(root, "tasks", "animal-behavior", id);
  const record = `reports/mouse-closeout-20261026/${id}-cli-acceptance.json`;
  mkdirSync(dir, { recursive: true });
  mkdirSync(dirname(join(root, record)), { recursive: true });
  for (const file of ["task.yaml", "contract.json", "data.lock", "evaluator.lock"])
    copyFileSync(join(repo, "tasks", "animal-behavior", id, file), join(dir, file));
  const deliveryPath = join(repo, "tasks", "animal-behavior", id, "hf-delivery.json");
  if (existsSync(deliveryPath)) {
    copyFileSync(deliveryPath, join(dir, "hf-delivery.json"));
    const delivery = JSON.parse(readFileSync(deliveryPath, "utf8"));
    mkdirSync(dirname(join(root, delivery.publication_receipt)), { recursive: true });
    copyFileSync(join(repo, delivery.publication_receipt), join(root, delivery.publication_receipt));
  }
  copyFileSync(join(repo, record), join(root, record));
  const report = JSON.parse(readFileSync(join(root, record), "utf8"));
  const task = { dir, meta: { id, domain: "animal-behavior", version: "0.1-source" } };
  const save = value => writeFileSync(join(root, record), JSON.stringify(value));
  try { run({ root, dir, record, report, task, save }); }
  finally { rmSync(root, { recursive: true, force: true }); }
}

test("all five frozen acceptance records bind current task metadata", () => {
  for (const id of ids) fixture(id, f => {
    const accepted = readMouseAcceptance(f.root, f.task);
    assert.equal(accepted.report.task_id, id);
    assert.equal(accepted.privateOnly, id === ids[2] || id === ids[4]);
  });
});

test("unreviewed tasks and overstated receipt claims are rejected", () => fixture(ids[0], f => {
  assert.equal(readMouseAcceptance(f.root, { meta: { domain: "eeg" } }), null);
  assert.throws(() => readMouseAcceptance(f.root, { meta: { domain: "animal-behavior", id: "unreviewed" } }), /reviewed acceptance/);
  for (const change of [{ task_version: "different" }, { private_interface_passed: false },
    { private_metrics_published: true }, { data_uploaded: true }, { source_only: false },
    { kind: "agent_benchmark" }, { public_score_executed: false }, { image_id: "latest" },
    { private_result_sha256: "unknown" }]) {
    f.save({ ...f.report, ...change });
    assert.throws(() => readMouseAcceptance(f.root, f.task), /invalid or overstated/);
  }
}));

test("missing, failed and duplicate acceptance steps are rejected", () => fixture(ids[0], f => {
  const steps = f.report.steps;
  for (const changed of [steps.filter(s => s.step !== "score-private"),
    steps.map((s, i) => i ? s : { ...s, ok: false, exit_code: 1 }), [...steps, steps[0]]]) {
    f.save({ ...f.report, steps: changed });
    assert.throws(() => readMouseAcceptance(f.root, f.task), /incomplete CLI acceptance/);
  }
}));

test("changed task bindings and linked evidence fail closed", () => fixture(ids[0], f => {
  const file = join(f.dir, "contract.json");
  const original = readFileSync(file);
  writeFileSync(file, Buffer.concat([original, Buffer.from("\n")]));
  assert.throws(() => readMouseAcceptance(f.root, f.task), /stale accepted|scientific contract/);
  writeFileSync(file, original);
  const evidence = join(f.root, f.record);
  const target = join(f.root, "receipt-copy.json");
  copyFileSync(evidence, target);
  rmSync(evidence);
  symlinkSync(target, evidence);
  assert.throws(() => readMouseAcceptance(f.root, f.task), /ordinary independent/);
}));
