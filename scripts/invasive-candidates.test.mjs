import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, mkdtempSync, writeFileSync, mkdirSync, rmSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { discoverTaskDirs } from "../dist/discover.js";
import { readInvasiveCandidates, validateInvasiveCandidate, invasiveCatalogRow } from "./invasive-candidates.mjs";
import { loadTask } from "../dist/loader.js";
import { readInvasiveAcceptance, requiredInvasiveBindings, validatePublicPreviewMapping } from "./invasive-acceptance.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const expected = [
  "falcon-b1-birdsong", "falcon-h1-reach-grasp", "falcon-h2-handwriting",
  "falcon-m1-emg", "falcon-m2-finger-velocity", "ieeg-film-speech-music",
  "ieeg-finger-flexion-bciciv4",
].sort();

// These checks inspect real task metadata, not synthetic recording arrays.
test("all seven invasive entries have one explicit lifecycle state", () => {
  const entries = readInvasiveCandidates(root);
  const runnable = new Set(discoverTaskDirs([join(root, "tasks")]));
  const runnableIds = [...runnable].filter(dir => /\/tasks\/(ieeg|intracortical)\//.test(dir)).map(dir => loadTask(dir).meta.id);
  assert.deepEqual([...entries.map(entry => entry.card.id), ...runnableIds].sort(), expected);
  for (const entry of entries) {
    assert.equal(runnable.has(entry.dir), false);
    assert.equal(existsSync(join(entry.dir, "task.yaml")), false);
    assert.equal(entry.card.runnable, false);
  }
});

test("each promoted invasive entry has current version-bound acceptance, not Agent results", () => {
  const catalog = JSON.parse(readFileSync(join(root, "tasks/catalog.json"), "utf8"));
  for (const dir of discoverTaskDirs([join(root, "tasks")]).filter(dir => /\/tasks\/(ieeg|intracortical)\//.test(dir))) {
    const task = loadTask(dir);
    assert.equal(existsSync(join(dir, "candidate.json")), false);
    assert.ok(readInvasiveAcceptance(root, dir, task));
    const entry = catalog.tasks.find(row => row.task_id === task.meta.id);
    assert.equal(entry.entry_kind, "runnable");
    assert.equal(entry.task_version, task.meta.version);
    assert.equal(entry.evaluation_scope, "public_validation_only");
    assert.equal(entry.evaluation_profile, task.meta.evaluation.profile);
    assert.equal(entry.agent_benchmark_results, "not_available");
  }
});

test("catalog rows preserve candidate status and metric directions", () => {
  const catalog = JSON.parse(readFileSync(join(root, "tasks/catalog.json"), "utf8"));
  for (const entry of readInvasiveCandidates(root)) {
    assert.deepEqual(catalog.tasks.find(row => row.task_id === entry.card.id), invasiveCatalogRow(entry));
  }
});

test("FALCON acceptance includes shared source verification dependencies", () => {
  for (const id of expected.filter(id => id.startsWith("falcon-"))) {
    const files = new Set(requiredInvasiveBindings(root, join(root, "tasks/intracortical", id)));
    for (const file of ["_preparation/prepare.py", "_preparation/check_manifest.py", "_preparation/make_manifest.py",
      "_preparation/requirements.txt", "_shared/native.py"]) {
      assert.ok(files.has(`tasks/intracortical/${file}`), `${id} must bind ${file}`);
    }
  }
});

test("candidate validation rejects identity and lifecycle changes", () => {
  const entry = historicalCandidate();
  const context = { ...entry, name: entry.card.id, root };
  for (const change of [
    { id: "different-task" }, { domain: "eeg" }, { schema: "unknown" },
    { status: "runnable" }, { runnable: true }, { runnable: "false" }, { runnable: undefined },
    { validated: true }, { validated: "false" },
    { primary_metric: { id: "r2", direction: "sideways" } }, { reason: "" },
  ]) assert.throws(() => validateInvasiveCandidate({ ...entry.card, ...change }, context));
});

test("preparation entry must stay inside its task domain", () => {
  const entry = historicalCandidate();
  const context = { ...entry, name: entry.card.id, root };
  for (const path of ["/tmp/prepare.py", "../prepare.py", "scripts/refresh-collection.mjs", ""]) {
    assert.throws(() => validateInvasiveCandidate({ ...entry.card,
      status: "preparation_ready_data_pending", preparation_entry: path }, context));
  }
});

test("engineering evidence rejects changed files and inflated lifecycle claims", () => {
  const temporary = mkdtempSync(join(tmpdir(), "bpb-evidence-metadata-"));
  const taskRelative = "tasks/ieeg/metadata-fixture";
  const dir = join(temporary, taskRelative);
  for (const subdir of ["checks", "env", "prompt"]) mkdirSync(join(dir, subdir), { recursive: true });
  const files = {};
  for (const name of ["task.yaml", "contract.json", "data.lock", "protocol.json", "prompt/turns.yaml",
    "checks/check.sh", "checks/score.py", "checks/worker.py", "env/prepare.py", "env/requirements.txt"]) {
    const bytes = `metadata fixture for ${name}\n`;
    writeFileSync(join(dir, name), bytes);
    files[`${taskRelative}/${name}`] = createHash("sha256").update(bytes).digest("hex");
  }
  const record = {
    schema: "bpb-local-task-acceptance/1", task_id: "metadata-fixture", task_version: "0.1",
    status: "passed", agent_benchmark_run: false, source_task_id: "unit-check", source_verification: "metadata-only-fixture",
    public_validation: { status: "passed", metric_id: "example", value: 0, profile: "unit-profile", cli_report_sha256: "1".repeat(64) },
    owner_test: { status: "fixed_reference_interface_passed", model_tuned: false, report_sha256: "2".repeat(64),
      frozen_artifact_receipt_sha256: "3".repeat(64), scores_published_as_agent_results: false },
    reference_artifact_sha256: { "config.json": "4".repeat(64), "model.py": "5".repeat(64), "weights.safetensors": "6".repeat(64) },
    checks: ["cli_submission_and_isolated_scoring"], file_sha256: files,
  };
  const task = { meta: { id: "metadata-fixture", version: "0.1", evaluation: { primaryMetric: { id: "example" }, profile: "unit-profile" } } };
  const write = value => writeFileSync(join(dir, "acceptance.json"), JSON.stringify(value));
  try {
    write(record);
    assert.ok(readInvasiveAcceptance(temporary, dir, task));
    for (const change of [{ agent_benchmark_run: true }, { task_version: "0.2" }, { status: "pending" },
      { owner_test: { status: "fixed_reference_interface_passed", model_tuned: true } }]) {
      write({ ...record, ...change });
      assert.throws(() => readInvasiveAcceptance(temporary, dir, task));
    }
    for (const name of ["checks/score.py", "checks/worker.py", "env/prepare.py", "env/requirements.txt"]) {
      const incomplete = { ...files };
      delete incomplete[`${taskRelative}/${name}`];
      write({ ...record, file_sha256: incomplete });
      assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /missing/);
    }
    write({ ...record, public_validation: { ...record.public_validation, profile: "wrong" } });
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /invalid/);
    write({ ...record, owner_test: { ...record.owner_test, report_sha256: undefined } });
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /invalid/);
    write(record);
    writeFileSync(join(dir, "contract.json"), "changed metadata\n");
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /stale/);
  } finally { rmSync(temporary, { recursive: true, force: true }); }
});

