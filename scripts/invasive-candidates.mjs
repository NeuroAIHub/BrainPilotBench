/** Read candidate metadata only. Never import or execute task code. */
import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export const invasiveDomains = Object.freeze(["ieeg", "intracortical"]);
const statuses = new Set(["metadata_only_not_runnable", "preparation_ready_data_pending"]);

function regularFile(path) {
  if (!lstatSync(path).isFile()) throw new Error(`${path}: expected a regular file, not a link`);
}

export function validateInvasiveCandidate(card, { domain, name, dir, root }) {
  const label = `tasks/${domain}/${name}`;
  if (card.schema !== "bpb-invasive-candidate/1") throw new Error(`${label}: unknown candidate schema`);
  if (card.id !== name || card.domain !== domain) throw new Error(`${label}: identity mismatch`);
  if (!statuses.has(card.status)) throw new Error(`${label}: unknown candidate status`);
  if (card.runnable !== false || (card.validated !== undefined && card.validated !== false))
    throw new Error(`${label}: candidate must set runnable=false and cannot claim validated`);
  for (const field of ["title", "source_task_id", "dataset_group_id", "input_description",
    "output_description", "native_split_description", "reason"]) {
    if (typeof card[field] !== "string" || !card[field].trim()) throw new Error(`${label}: missing ${field}`);
  }
  if (typeof card.primary_metric?.id !== "string" || !card.primary_metric.id.trim() ||
      !["maximize", "minimize"].includes(card.primary_metric.direction))
    throw new Error(`${label}: invalid primary metric`);
  if (existsSync(join(dir, "task.yaml"))) throw new Error(`${label}: candidate must not have task.yaml`);
  if (card.protocol !== "protocol.json") throw new Error(`${label}: expected protocol.json`);
  for (const file of ["README.md", "protocol.json"]) regularFile(join(dir, file));
  const protocol = JSON.parse(readFileSync(join(dir, "protocol.json"), "utf8"));
  if (!protocol || Array.isArray(protocol) || typeof protocol !== "object" || !Object.keys(protocol).length)
    throw new Error(`${label}: empty protocol`);
  if (card.status === "preparation_ready_data_pending") {
    if (typeof card.preparation_entry !== "string" || !card.preparation_entry || isAbsolute(card.preparation_entry))
      throw new Error(`${label}: preparation_entry must be a repository-relative file`);
    const target = resolve(root, card.preparation_entry);
    const domainRoot = join(root, "tasks", domain);
    const back = relative(domainRoot, target);
    if (back === ".." || back.startsWith(`..${sep}`) || isAbsolute(back))
      throw new Error(`${label}: preparation entry escapes its domain`);
    // Reject intermediate symlinks, including links that point outside the checkout.
    let cursor = domainRoot;
    for (const part of back.split(sep)) {
      cursor = join(cursor, part);
      if (lstatSync(cursor).isSymbolicLink()) throw new Error(`${label}: preparation path contains a link`);
    }
    regularFile(target);
  }
}

export function readInvasiveCandidates(root) {
  const entries = [];
  for (const domain of invasiveDomains) {
    const domainRoot = join(root, "tasks", domain);
    if (!existsSync(domainRoot)) continue;
    if (!lstatSync(domainRoot).isDirectory()) throw new Error(`${domainRoot}: expected a regular directory`);
    for (const entry of readdirSync(domainRoot, { withFileTypes: true })) {
      const dir = join(domainRoot, entry.name);
      if (!entry.isDirectory()) continue;
      const path = join(dir, "candidate.json");
      if (!existsSync(path)) continue;
      regularFile(path);
      const card = JSON.parse(readFileSync(path, "utf8"));
      validateInvasiveCandidate(card, { domain, name: entry.name, dir, root });
      entries.push({ card, domain, dir, relDir: `tasks/${domain}/${entry.name}` });
    }
  }
  return entries.sort((a, b) => a.card.id.localeCompare(b.card.id));
}

export function invasiveCatalogRow({ card, domain, relDir }) {
  const preparation = card.status === "preparation_ready_data_pending";
  return {
    task_id: card.id, domain, directory: relDir, entry_kind: "candidate",
    validation: preparation ? "preparation_tools_present_acceptance_pending" : "metadata_structure_checked",
    preparation_available: preparation, source_task_id: card.source_task_id,
    primary_metric: card.primary_metric, reason: card.reason,
  };
}
