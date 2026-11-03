/** Verify a transport-only mirror against the original tracking acceptance. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

export const TRACKING_ID = "sam2mice-multi-animal-tracking";
export const TRACKING_DIR = `tasks/animal-behavior/${TRACKING_ID}`;
export const TRACKING_ACCEPTANCE = "reports/sam2mice-tracking-20261103/acceptance.json";
export const TRANSPORT_CODE_REVIEW = "reports/sam2mice-hf-20261103/transport-code-review.json";
export const TRANSPORT_CHANGES = [
  "tasks/animal-behavior/_sam2mice_tracking/package_task.py",
  "tasks/animal-behavior/_sam2mice_tracking/task_common.py",
];
export const TRANSPORT_DEPENDENCIES = ["tasks/animal-behavior/_sam2mice_tracking/sam2mice_transport.py"];
export const TRACKING_REPOS = { public: "BrainPilot-Bench/Tasks-Data-Public", private: "BrainPilot-Bench/Tasks-Data-Private" };
export const sha256 = value => createHash("sha256").update(value).digest("hex");
const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
export const jsonBytes = value => Buffer.from(JSON.stringify(sorted(value), null, 2) + "\n");
const equal = (first, second) => JSON.stringify(sorted(first)) === JSON.stringify(sorted(second));
const hex = (value, length = 64) => typeof value === "string" && new RegExp(`^[a-f0-9]{${length}}$`).test(value);
const SOURCE_AVAILABILITY = "data_availability: source-verified-local-only\n";
const HOSTED_AVAILABILITY = "data_availability: published-public-and-private-snapshots\n";

export function sourceTaskBytes(actual, sourceSha) {
  if (sha256(actual) === sourceSha) return actual;
  const text = actual.toString("utf8");
  if (text.split(HOSTED_AVAILABILITY).length !== 2 || text.includes(SOURCE_AVAILABILITY))
    throw new Error("tracking task metadata changed beyond the transport availability field");
  const source = Buffer.from(text.replace(HOSTED_AVAILABILITY, SOURCE_AVAILABILITY));
  if (sha256(source) !== sourceSha) throw new Error("tracking source task metadata cannot be reconstructed");
  return source;
}

export function hostedTaskBytes(source) {
  const text = source.toString("utf8");
  if (text.split(SOURCE_AVAILABILITY).length !== 2 || text.includes(HOSTED_AVAILABILITY))
    throw new Error("tracking source availability field is not exact");
  return Buffer.from(text.replace(SOURCE_AVAILABILITY, HOSTED_AVAILABILITY));
}

function safeRelative(value) {
  if (typeof value !== "string" || !value || value.split("/").some(part => !/^[A-Za-z0-9._-]+$/.test(part) || part === "." || part === ".."))
    throw new Error("unsafe tracking delivery path");
  return value;
}

export function evidenceBytes(path) {
  for (let cursor = path; ; cursor = dirname(cursor)) {
    const info = lstatSync(cursor);
    if (info.isSymbolicLink() || (cursor === path ? !info.isFile() || info.nlink !== 1 : !info.isDirectory()))
      throw new Error("tracking delivery requires ordinary independent evidence");
    if (dirname(cursor) === cursor) break;
  }
  if (lstatSync(path).size > 4_000_000) throw new Error("tracking delivery metadata exceeds bound");
  return readFileSync(path);
}

export function trackingRemotePath(role, nativePath) {
  safeRelative(nativePath);
  if (!["public", "private"].includes(role)) throw new Error("invalid tracking delivery role");
  return `${TRACKING_DIR}/${role === "public" ? "public" : "evaluator"}/${nativePath}`;
}

export function readTransportCodeReview(root, acceptance) {
  const file = join(root, TRANSPORT_CODE_REVIEW);
  if (!existsSync(file)) return null;
  const review = JSON.parse(evidenceBytes(file));
  if (review.schema !== "bpb-sam2mice-transport-code-review/1" || review.status !== "reviewed" ||
      review.task_id !== TRACKING_ID || review.transport_only !== true || review.scientific_protocol_unchanged !== true ||
      review.no_model_rerun !== true || review.source_acceptance_sha256 !== sha256(evidenceBytes(join(root, TRACKING_ACCEPTANCE))) ||
      !equal(Object.keys(review.changes ?? {}).sort(), TRANSPORT_CHANGES) ||
      !equal(Object.keys(review.dependencies ?? {}).sort(), TRANSPORT_DEPENDENCIES) ||
      review.checks?.source_and_hosted_locks !== "passed" || review.checks?.materialize_only_preserves_hf_locks !== "passed" ||
      review.checks?.evaluator_marker_revision !== "passed")
    throw new Error("unreviewed tracking transport code transition");
  for (const path of TRANSPORT_CHANGES) {
    const change = review.changes[path];
    if (!equal(Object.keys(change ?? {}).sort(), ["current_sha256", "source_sha256"]) ||
        change.source_sha256 !== acceptance.bindings[path] || !hex(change.current_sha256) ||
        change.current_sha256 !== sha256(evidenceBytes(join(root, path))))
      throw new Error(`tracking transport code differs from reviewed transition: ${path}`);
  }
  for (const path of TRANSPORT_DEPENDENCIES)
    if (!hex(review.dependencies[path]) || review.dependencies[path] !== sha256(evidenceBytes(join(root, path))))
      throw new Error(`tracking transport dependency changed: ${path}`);
  return { review, record: TRANSPORT_CODE_REVIEW, sha256: sha256(evidenceBytes(file)) };
}

export function trackingSourceLocks(contract) {
  if (contract.task_id !== TRACKING_ID || !hex(contract.revision)) throw new Error("invalid tracking content identity");
  const datasets = [];
  for (const [role, key] of [["public", "public_files"], ["evaluator", "owner_files"]]) {
    if (!Array.isArray(contract[key]) || !contract[key].length) throw new Error("tracking role files missing");
    const paths = new Set();
    for (const row of contract[key]) {
      safeRelative(row.path);
      if (paths.has(row.path) || !hex(row.sha256) || !Number.isSafeInteger(row.bytes) || row.bytes <= 0)
        throw new Error("invalid tracking role file");
      paths.add(row.path);
      const entry = { name: role + "__" + row.path.replaceAll("/", "__"),
        uri: `local://${TRACKING_DIR}/${contract.revision}/${role}/${row.path}`,
        sha256: row.sha256, bytes: row.bytes, scope: role === "public" ? "public" : "private",
        format: row.path.endsWith(".json") ? "json" : "npz" };
      if (role === "public") entry.path = row.path;
      datasets.push(entry);
    }
  }
  return { "data.lock": { datasets }, "evaluator.lock": { schema: "bpb-evaluator-source/1", task_id: TRACKING_ID,
    repo_id: "local-prepared", revision: contract.revision,
    files: contract.owner_files.map(row => ({ name: "evaluator__" + row.path.replaceAll("/", "__"), ...row })) } };
}

export function readTrackingPublication(root, path, expectedSha) {
  safeRelative(path);
  if (!path.startsWith("reports/")) throw new Error("tracking publication evidence must be in reports");
  const bytes = evidenceBytes(join(root, path));
  if (expectedSha !== undefined && expectedSha !== sha256(bytes)) throw new Error("tracking publication receipt SHA differs");
  const receipt = JSON.parse(bytes);
  if (receipt.schema !== "bpb-sam2mice-hf-publication/1" || receipt.status !== "verified" ||
      receipt.task_id !== TRACKING_ID || !hex(receipt.content_revision) || !hex(receipt.contract_sha256) ||
      !hex(receipt.acceptance_sha256) || receipt.anonymous_private_access_denied !== true)
    throw new Error("tracking publication is incomplete or unverified");
  for (const role of ["public", "private"]) {
    const published = receipt[role];
    if (!published || published.repo_id !== TRACKING_REPOS[role] || !hex(published.revision, 40) ||
        published.private !== (role === "private") || published.status !== "verified" ||
        published.all_remote_object_identities_checked !== true || published.old_data_objects_unchanged !== true ||
        !Array.isArray(published.files) || !published.files.length)
      throw new Error("invalid tracking publication destination or verification");
    const paths = new Set();
    for (const row of published.files) {
      if (row.task_id !== TRACKING_ID || row.path !== trackingRemotePath(role, row.native_path) || paths.has(row.path) ||
          !hex(row.sha256) || !Number.isSafeInteger(row.bytes) || row.bytes <= 0)
        throw new Error("invalid tracking publication file");
      paths.add(row.path);
    }
  }
  return { receipt, path, sha256: sha256(bytes) };
}

export function trackingHostedLocks(contract, receipt) {
  if (receipt.content_revision !== contract.revision) throw new Error("tracking publication changes scientific content identity");
  const source = trackingSourceLocks(contract), hosted = structuredClone(source), destinations = {};
  for (const [role, key] of [["public", "public_files"], ["private", "owner_files"]]) {
    const published = receipt[role];
    if (published.files.length !== contract[key].length) throw new Error("partial tracking role publication");
    const byNative = new Map(published.files.map(row => [row.native_path, row]));
    if (byNative.size !== published.files.length) throw new Error("duplicate tracking native path");
    for (const expected of contract[key]) {
      const actual = byNative.get(expected.path);
      if (!actual || actual.path !== trackingRemotePath(role, expected.path) ||
          actual.bytes !== expected.bytes || actual.sha256 !== expected.sha256)
        throw new Error("tracking publication differs from exact scientific bytes");
    }
    destinations[role] = { repo_id: published.repo_id, revision: published.revision };
    for (const entry of hosted["data.lock"].datasets) {
      if (entry.scope !== role) continue;
      const packetRole = role === "public" ? "public" : "evaluator";
      const prefix = `local://${TRACKING_DIR}/${contract.revision}/${packetRole}/`;
      if (!entry.uri.startsWith(prefix)) throw new Error("unexpected source tracking URI");
      entry.uri = `hf://datasets/${published.repo_id}@${published.revision}/${trackingRemotePath(role, entry.uri.slice(prefix.length))}`;
    }
    if (role === "private") Object.assign(hosted["evaluator.lock"], {
      schema: "bpb-evaluator-data/1", repo_id: published.repo_id, revision: published.revision });
  }
  return { source, hosted, destinations };
}

export function readTrackingDelivery(root, candidate, acceptance, codeReview) {
  const dir = join(root, TRACKING_DIR), file = join(dir, "hf-delivery.json");
  if (!existsSync(file)) return null;
  if (!codeReview) throw new Error("tracking HF delivery requires a reviewed transport code transition");
  const card = JSON.parse(evidenceBytes(file));
  const contract = JSON.parse(evidenceBytes(join(dir, "contract.json")));
  if (candidate.meta.id !== TRACKING_ID || card.schema !== "bpb-mouse-hf-delivery/1" || card.task_id !== TRACKING_ID ||
      card.content_revision !== contract.revision || card.transport_only !== true ||
      card.transport_code_review !== codeReview.record || card.transport_code_review_sha256 !== codeReview.sha256 ||
      !equal(Object.keys(card.hosted_bindings ?? {}).sort(), ["data.lock", "evaluator.lock", "task.yaml"]) ||
      !hex(card.publication_receipt_sha256)) throw new Error("invalid tracking delivery bridge");
  const publication = readTrackingPublication(root, card.publication_receipt, card.publication_receipt_sha256);
  if (publication.receipt.contract_sha256 !== acceptance.bindings[`${TRACKING_DIR}/contract.json`] ||
      publication.receipt.acceptance_sha256 !== sha256(evidenceBytes(join(root, TRACKING_ACCEPTANCE))))
    throw new Error("tracking publication references different acceptance or contract");
  const { source, hosted, destinations } = trackingHostedLocks(contract, publication.receipt);
  const sourceBindings = Object.fromEntries(["contract.json", "task.yaml", "data.lock", "evaluator.lock"]
    .map(name => [name, acceptance.bindings[`${TRACKING_DIR}/${name}`]]));
  if (!equal(card.source_bindings, sourceBindings) || !equal(card.public, destinations.public) || !equal(card.private, destinations.private))
    throw new Error("tracking delivery changes accepted source bindings or destinations");
  if (sha256(evidenceBytes(join(dir, "contract.json"))) !== sourceBindings["contract.json"])
    throw new Error("tracking scientific contract changed");
  const actualTask = evidenceBytes(join(dir, "task.yaml"));
  const sourceTask = sourceTaskBytes(actualTask, sourceBindings["task.yaml"]);
  if (!actualTask.equals(hostedTaskBytes(sourceTask)) || sha256(actualTask) !== card.hosted_bindings?.["task.yaml"])
    throw new Error("tracking hosted task availability differs from its exact transition");
  for (const name of ["data.lock", "evaluator.lock"]) {
    if (sha256(jsonBytes(source[name])) !== sourceBindings[name]) throw new Error("tracking source lock reconstruction changed");
    const actual = evidenceBytes(join(dir, name));
    if (!actual.equals(jsonBytes(hosted[name])) || sha256(actual) !== card.hosted_bindings?.[name])
      throw new Error("tracking hosted lock differs from verified publication");
  }
  return { card, publication, record: `${TRACKING_DIR}/hf-delivery.json`, publicHosted: true, privateHosted: true };
}