test("delivery receipt permits only pinned public lock and setup changes", () => {
  const temporary = mkdtempSync(join(tmpdir(), "bpb-delivery-evidence-"));
  const taskRelative = "tasks/ieeg/metadata-fixture";
  const dir = join(temporary, taskRelative);
  const digest = value => createHash("sha256").update(value).digest("hex");
  const put = (path, value) => {
    const full = join(temporary, path);
    mkdirSync(dirname(full), { recursive: true });
    writeFileSync(full, value);
    return digest(value);
  };
  const bound = {};
  for (const name of ["task.yaml", "contract.json", "data.lock", "protocol.json", "prompt/turns.yaml",
    "checks/check.sh", "env/setup.sh"]) {
    const file = `${taskRelative}/${name}`;
    bound[file] = put(file, `original ${name}\n`);
  }
  const acceptance = {
    schema: "bpb-local-task-acceptance/1", task_id: "metadata-fixture", task_version: "0.1",
    status: "passed", agent_benchmark_run: false, source_task_id: "unit-check", source_verification: "fixture",
    public_validation: { status: "passed", metric_id: "example", value: 0, profile: "unit-profile",
      cli_report_sha256: "1".repeat(64) },
    owner_test: { status: "fixed_reference_interface_passed", model_tuned: false,
      report_sha256: "2".repeat(64), frozen_artifact_receipt_sha256: "3".repeat(64),
      scores_published_as_agent_results: false },
    reference_artifact_sha256: { "config.json": "4".repeat(64), "model.py": "5".repeat(64),
      "weights.safetensors": "6".repeat(64) },
    checks: ["cli_submission_and_isolated_scoring"], file_sha256: bound,
  };
  const revision = "a".repeat(40);
  const target = "tasks/invasive/metadata-fixture/public/train/manifest.json";
  const task = { meta: { id: "metadata-fixture", version: "0.1",
    evaluation: { primaryMetric: { id: "example" }, profile: "unit-profile" } },
    datasets: [{ name: "manifest.json", scope: "public", path: "train/manifest.json",
      uri: `hf://datasets/BrainPilot-Bench/Tasks-Data-Public@${revision}/${target}` },
      { name: "private.dat", scope: "private", uri: "local://private.dat" }] };
  const acceptanceText = JSON.stringify(acceptance);
  const acceptancePath = `${taskRelative}/acceptance.json`;
  const lockFile = `${taskRelative}/data.lock`;
  const setupFile = `${taskRelative}/env/setup.sh`;
  const reportPath = "reports/unified-public-verification.json";
  const report = {
    schema: "bpb-unified-public-verification/1", published_revision: revision,
    metadata: { scope: "all", tasks: 112, hosted_tasks: 111, source_only_tasks: 1, public_files: 668 },
    downloads: { scope: "representative", verified_targets: [target] },
    setup: { public_output_checks: Object.fromEntries([
      "ieeg-finger-flexion-bciciv4", "falcon-h2-handwriting", "falcon-m1-emg",
      "falcon-m2-finger-velocity", "falcon-b1-birdsong", "ieeg-film-speech-music",
    ].map(id => [id, { passed: true, manifest_hash_verified: true }])) },
    owner_test_run: false,
  };
  try {
    put(acceptancePath, acceptanceText);
    const newHashes = { [lockFile]: put(lockFile, "new public lock\n"),
      [setupFile]: put(setupFile, "new public setup\n") };
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /missing fresh delivery/);
    const bridge = {};
    for (const file of ["src/data/types.ts", "src/data/manifest.ts", "src/workflow.ts", "src/cli.ts"])
      bridge[file] = put(file, `bridge ${file}\n`);
    const reportHash = put(reportPath, JSON.stringify(report));
    const delivery = {
      schema: "bpb-unified-public-delivery/1", status: "passed", task_id: "metadata-fixture",
      task_version: "0.1", published_revision: revision, prior_acceptance_sha256: digest(acceptanceText),
      old_file_sha256: { [lockFile]: bound[lockFile], [setupFile]: bound[setupFile] },
      new_file_sha256: newHashes, bridge_file_sha256: bridge,
      verification_report: { path: reportPath, sha256: reportHash },
    };
    const writeDelivery = value => put(`${taskRelative}/delivery-acceptance.json`, JSON.stringify(value));
    writeDelivery(delivery);
    assert.ok(readInvasiveAcceptance(temporary, dir, task));
    put(`${taskRelative}/contract.json`, "changed scientific contract\n");
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /stale/);
    put(`${taskRelative}/contract.json`, "original contract.json\n");
    put(acceptancePath, JSON.stringify({ ...acceptance, note: "changed" }));
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /invalid delivery/);
    put(acceptancePath, acceptanceText);
    rmSync(join(temporary, reportPath));
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task));
    put(reportPath, JSON.stringify(report));
    put(reportPath, JSON.stringify({ ...report, owner_test_run: true }));
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /stale verification report/);
    put(reportPath, JSON.stringify(report));
    put(setupFile, "changed again\n");
    assert.throws(() => readInvasiveAcceptance(temporary, dir, task), /stale or incorrect delivery hash/);
  } finally { rmSync(temporary, { recursive: true, force: true }); }
});

