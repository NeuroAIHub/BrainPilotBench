#!/usr/bin/env node
/** Bind fresh public delivery evidence without rewriting scientific acceptance. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";
import { priorAcceptanceSha256, requiredInvasiveBindings, validatePublicPreviewMapping, validateUnifiedDeliveryReport } from "./invasive-acceptance.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const value = flag => {
  const at = args.indexOf(flag);
  if (at < 0 || !args[at + 1] || args[at + 1].startsWith("--"))
    throw new Error(`Pass ${flag} with a value`);
  return args[at + 1];
};
const revision = value("--revision");
const reportPath = value("--report");
const apply = args.includes("--apply");
if (!/^[0-9a-f]{40}$/.test(revision)) throw new Error("Revision must be the actual published 40-hex commit");
if (!/^(?:tasks|reports)\/[A-Za-z0-9._/-]+\.json$/.test(reportPath) ||
    reportPath.split("/").some(part => part === "." || part === ".."))
  throw new Error("Report must be a safe repo-relative tasks/ or reports/ JSON path");
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const bytesFor = file => {
  let current = root;
  for (const part of file.split("/")) {
    current = join(current, part);
    if (lstatSync(current).isSymbolicLink()) throw new Error(`Linked file: ${file}`);
  }
  if (!lstatSync(current).isFile()) throw new Error(`Missing regular file: ${file}`);
  return readFileSync(current);
};
const reportBytes = bytesFor(reportPath);
validateUnifiedDeliveryReport(JSON.parse(reportBytes), revision);
const bridgeFiles = ["src/data/types.ts", "src/data/manifest.ts", "src/workflow.ts", "src/cli.ts",
  "src/data/cache.ts", "src/data/fetch.ts", "src/data/resolve.ts"];
const bridge_file_sha256 = Object.fromEntries(bridgeFiles.map(file => [file, hash(bytesFor(file))]));
const previewBytes = readFileSync(join(root, ".cache/hf-unified-audit-20261015/migration-preview.json"));
if (hash(previewBytes) !== "bc98f67db0f3d2e09b2fdce373a638ae816f886c9fc5103b6156204f314ae1b6")
  throw new Error("Audited migration preview SHA-256 changed; stop before writing delivery receipts");
const preview = JSON.parse(previewBytes);
const ids = ["ieeg-finger-flexion-bciciv4", "falcon-h2-handwriting", "falcon-m1-emg",
  "falcon-m2-finger-velocity", "falcon-b1-birdsong", "ieeg-film-speech-music"];
const pending = [];
for (const id of ids) {
  const card = preview.tasks.find(task => task.task_id === id);
  if (!card) throw new Error(`Preview lacks ${id}`);
  const dir = join(root, card.source_code_directory);
  const prefix = relative(root, dir).split(sep).join("/");
  const acceptancePath = `${prefix}/acceptance.json`;
  const acceptanceBytes = bytesFor(acceptancePath);
  if (hash(acceptanceBytes) !== priorAcceptanceSha256[id])
    throw new Error(`${id}: original scientific acceptance record changed`);
  const record = JSON.parse(acceptanceBytes);
  if (record.schema !== "bpb-local-task-acceptance/1" || record.task_id !== id ||
      record.task_version !== card.task_version || record.status !== "passed")
    throw new Error(`${id}: prior scientific acceptance is invalid`);
  const allowed = [`${prefix}/data.lock`, `${prefix}/env/setup.sh`];
  for (const file of requiredInvasiveBindings(root, dir))
    if (!record.file_sha256?.[file]) throw new Error(`${id}: original acceptance lacks ${file}`);
  for (const [file, expected] of Object.entries(record.file_sha256)) {
    const actual = hash(bytesFor(file));
    if (actual !== expected && !allowed.includes(file))
      throw new Error(`${id}: scientific binding changed: ${file}`);
  }
  const old_file_sha256 = Object.fromEntries(allowed.map(file => [file, record.file_sha256[file]]));
  const new_file_sha256 = Object.fromEntries(allowed.map(file => [file, hash(bytesFor(file))]));
  if (allowed.some(file => old_file_sha256[file] === new_file_sha256[file]))
    throw new Error(`${id}: expected both delivery files to change`);
  const lock = YAML.parse(bytesFor(`${prefix}/data.lock`).toString("utf8"));
  const publicEntries = lock.datasets?.filter(entry => entry.scope === "public") ?? [];
  const planned = preview.operations_preview.filter(op => op.task_id === id);
  validatePublicPreviewMapping(id, publicEntries, planned, revision);
  const receipt = {
    schema: "bpb-unified-public-delivery/1", status: "passed", task_id: id,
    task_version: card.task_version, published_revision: revision,
    prior_acceptance_sha256: hash(acceptanceBytes), old_file_sha256, new_file_sha256,
    bridge_file_sha256,
    verification_report: { path: reportPath, sha256: hash(reportBytes) },
  };
  const destination = join(dir, "delivery-acceptance.json");
  const content = JSON.stringify(receipt, null, 2) + "\n";
  if (existsSync(destination) && readFileSync(destination, "utf8") !== content)
    throw new Error(`${id}: existing delivery receipt differs; reconcile before rewriting`);
  pending.push([destination, content]);
}
if (apply) for (const [destination, content] of pending) writeFileSync(destination, content);
console.log(JSON.stringify({ mode: apply ? "applied" : "dry_run", published_revision: revision,
  report: reportPath, receipts: pending.map(([path]) => relative(root, path)) }, null, 2));
