#!/usr/bin/env node
/** Bind verified mouse mirrors; no network, scientific edits, or Test replay. */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { evidenceBytes, jsonBytes, MOUSE_TASK_IDS, mouseHostedLocks, readMouseDelivery, readMousePublication, sha256 } from "./mouse-hf-delivery.mjs";

export function buildMouseHFBindings(root, receiptPath) {
  const published = readMousePublication(root, receiptPath);
  const outputs = new Map();
  for (const id of MOUSE_TASK_IDS) {
    if (!["public", "private"].some(role => published.receipt[role]?.files.some(file => file.task_id === id))) continue;
    const dir = join(root, "tasks", "animal-behavior", id);
    const contract = JSON.parse(evidenceBytes(join(dir, "contract.json")));
    const accepted = JSON.parse(evidenceBytes(join(root, `reports/mouse-closeout-20261026/${id}-cli-acceptance.json`)));
    const { source, hosted, destinations } = mouseHostedLocks(contract, published.receipt);
    if (existsSync(join(dir, "hf-delivery.json"))) readMouseDelivery(root, { dir, meta: { id } }, accepted);
    for (const file of ["contract.json", "task.yaml"])
      if (sha256(evidenceBytes(join(dir, file))) !== accepted.bindings[file]) throw new Error(`${id}: changed scientific contract`);
    for (const file of ["data.lock", "evaluator.lock"]) {
      if (sha256(jsonBytes(source[file])) !== accepted.bindings[file]) throw new Error(`${id}: source lock reconstruction differs`);
      if (!existsSync(join(dir, "hf-delivery.json")) && sha256(evidenceBytes(join(dir, file))) !== accepted.bindings[file])
        throw new Error(`${id}: current source lock differs from acceptance`);
      outputs.set(join(dir, file), jsonBytes(hosted[file]));
    }
    outputs.set(join(dir, "hf-delivery.json"), jsonBytes({ schema: "bpb-mouse-hf-delivery/1", task_id: id,
      content_revision: contract.revision, transport_only: true, source_bindings: accepted.bindings,
      hosted_bindings: Object.fromEntries(Object.entries(hosted).map(([name, value]) => [name, sha256(jsonBytes(value))])),
      ...destinations, publication_receipt: receiptPath, publication_receipt_sha256: published.sha256,
      scope: "Transport-only mirror of accepted content; no model rerun or new Agent benchmark result" }));
  }
  return outputs;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const args = process.argv.slice(2), index = args.indexOf("--receipt");
  if (index < 0 || !args[index + 1]) throw new Error("--receipt reports/<verified-publication>.json is required");
  const outputs = buildMouseHFBindings(root, args[index + 1]);
  if (args.includes("--write")) for (const [path, content] of outputs) writeFileSync(path, content);
  console.log(JSON.stringify({ written: args.includes("--write"), paths: [...outputs.keys()].map(path => relative(root, path)) }));
}