test("delivery mapping rejects a duplicate public file that omits another", () => {
  const revision = "a".repeat(40);
  const id = "falcon-m1-emg";
  const prefix = `tasks/invasive/${id}/public/`;
  const planned = [
    { target: `${prefix}train/x.npy`, sha256: "1".repeat(64), bytes: 1 },
    { target: `${prefix}valid/x.npy`, sha256: "2".repeat(64), bytes: 2 },
  ];
  const entries = planned.map(op => ({ path: op.target.slice(prefix.length),
    uri: `hf://datasets/BrainPilot-Bench/Tasks-Data-Public@${revision}/${op.target}`,
    sha256: op.sha256, bytes: op.bytes }));
  assert.doesNotThrow(() => validatePublicPreviewMapping(id, entries, planned, revision));
  assert.throws(() => validatePublicPreviewMapping(id, [entries[0], entries[0]], planned, revision), /differs/);
});

// Preserve candidate validation coverage after every invasive candidate is promoted.
function historicalCandidate() {
  const available = readInvasiveCandidates(root)[0];
  if (available) return available;
  const original = join(root, "tasks/intracortical/falcon-h1-reach-grasp");
  const dir = mkdtempSync(join(tmpdir(), "bpb-candidate-metadata-"));
  const card = JSON.parse(readFileSync(join(original, "preparation-history.json"), "utf8"));
  for (const name of ["README.md", "protocol.json"]) writeFileSync(join(dir, name), readFileSync(join(original, name)));
  // Every test passes invalid metadata before reaching any preparation entry I/O.
  process.once("exit", () => rmSync(dir, { recursive: true, force: true }));
  return { card, domain: "intracortical", dir, relDir: `tasks/intracortical/${card.id}` };
}
