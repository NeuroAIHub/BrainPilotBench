/** Inspect mouse candidate metadata and files only; never execute preparation code. */
import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export const mouseDomains = Object.freeze(["animal-behavior", "calcium-imaging"]);
const statuses = new Set(["metadata_only_not_runnable", "preparation_ready_data_pending"]);

function statOrNull(path) {
  try { return lstatSync(path); }
  catch (error) { if (error.code === "ENOENT") return null; throw error; }
}

function ordinaryFile(path) {
  const stat = statOrNull(path);
  if (!stat?.isFile()) throw new Error(`${path}: expected an ordinary file; links are forbidden`);
}

function ordinaryDirectory(path) {
  const stat = statOrNull(path);
  if (!stat?.isDirectory()) throw new Error(`${path}: expected an ordinary directory; links are forbidden`);
}

function preparationFile(root, domain, path, label) {
  if (typeof path !== "string" || !path || isAbsolute(path) || path.includes("\\") || path.includes("\0"))
    throw new Error(`${label}: preparation_entry must be a repository-relative file`);
  const parts = path.split("/");
  if (parts.length < 3 || parts[0] !== "tasks" || parts[1] !== domain ||
      parts.some(part => !part || part === "." || part === ".."))
    throw new Error(`${label}: preparation_entry must stay within tasks/${domain}`);
  const target = resolve(root, path);
  const back = relative(join(root, "tasks", domain), target);
  if (back === ".." || back.startsWith(`..${sep}`) || isAbsolute(back))
    throw new Error(`${label}: preparation_entry escapes its domain`);
  let cursor = root;
  for (const part of parts) {
    cursor = join(cursor, part);
    const stat = statOrNull(cursor);
    if (stat?.isSymbolicLink()) throw new Error(`${label}: preparation path contains a link`);
    if (!stat) throw new Error(`${label}: missing preparation path ${path}`);
  }
  ordinaryFile(target);
}

export function validateMouseCandidate(card, { domain, name, dir, root }) {
  const label = `tasks/${domain}/${name}`;
  if (!card || typeof card !== "object" || Array.isArray(card) || card.schema !== "bpb-mouse-candidate/1")
    throw new Error(`${label}: unknown candidate schema`);
  if (!mouseDomains.includes(domain) || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name) ||
      card.id !== name || card.domain !== domain)
    throw new Error(`${label}: identity mismatch`);
  if (!statuses.has(card.status)) throw new Error(`${label}: unknown candidate status`);
  if (card.runnable !== false || card.validated !== false)
    throw new Error(`${label}: candidate must set runnable=false and validated=false`);
  for (const field of ["title", "source_task_id", "dataset_group_id", "input_description",
    "output_description", "native_split_description", "reason"]) {
    if (typeof card[field] !== "string" || !card[field].trim()) throw new Error(`${label}: missing ${field}`);
  }
  const metric = card.primary_metric;
  if (!metric || typeof metric !== "object" || Array.isArray(metric) ||
      typeof metric.id !== "string" || !metric.id.trim() ||
      !["maximize", "minimize"].includes(metric.direction) ||
      (metric.unit !== undefined && (typeof metric.unit !== "string" || !metric.unit.trim())) ||
      Object.keys(metric).some(key => !["id", "direction", "unit"].includes(key)))
    throw new Error(`${label}: invalid primary metric descriptor`);
  if (statOrNull(join(dir, "task.yaml"))) throw new Error(`${label}: candidate must not have task.yaml`);
  if (card.protocol !== "protocol.json") throw new Error(`${label}: expected protocol.json`);
  ordinaryFile(join(dir, "README.md"));
  ordinaryFile(join(dir, "protocol.json"));
  const protocol = JSON.parse(readFileSync(join(dir, "protocol.json"), "utf8"));
  if (!protocol || typeof protocol !== "object" || Array.isArray(protocol) || !Object.keys(protocol).length)
    throw new Error(`${label}: empty protocol`);
  if (card.status === "preparation_ready_data_pending")
    preparationFile(root, domain, card.preparation_entry, label);
  else if (card.preparation_entry !== undefined)
    throw new Error(`${label}: metadata-only candidate cannot claim preparation_entry`);
}

export function readMouseCandidates(root) {
  const entries = [];
  ordinaryDirectory(join(root, "tasks"));
  for (const domain of mouseDomains) {
    const domainRoot = join(root, "tasks", domain);
    if (!statOrNull(domainRoot)) continue;
    ordinaryDirectory(domainRoot);
    for (const entry of readdirSync(domainRoot, { withFileTypes: true })) {
      const dir = join(domainRoot, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`${dir}: task directory link forbidden`);
      if (!entry.isDirectory()) continue;
      const path = join(dir, "candidate.json");
      if (!statOrNull(path)) continue;
      ordinaryDirectory(dir);
      ordinaryFile(path);
      const card = JSON.parse(readFileSync(path, "utf8"));
      validateMouseCandidate(card, { domain, name: entry.name, dir, root });
      entries.push({ card, domain, dir, relDir: `tasks/${domain}/${entry.name}` });
    }
  }
  return entries.sort((a, b) => a.card.id.localeCompare(b.card.id));
}

export function mouseCatalogRow({ card, domain, relDir }) {
  const preparation = card.status === "preparation_ready_data_pending";
  return {
    task_id: card.id, domain, directory: relDir, entry_kind: "candidate",
    validation: preparation ? "preparation_tools_present_acceptance_pending" : "metadata_structure_checked",
    preparation_available: preparation, source_task_id: card.source_task_id,
    primary_metric: card.primary_metric, reason: card.reason,
  };
}
