import test from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildTrackingHFBindings } from "./bind-sam2mice-hf-delivery.mjs";
import { readTrackingAcceptance, TRACKING_BINDINGS } from "./sam2mice-tracking-acceptance.mjs";
import { jsonBytes, sha256, sourceTaskBytes, TRACKING_ACCEPTANCE, TRACKING_DIR, TRACKING_ID,
  TRACKING_REPOS, TRANSPORT_CHANGES, TRANSPORT_CODE_REVIEW, TRANSPORT_DEPENDENCIES,
  trackingRemotePath, trackingSourceLocks } from "./sam2mice-hf-delivery.mjs";

const repo = fileURLToPath(new URL("..", import.meta.url));
function fixture(run) {
  const root = mkdtempSync(join(realpathSync(tmpdir()), "bpb-tracking-delivery-"));
  const dir = join(root, TRACKING_DIR);
  const acceptance = JSON.parse(readFileSync(join(repo, TRACKING_ACCEPTANCE)));
  for (const file of [...TRACKING_BINDINGS, ...TRANSPORT_DEPENDENCIES, TRACKING_ACCEPTANCE]) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    copyFileSync(join(repo, file), join(root, file));
  }
  writeFileSync(join(dir, "task.yaml"), sourceTaskBytes(readFileSync(join(dir, "task.yaml")), acceptance.bindings[`${TRACKING_DIR}/task.yaml`]));
  const contract = JSON.parse(readFileSync(join(dir, "contract.json")));
  for (const [name, content] of Object.entries(trackingSourceLocks(contract))) writeFileSync(join(dir, name), jsonBytes(content));
  const review = { schema: "bpb-sam2mice-transport-code-review/1", status: "reviewed", task_id: TRACKING_ID,
    transport_only: true, scientific_protocol_unchanged: true, no_model_rerun: true,
    source_acceptance_sha256: sha256(readFileSync(join(root, TRACKING_ACCEPTANCE))),
    changes: Object.fromEntries(TRANSPORT_CHANGES.map(path => [path, { source_sha256: acceptance.bindings[path],
      current_sha256: sha256(readFileSync(join(root, path))) }])),
    dependencies: Object.fromEntries(TRANSPORT_DEPENDENCIES.map(path => [path, sha256(readFileSync(join(root, path)))])),
    checks: { source_and_hosted_locks: "passed", materialize_only_preserves_hf_locks: "passed", evaluator_marker_revision: "passed" } };
  mkdirSync(dirname(join(root, TRANSPORT_CODE_REVIEW)), { recursive: true });
  const saveReview = () => writeFileSync(join(root, TRANSPORT_CODE_REVIEW), jsonBytes(review));
  saveReview();
  const receiptPath = "reports/sam2mice-hf-fixture/publication.json";
  const receipt = { schema: "bpb-sam2mice-hf-publication/1", status: "verified", task_id: TRACKING_ID,
    content_revision: contract.revision, contract_sha256: sha256(readFileSync(join(dir, "contract.json"))),
    acceptance_sha256: sha256(readFileSync(join(root, TRACKING_ACCEPTANCE))), anonymous_private_access_denied: true };
  for (const [role, key] of [["public", "public_files"], ["private", "owner_files"]]) {
    receipt[role] = { repo_id: TRACKING_REPOS[role], revision: (role === "public" ? "a" : "b").repeat(40),
      private: role === "private", status: "verified", all_remote_object_identities_checked: true,
      old_data_objects_unchanged: true, files: contract[key].map(row => ({ task_id: TRACKING_ID,
        native_path: row.path, path: trackingRemotePath(role, row.path), bytes: row.bytes, sha256: row.sha256 })) };
  }
  mkdirSync(dirname(join(root, receiptPath)), { recursive: true });
  const save = () => writeFileSync(join(root, receiptPath), jsonBytes(receipt));
  const bind = () => { for (const [path, value] of buildTrackingHFBindings(root, receiptPath)) writeFileSync(path, value); };
  const task = { dir, meta: { id: TRACKING_ID, version: "0.1", domain: "animal-behavior" } };
  save();
  try { run({ root, dir, task, contract, acceptance, review, saveReview, receiptPath, receipt, save, bind }); }
  finally { rmSync(root, { recursive: true, force: true }); }
}

test("reviewed transport code preserves source-only scientific acceptance", () => fixture(f => {
  const result = readTrackingAcceptance(f.root, f.task);
  assert.equal(result.delivery, null);
  assert.equal(result.transportCodeReview.review.status, "reviewed");
  f.review.status = "pending"; f.saveReview();
  assert.throws(() => readTrackingAcceptance(f.root, f.task), /unreviewed/);
}));

