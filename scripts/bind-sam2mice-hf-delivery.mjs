#!/usr/bin/env node
/** Bind verified tracking transport without changing the scientific protocol. */
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { TRACKING_BINDINGS } from "./sam2mice-tracking-acceptance.mjs";
import { evidenceBytes, hostedTaskBytes, jsonBytes, readTrackingDelivery, readTrackingPublication,
  readTransportCodeReview, sha256, sourceTaskBytes, TRACKING_ACCEPTANCE, TRACKING_DIR, TRACKING_ID,
  trackingHostedLocks } from "./sam2mice-hf-delivery.mjs";

export function buildTrackingHFBindings(root, receiptPath) {
  const acceptanceBytes = evidenceBytes(join(root, TRACKING_ACCEPTANCE));
  const acceptance = JSON.parse(acceptanceBytes);
  const codeReview = readTransportCodeReview(root, acceptance);
  if (!codeReview) throw new Error("review the tracking transport code before binding");
  if (JSON.stringify(Object.keys(acceptance.bindings ?? {}).sort()) !== JSON.stringify(TRACKING_BINDINGS))
    throw new Error("tracking historical acceptance bindings differ");
  for (const path of TRACKING_BINDINGS) {
    if (["data.lock", "evaluator.lock", "task.yaml"].some(name => path === `${TRACKING_DIR}/${name}`)) continue;
    const expected = codeReview.review.changes[path]?.current_sha256 ?? acceptance.bindings[path];
    if (sha256(evidenceBytes(join(root, path))) !== expected) throw new Error(`unreviewed tracking code or science change: ${path}`);
  }
  const publication = readTrackingPublication(root, receiptPath);
  const dir = join(root, TRACKING_DIR);
  const contractBytes = evidenceBytes(join(dir, "contract.json"));
  const contract = JSON.parse(contractBytes);
  if (publication.receipt.acceptance_sha256 !== sha256(acceptanceBytes) ||
      publication.receipt.contract_sha256 !== sha256(contractBytes) ||
      sha256(contractBytes) !== acceptance.bindings[`${TRACKING_DIR}/contract.json`])
    throw new Error("tracking publication does not bind the accepted scientific contract");
  if (existsSync(join(dir, "hf-delivery.json")))
    readTrackingDelivery(root, { meta: { id: TRACKING_ID } }, acceptance, codeReview);
  const { source, hosted, destinations } = trackingHostedLocks(contract, publication.receipt);
  const outputs = new Map();
  const sourceBindings = Object.fromEntries(["contract.json", "task.yaml", "data.lock", "evaluator.lock"]
    .map(name => [name, acceptance.bindings[`${TRACKING_DIR}/${name}`]]));
  for (const name of ["data.lock", "evaluator.lock"]) {
    const sourceBytes = jsonBytes(source[name]), hostedBytes = jsonBytes(hosted[name]);
    if (sha256(sourceBytes) !== sourceBindings[name]) throw new Error("tracking source lock cannot be reconstructed");
    const actual = evidenceBytes(join(dir, name));
    // An interrupted local write can contain these exact verified destination bytes.
    if (!actual.equals(sourceBytes) && !actual.equals(hostedBytes)) throw new Error("tracking current lock has unreviewed changes");
    outputs.set(join(dir, name), hostedBytes);
  }
  const originalTask = sourceTaskBytes(evidenceBytes(join(dir, "task.yaml")), sourceBindings["task.yaml"]);
  outputs.set(join(dir, "task.yaml"), hostedTaskBytes(originalTask));
  outputs.set(join(dir, "hf-delivery.json"), jsonBytes({
    schema: "bpb-mouse-hf-delivery/1", task_id: TRACKING_ID, content_revision: contract.revision,
    transport_only: true, source_bindings: sourceBindings,
    hosted_bindings: Object.fromEntries([...outputs].map(([path, value]) => [path.slice(dir.length + 1), sha256(value)])),
    ...destinations, publication_receipt: receiptPath, publication_receipt_sha256: publication.sha256,
    transport_code_review: codeReview.record, transport_code_review_sha256: codeReview.sha256,
    scope: "Exact accepted scientific bytes at pinned public and private repositories. Only task availability metadata changes.",
  }));
  return outputs;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const args = process.argv.slice(2), index = args.indexOf("--receipt");
  if (index < 0 || !args[index + 1]) throw new Error("--receipt reports/<verified-publication>.json is required");
  const outputs = buildTrackingHFBindings(root, args[index + 1]);
  if (args.includes("--write")) {
    const originals = new Map([...outputs.keys()].map(path => [path, existsSync(path) ? readFileSync(path) : null]));
    for (const [path, value] of outputs) {
      const current = existsSync(path) ? evidenceBytes(path) : null;
      const original = originals.get(path);
      if ((current === null) !== (original === null) || (current && !current.equals(original)))
        throw new Error("tracking binding changed concurrently");
      const temporary = path + ".transport-write-tmp";
      writeFileSync(temporary, value, { flag: "wx", mode: 0o644 });
      renameSync(temporary, path);
    }
  }
  console.log(JSON.stringify({ written: args.includes("--write"), paths: [...outputs.keys()].map(path => relative(root, path)) }));
}
