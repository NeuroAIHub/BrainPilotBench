/** Verify transport-only mouse mirrors without replacing scientific acceptance. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync } from "node:fs";
import { join } from "node:path";

export const MOUSE_TASK_IDS = ["calms21-classic-classification", "calms21-annotation-style-transfer",
  "calms21-few-shot-behavior", "mabe22-supervised-segmentation", "mabe22-representation-classification"];
export const MOUSE_REPOS = { public: "BrainPilot-Bench/Tasks-Data-Public", private: "BrainPilot-Bench/Tasks-Data-Private" };
const hex = (v, n = 64) => typeof v === "string" && new RegExp(`^[0-9a-f]{${n}}$`).test(v);
export const sha256 = value => createHash("sha256").update(value).digest("hex");
const sorted = v => Array.isArray(v) ? v.map(sorted) : v && typeof v === "object"
  ? Object.fromEntries(Object.keys(v).sort().map(k => [k, sorted(v[k])])) : v;
export const jsonBytes = value => Buffer.from(JSON.stringify(sorted(value), null, 2) + "\n");
function safePath(value) {
  if (typeof value !== "string" || !value || value.split("/").some(p => !/^[A-Za-z0-9._-]+$/.test(p) || p === "." || p === ".."))
    throw new Error("unsafe mouse delivery path");
  return value;
}
export function evidenceBytes(path) {
  const info = lstatSync(path);
  if (!info.isFile() || info.nlink !== 1) throw new Error("mouse delivery evidence requires an independent regular file");
  return readFileSync(path);
}
export function remotePath(id, role, native) {
  safePath(native);
  return `tasks/animal-behavior/${id}/${role === "public" ? "public" : "evaluator"}/${role === "public" ? native.replace(/^public\//, "") : native}`;
}

export function readMousePublication(root, path, expectedSha) {
  safePath(path);
  if (!path.startsWith("reports/")) throw new Error("publication evidence must be under reports/");
  const bytes = evidenceBytes(join(root, path));
  if (expectedSha !== undefined && sha256(bytes) !== expectedSha) throw new Error("mouse publication receipt SHA mismatch");
  const receipt = JSON.parse(bytes);
  if (receipt.schema !== "bpb-mouse-hf-publication/1" || receipt.status !== "verified")
    throw new Error("mouse publication is not verified");
  let total = 0;
  for (const role of ["public", "private"]) {
    const published = receipt[role];
    if (published === null || published === undefined) continue;
    if (published.repo_id !== MOUSE_REPOS[role] || !hex(published.revision, 40) || !Array.isArray(published.files) ||
        published.private !== (role === "private") || published.old_data_unchanged !== true)
      throw new Error("invalid mouse publication destination");
    const paths = new Set();
    for (const file of published.files) {
      if (!MOUSE_TASK_IDS.includes(file.task_id) || !hex(file.sha256) || !Number.isSafeInteger(file.bytes) || file.bytes <= 0 ||
          file.path !== remotePath(file.task_id, role, file.native_path) || paths.has(file.path))
        throw new Error("invalid or duplicate mouse publication file");
      paths.add(file.path); total++;
    }
  }
  if (!total) throw new Error("empty mouse publication");
  return { receipt, sha256: sha256(bytes), path };
}

export function mouseSourceLocks(contract) {
  const id = contract.task_id;
  if (!MOUSE_TASK_IDS.includes(id) || !hex(contract.revision)) throw new Error("invalid mouse content identity");
  const data = { datasets: [] };
  for (const [role, key] of [["public", "public_files"], ["evaluator", "owner_files"]]) {
    if (!Array.isArray(contract[key]) || !contract[key].length) throw new Error("mouse contract file set missing");
    for (const row of contract[key]) {
      safePath(row.path);
      if (!hex(row.sha256) || !Number.isSafeInteger(row.bytes) || row.bytes <= 0) throw new Error("invalid mouse content file");
      const entry = { name: role + "__" + row.path.replaceAll("/", "__"),
        uri: `local://tasks/animal-behavior/${id}/${contract.revision}/${role}/${row.path}`,
        sha256: row.sha256, bytes: row.bytes, scope: role === "public" ? "public" : "private",
        format: row.path.endsWith(".json") ? "json" : "npz" };
      if (role === "public") entry.path = id.startsWith("calms21-") ? "public/" + row.path : row.path;
      data.datasets.push(entry);
    }
  }
  const evaluator = { schema: "bpb-evaluator-source/1", task_id: id, repo_id: "local-prepared", revision: contract.revision,
    files: contract.owner_files.map(row => ({ name: "evaluator__" + row.path.replaceAll("/", "__"), ...row })) };
  if (contract.public_equivalent_sha256) evaluator.public_equivalent_sha256 = contract.public_equivalent_sha256;
  return { "data.lock": data, "evaluator.lock": evaluator };
}

export function mouseHostedLocks(contract, receipt) {
  const source = mouseSourceLocks(contract), hosted = structuredClone(source), destinations = {};
  for (const [role, key] of [["public", "public_files"], ["private", "owner_files"]]) {
    const published = receipt[role];
    const rows = published?.files.filter(file => file.task_id === contract.task_id) ?? [];
    if (!rows.length) { destinations[role] = null; continue; }
    const expected = contract[key];
    if (rows.length !== expected.length) throw new Error("partial mouse role publication");
    const byNative = new Map(rows.map(row => [row.native_path, row]));
    if (byNative.size !== rows.length) throw new Error("duplicate mouse native path");
    for (const row of expected) {
      const actual = byNative.get(row.path);
      if (!actual || actual.sha256 !== row.sha256 || actual.bytes !== row.bytes ||
          actual.path !== remotePath(contract.task_id, role, row.path)) throw new Error("publication differs from mouse scientific content");
    }
    destinations[role] = { repo_id: published.repo_id, revision: published.revision };
    for (const entry of hosted["data.lock"].datasets) {
      if (entry.scope !== role) continue;
      const prefix = `local://tasks/animal-behavior/${contract.task_id}/${contract.revision}/${role === "public" ? "public" : "evaluator"}/`;
      if (!entry.uri.startsWith(prefix)) throw new Error("mouse source URI changed during binding");
      const native = entry.uri.slice(prefix.length);
      entry.uri = `hf://datasets/${published.repo_id}@${published.revision}/${remotePath(contract.task_id, role, native)}`;
    }
    if (role === "private") Object.assign(hosted["evaluator.lock"], {
      schema: "bpb-evaluator-data/1", repo_id: published.repo_id, revision: published.revision });
  }
  return { source, hosted, destinations };
}

export function readMouseDelivery(root, task, acceptance) {
  const path = join(task.dir, "hf-delivery.json");
  if (!existsSync(path)) return null;
  const card = JSON.parse(evidenceBytes(path));
  const contract = JSON.parse(evidenceBytes(join(task.dir, "contract.json")));
  if (card.schema !== "bpb-mouse-hf-delivery/1" || card.task_id !== task.meta.id ||
      card.content_revision !== contract.revision || card.transport_only !== true ||
      !hex(card.publication_receipt_sha256)) throw new Error("invalid mouse delivery bridge");
  const publication = readMousePublication(root, card.publication_receipt, card.publication_receipt_sha256);
  const { source, hosted, destinations } = mouseHostedLocks(contract, publication.receipt);
  if (!destinations.public && !destinations.private) throw new Error("mouse delivery has no published role");
  if (JSON.stringify(sorted(card.source_bindings)) !== JSON.stringify(sorted(acceptance.bindings)) ||
      JSON.stringify(sorted(card.public)) !== JSON.stringify(sorted(destinations.public)) ||
      JSON.stringify(sorted(card.private)) !== JSON.stringify(sorted(destinations.private)))
    throw new Error("mouse delivery changes historical acceptance or destinations");
  for (const file of ["contract.json", "task.yaml"])
    if (sha256(evidenceBytes(join(task.dir, file))) !== acceptance.bindings[file]) throw new Error("mouse delivery changes scientific contract");
  for (const file of ["data.lock", "evaluator.lock"]) {
    if (sha256(jsonBytes(source[file])) !== acceptance.bindings[file]) throw new Error("mouse source lock cannot be reconstructed");
    const actual = evidenceBytes(join(task.dir, file));
    if (!actual.equals(jsonBytes(hosted[file])) || sha256(actual) !== card.hosted_bindings?.[file])
      throw new Error("mouse hosted lock differs from verified publication");
  }
  return { card, publication, record: `tasks/animal-behavior/${task.meta.id}/hf-delivery.json`,
    publicHosted: !!destinations.public, privateHosted: !!destinations.private };
}