test("exact public and private mirrors preserve original receipt and science", () => fixture(f => {
  const oldAcceptance = readFileSync(join(f.root, TRACKING_ACCEPTANCE));
  const oldContract = readFileSync(join(f.dir, "contract.json"));
  f.bind();
  const result = readTrackingAcceptance(f.root, f.task);
  assert.equal(result.delivery.publicHosted, true);
  assert.equal(result.delivery.privateHosted, true);
  assert.deepEqual(readFileSync(join(f.root, TRACKING_ACCEPTANCE)), oldAcceptance);
  assert.deepEqual(readFileSync(join(f.dir, "contract.json")), oldContract);
  assert.match(readFileSync(join(f.dir, "task.yaml"), "utf8"), /data_availability: published-public-and-private-snapshots/);
  const lock = JSON.parse(readFileSync(join(f.dir, "data.lock")));
  assert.equal(lock.datasets.filter(row => row.scope === "public").length, 49);
  assert.equal(lock.datasets.filter(row => row.scope === "private").length, 13);
  assert.ok(lock.datasets.every(row => row.uri.startsWith(`hf://datasets/${TRACKING_REPOS[row.scope]}@`)));
  f.bind();
}));

test("partial, altered or exposed-private publication is rejected before binding", () => fixture(f => {
  const original = structuredClone(f.receipt);
  for (const change of [receipt => receipt.public.files.pop(), receipt => receipt.private.files.push(receipt.private.files[0]),
    receipt => receipt.public.files[0].bytes++, receipt => receipt.private.files[0].sha256 = "0".repeat(64),
    receipt => receipt.private.repo_id = TRACKING_REPOS.public,
    receipt => receipt.private.files[0].path = receipt.private.files[0].path.replace("/evaluator/", "/public/"),
    receipt => receipt.public.revision = "main", receipt => receipt.private.private = false,
    receipt => receipt.public.old_data_objects_unchanged = false,
    receipt => receipt.private.all_remote_object_identities_checked = false,
    receipt => receipt.anonymous_private_access_denied = false,
    receipt => receipt.status = "uploaded_unverified"]) {
    Object.assign(f.receipt, structuredClone(original)); change(f.receipt); f.save();
    assert.throws(() => buildTrackingHFBindings(f.root, f.receiptPath));
  }
}));

test("only the exact task availability line can change in hosted metadata", () => fixture(f => {
  f.bind();
  const file = join(f.dir, "task.yaml"), original = readFileSync(file, "utf8");
  for (const changed of [original.replace('version: "0.1"', 'version: "0.2"'),
    original.replace("id: mota", "id: idf1"), original + "# unreviewed edit\n"]) {
    writeFileSync(file, changed);
    assert.throws(() => readTrackingAcceptance(f.root, f.task), /metadata/);
  }
}));

test("code review cannot authorize arbitrary accepted files or hide hosted-binding changes", () => fixture(f => {
  const original = structuredClone(f.review);
  f.review.changes[`${TRACKING_DIR}/prompt/turns.yaml`] = { source_sha256: "a".repeat(64), current_sha256: "a".repeat(64) };
  f.saveReview();
  assert.throws(() => readTrackingAcceptance(f.root, f.task), /unreviewed/);
  Object.assign(f.review, original); f.saveReview();
  f.bind();
  const cardPath = join(f.dir, "hf-delivery.json"), card = JSON.parse(readFileSync(cardPath));
  card.hosted_bindings["prompt/turns.yaml"] = "0".repeat(64);
  writeFileSync(cardPath, jsonBytes(card));
  assert.throws(() => readTrackingAcceptance(f.root, f.task), /invalid tracking delivery bridge/);
}));

test("changed scientific code or publication receipt invalidates hosted acceptance", () => fixture(f => {
  f.bind();
  const file = join(f.root, "tasks/animal-behavior/_sam2mice_tracking/metrics.py");
  const original = readFileSync(file);
  writeFileSync(file, Buffer.concat([original, Buffer.from("\n# changed\n")]));
  assert.throws(() => readTrackingAcceptance(f.root, f.task), /stale tracking/);
  writeFileSync(file, original);
  f.receipt.public.files[0].bytes++; f.save();
  assert.throws(() => readTrackingAcceptance(f.root, f.task), /receipt SHA/);
}));
