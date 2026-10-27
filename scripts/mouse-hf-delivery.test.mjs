import test from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildMouseHFBindings } from "./bind-mouse-hf-delivery.mjs";
import { readMouseAcceptance } from "./mouse-acceptance.mjs";
import { MOUSE_TASK_IDS, MOUSE_REPOS, jsonBytes, mouseSourceLocks, remotePath, sha256 } from "./mouse-hf-delivery.mjs";

const repo = fileURLToPath(new URL("..", import.meta.url));
function fixture(run) {
  const root = mkdtempSync(join(tmpdir(), "bpb-mouse-delivery-"));
  const receiptPath = "reports/mouse-hf-delivery-fixture/publication.json";
  const receipt = { schema: "bpb-mouse-hf-publication/1", status: "verified" };
  for (const role of ["public", "private"])
    receipt[role] = { repo_id: MOUSE_REPOS[role], revision: (role === "public" ? "a" : "b").repeat(40),
      private: role === "private", old_data_unchanged: true, files: [] };
  const tasks = new Map();
  for (const id of MOUSE_TASK_IDS) {
    const dir = join(root, "tasks", "animal-behavior", id);
    mkdirSync(dir, { recursive: true });
    for (const file of ["task.yaml", "contract.json", "data.lock", "evaluator.lock"])
      copyFileSync(join(repo, "tasks", "animal-behavior", id, file), join(dir, file));
    const report = `reports/mouse-closeout-20261026/${id}-cli-acceptance.json`;
    mkdirSync(dirname(join(root, report)), { recursive: true });
    copyFileSync(join(repo, report), join(root, report));
    tasks.set(id, { dir, meta: { id, domain: "animal-behavior", version: "0.1-source" } });
    const contract = JSON.parse(readFileSync(join(dir, "contract.json")));
    for (const [name, content] of Object.entries(mouseSourceLocks(contract)))
      writeFileSync(join(dir, name), jsonBytes(content));
    for (const [role, key] of [["public", "public_files"], ["private", "owner_files"]])
      receipt[role].files.push(...contract[key].map(row => ({ task_id: id, native_path: row.path,
        path: remotePath(id, role, row.path), sha256: row.sha256, bytes: row.bytes })));
  }
  mkdirSync(dirname(join(root, receiptPath)), { recursive: true });
  const save = () => writeFileSync(join(root, receiptPath), jsonBytes(receipt));
  save();
  const bind = () => { for (const [path, content] of buildMouseHFBindings(root, receiptPath)) writeFileSync(path, content); };
  try { run({ root, tasks, receipt, receiptPath, save, bind }); }
  finally { rmSync(root, { recursive: true, force: true }); }
}

test("all five mirrors preserve historical acceptance and exact native content", () => fixture(f => {
  const old = new Map([...f.tasks].map(([id, task]) => [id, sha256(readFileSync(join(task.dir, "contract.json")))]));
  f.bind();
  for (const [id, task] of f.tasks) {
    const accepted = readMouseAcceptance(f.root, task);
    assert.equal(accepted.delivery.publicHosted, true);
    assert.equal(accepted.delivery.privateHosted, true);
    assert.equal(sha256(readFileSync(join(task.dir, "contract.json"))), old.get(id));
    const lock = JSON.parse(readFileSync(join(task.dir, "data.lock")));
    assert.ok(lock.datasets.every(row => row.uri.startsWith("hf://datasets/BrainPilot-Bench/Tasks-Data-")));
    assert.ok(lock.datasets.filter(row => row.scope === "public").every(row => !row.uri.includes("/public/public/")));
  }
  f.bind(); // Idempotent exact verification, not another publication.
}));

test("public-only mirrors keep private source transport and scientific acceptance", () => fixture(f => {
  f.receipt.private = null;
  f.save(); f.bind();
  for (const task of f.tasks.values()) {
    const accepted = readMouseAcceptance(f.root, task);
    assert.equal(accepted.delivery.publicHosted, true);
    assert.equal(accepted.delivery.privateHosted, false);
    assert.equal(JSON.parse(readFileSync(join(task.dir, "evaluator.lock"))).schema, "bpb-evaluator-source/1");
  }
}));

test("partial publication, different bytes, and wrong targets cannot bind", () => fixture(f => {
  const original = structuredClone(f.receipt);
  for (const alter of [r => r.public.files.pop(), r => r.public.files[0].bytes++,
    r => r.private.files[0].path = r.private.files[0].path.replace("/evaluator/", "/public/"),
    r => r.private.files.push(r.private.files[0]), r => r.public.revision = "main",
    r => r.private.private = false, r => r.public.old_data_unchanged = false,
    r => r.status = "uploaded_unverified"]) {
    Object.assign(f.receipt, structuredClone(original)); alter(f.receipt); f.save();
    assert.throws(() => buildMouseHFBindings(f.root, f.receiptPath));
  }
}));

test("changed receipt, data bytes, scientific contract, and source bindings fail", () => fixture(f => {
  f.bind();
  const task = f.tasks.values().next().value;
  const contract = join(task.dir, "contract.json"), original = readFileSync(contract);
  writeFileSync(contract, Buffer.concat([original, Buffer.from("\n")]));
  assert.throws(() => readMouseAcceptance(f.root, task), /scientific contract/);
  writeFileSync(contract, original);
  const lockPath = join(task.dir, "data.lock"), lockBytes = readFileSync(lockPath);
  const data = JSON.parse(lockBytes); data.datasets[0].bytes++;
  writeFileSync(lockPath, jsonBytes(data));
  assert.throws(() => readMouseAcceptance(f.root, task), /hosted lock differs/);
  writeFileSync(lockPath, lockBytes);
  f.receipt.public.files[0].sha256 = "0".repeat(64); f.save();
  assert.throws(() => readMouseAcceptance(f.root, task), /receipt SHA mismatch/);
}));
