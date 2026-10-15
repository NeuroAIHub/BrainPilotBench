#!/usr/bin/env node
/** Prepare public data.lock URI migration from an exact, audited HF preview.
 * Dry run is the default. --apply requires the actual published 40-hex revision.
 * Private entries and task metadata are never selected for replacement.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const previewFile = join(root, ".cache/hf-unified-audit-20261015/migration-preview.json");
const args = process.argv.slice(2);
const option = flag => {
  const at = args.indexOf(flag);
  if (at < 0) return undefined;
  if (!args[at + 1] || args[at + 1].startsWith("--")) throw new Error(`${flag} needs a value`);
  return args[at + 1];
};
const revision = option("--revision");
const apply = args.includes("--apply");
const check = args.includes("--check");
if (!/^[0-9a-f]{40}$/.test(revision ?? ""))
  throw new Error("Pass --revision with the actual published 40-hex Hugging Face commit");
if (apply && check) throw new Error("Choose --apply or --check");
if (!existsSync(previewFile)) throw new Error(`Missing audited preview: ${previewFile}`);
const previewBytes = readFileSync(previewFile);
if (createHash("sha256").update(previewBytes).digest("hex") !==
    "bc98f67db0f3d2e09b2fdce373a638ae816f886c9fc5103b6156204f314ae1b6")
  throw new Error("Audited migration preview SHA-256 changed; stop before updating locks");
const preview = JSON.parse(previewBytes);
if (preview.repo_id !== "BrainPilot-Bench/Tasks-Data-Public" ||
    preview.operations_preview?.length !== 668 || preview.tasks?.length !== 112 ||
    preview.hosted_tasks_planned !== 111 || preview.source_only_tasks?.length !== 1 ||
    preview.source_only_tasks[0] !== "falcon-h1-reach-grasp")
  throw new Error("Preview is not the expected 112-task public migration plan");
if (revision === preview.baseline_revision)
  throw new Error("The supplied revision is the old baseline, not a new published snapshot");

const replacementIds = new Set([
  "ieeg-finger-flexion-bciciv4", "falcon-h2-handwriting", "falcon-m1-emg",
  "falcon-m2-finger-velocity", "falcon-b1-birdsong", "ieeg-film-speech-music",
]);
const operations = new Map();
for (const op of preview.operations_preview) {
  if (!/^tasks\/(?:eeg|mri|psychology|connectomics|calcium-imaging|invasive)\/[^/]+\/public\/.+/.test(op.target) ||
      !/^[a-f0-9]{64}$/.test(op.sha256) || !Number.isSafeInteger(op.bytes) || op.bytes < 0)
    throw new Error(`Unsafe preview operation: ${op.target}`);
  if (!operations.has(op.task_id)) operations.set(op.task_id, []);
  operations.get(op.task_id).push(op);
}
const hfUri = target => `hf://datasets/${preview.repo_id}@${revision}/${target}`;
const fail = (id, message) => { throw new Error(`${id}: ${message}`); };
const formatFor = path => basename(path).split(".").at(-1);
const normalized = value => JSON.stringify(value);
const updated = [];
const pendingWrites = [];
let publicEntries = 0;

for (const task of preview.tasks) {
  const id = task.task_id;
  if (task.access === "source_only") {
    if (id !== "falcon-h1-reach-grasp" || operations.has(id)) fail(id, "source-only task has planned hosted assets");
    continue;
  }
  if (task.access !== "hosted_public_planned") fail(id, `unexpected access ${task.access}`);
  const planned = operations.get(id) ?? [];
  if (!planned.length) fail(id, "no public operations");
  const lockPath = join(root, task.source_code_directory, "data.lock");
  if (!existsSync(lockPath)) fail(id, "missing data.lock");
  const original = readFileSync(lockPath, "utf8");
  const json = original.trimStart().startsWith("{");
  const lock = json ? JSON.parse(original) : YAML.parse(original);
  if (!Array.isArray(lock.datasets)) fail(id, "missing datasets array");
  const oldPrivate = lock.datasets.filter(x => x.scope === "private");
  const oldPublic = lock.datasets.filter(x => x.scope === "public" || x.scope === undefined);
  const prefix = `tasks/${task.data_category}/${id}/public/`;
  const paths = new Set();
  for (const op of planned) {
    if (!op.target.startsWith(prefix)) fail(id, `wrong canonical target: ${op.target}`);
    const native = op.target.slice(prefix.length);
    if (!native || native.startsWith("/") || native.split("/").some(x => !x || x === "." || x === ".."))
      fail(id, `unsafe native path: ${native}`);
    if (paths.has(native.toLowerCase())) fail(id, `duplicate native path: ${native}`);
    paths.add(native.toLowerCase());
  }
  let nextPublic;
  if (replacementIds.has(id)) {
    const byDigest = new Map(oldPublic.map(x => [`${x.sha256}:${x.bytes}`, x]));
    nextPublic = planned.map(op => {
      const native = op.target.slice(prefix.length);
      const existing = byDigest.get(`${op.sha256}:${op.bytes}`);
      return {
        name: existing?.name ?? native.replaceAll("/", "__"),
        uri: hfUri(op.target), sha256: op.sha256, bytes: op.bytes,
        format: existing?.format ?? formatFor(native), scope: "public", path: native,
      };
    });
  } else {
    if (oldPublic.length !== planned.length) fail(id, "old public count differs from preview");
    const unmatched = [...planned];
    nextPublic = oldPublic.map(entry => {
      const matches = unmatched.filter(op => op.sha256 === entry.sha256 && op.bytes === entry.bytes);
      if (matches.length !== 1) fail(id, `ambiguous preview mapping for ${entry.name}`);
      const op = matches[0];
      unmatched.splice(unmatched.indexOf(op), 1);
      return { ...entry, uri: hfUri(op.target) };
    });
    if (unmatched.length) fail(id, "unmapped preview operations");
  }
  if (new Set(nextPublic.map(x => x.name.toLowerCase())).size !== nextPublic.length)
    fail(id, "colliding public dataset names");
  publicEntries += nextPublic.length;
  const next = { ...lock, datasets: [...nextPublic, ...oldPrivate] };
  if (normalized(next.datasets.filter(x => x.scope === "private")) !== normalized(oldPrivate))
    fail(id, "private entries changed");
  let content;
  if (json) {
    // These two JSON locks keep their private object text exactly as recorded.
    if (!replacementIds.has(id) || !oldPrivate.length) fail(id, "unexpected JSON lock layout");
    const opening = original.indexOf("[", original.indexOf('"datasets"'));
    const firstPrivateName = JSON.stringify(oldPrivate[0].name);
    const firstPrivateAt = original.indexOf(`"name": ${firstPrivateName}`, opening);
    const privateStart = original.lastIndexOf("    {", firstPrivateAt);
    if (opening < 0 || firstPrivateAt < 0 || privateStart < opening)
      fail(id, "cannot preserve private JSON block");
    const renderedPublic = nextPublic.map(x =>
      "    " + JSON.stringify(x, null, 2).replaceAll("\n", "\n    ")).join(",\n");
    content = original.slice(0, opening + 1) + "\n" + renderedPublic + ",\n" + original.slice(privateStart);
  } else if (replacementIds.has(id)) {
    // Keep the original header and every private YAML block byte-for-byte.
    const doc = YAML.parseDocument(original, { keepSourceTokens: true });
    const items = doc.get("datasets", true)?.items;
    if (!items || items.length !== lock.datasets.length) fail(id, "YAML item offsets unavailable");
    const start = items[0].range[0] - 4;
    const privateBlocks = items.flatMap((item, index) => {
      if (lock.datasets[index].scope !== "private") return [];
      const from = item.range[0] - 4;
      const to = index + 1 < items.length ? items[index + 1].range[0] - 4 : original.length;
      return [original.slice(from, to)];
    });
    const publicYaml = YAML.stringify({ datasets: nextPublic }).replace(/^datasets:\n/, "");
    content = original.slice(0, start) + publicYaml + privateBlocks.join("");
  } else {
    content = original;
    for (let i = 0; i < oldPublic.length; i++) {
      const from = oldPublic[i].uri;
      const to = nextPublic[i].uri;
      const needle = `uri: ${from}`;
      if (content.split(needle).length !== 2) fail(id, `URI is not unique in YAML: ${from}`);
      content = content.replace(needle, `uri: ${to}`);
    }
  }
  const parsed = json ? JSON.parse(content) : YAML.parse(content);
  if (normalized(parsed.datasets.filter(x => x.scope === "private")) !== normalized(oldPrivate))
    fail(id, "rendered private entries changed");
  if (parsed.datasets.filter(x => x.scope === "public" || x.scope === undefined).length !== planned.length)
    fail(id, "rendered public count differs from preview");
  if (content !== original) {
    updated.push(relative(root, lockPath));
    pendingWrites.push([lockPath, content]);
    if (check) fail(id, "lock is stale for supplied revision");
  }
}
if (publicEntries !== preview.operations_preview.length)
  throw new Error(`Mapped ${publicEntries} public entries; expected ${preview.operations_preview.length}`);
if (apply) for (const [file, content] of pendingWrites) writeFileSync(file, content);
console.log(JSON.stringify({ mode: apply ? "applied" : check ? "check" : "dry_run", revision,
  hosted_tasks: 111, source_only_tasks: 1, public_entries: publicEntries, changed_locks: updated.length,
  files: updated }, null, 2));
