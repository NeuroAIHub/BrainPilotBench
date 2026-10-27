import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { mouseCatalogRow, readMouseCandidates, validateMouseCandidate } from "./mouse-candidates.mjs";

function fixture(run) {
  const root = mkdtempSync(join(tmpdir(), "bpb-mouse-candidate-"));
  const domain = "animal-behavior";
  const name = "mouse-example";
  const dir = join(root, "tasks", domain, name);
  mkdirSync(dir, { recursive: true });
  const card = {
    schema: "bpb-mouse-candidate/1", id: name, domain,
    status: "metadata_only_not_runnable", runnable: false, validated: false,
    title: "Example mouse behavior", source_task_id: "source-example",
    dataset_group_id: "group-example", input_description: "Input records",
    output_description: "Behavior classes", native_split_description: "Native split",
    primary_metric: { id: "macro_f1", direction: "maximize" },
    protocol: "protocol.json", reason: "Data binding pending",
  };
  const put = (rel, value) => {
    const path = join(root, rel);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, value);
    return path;
  };
  put(`tasks/${domain}/${name}/README.md`, "# Candidate\n");
  put(`tasks/${domain}/${name}/protocol.json`, '{"schema":"example"}\n');
  const save = value => put(`tasks/${domain}/${name}/candidate.json`, JSON.stringify(value));
  save(card);
  try { run({ root, domain, name, dir, card, put, save }); }
  finally { rmSync(root, { recursive: true, force: true }); }
}

test("reader accepts metadata-only and preparation-pending cards without making them runnable", () => fixture(f => {
  const [entry] = readMouseCandidates(f.root);
  assert.equal(entry.card.id, f.name);
  assert.deepEqual(mouseCatalogRow(entry), {
    task_id: f.name, domain: f.domain, directory: `tasks/${f.domain}/${f.name}`,
    entry_kind: "candidate", validation: "metadata_structure_checked",
    preparation_available: false, source_task_id: "source-example",
    primary_metric: { id: "macro_f1", direction: "maximize" }, reason: "Data binding pending",
  });
  const preparation_entry = `tasks/${f.domain}/_shared/prepare.py`;
  f.put(preparation_entry, "# fixture only\n");
  f.save({ ...f.card, status: "preparation_ready_data_pending", preparation_entry });
  const [prepared] = readMouseCandidates(f.root);
  assert.equal(mouseCatalogRow(prepared).validation, "preparation_tools_present_acceptance_pending");
  assert.equal(mouseCatalogRow(prepared).preparation_available, true);
  assert.equal(prepared.card.runnable, false);
}));

test("identity, lifecycle, and metric claims fail closed", () => fixture(f => {
  const context = { domain: f.domain, name: f.name, dir: f.dir, root: f.root };
  for (const change of [
    { schema: "other" }, { id: "different" }, { domain: "calcium-imaging" },
    { status: "runnable" }, { runnable: true }, { runnable: undefined },
    { validated: true }, { validated: undefined }, { title: " " },
    { primary_metric: { id: "", direction: "maximize" } },
    { primary_metric: { id: "macro_f1", direction: "sideways" } },
    { primary_metric: { id: "macro_f1", direction: "maximize", value: Infinity } },
    { primary_metric: { id: NaN, direction: "maximize" } },
    { primary_metric: { id: "F1", direction: "maximize", unit: null } },
    { protocol: "other.json" },
  ]) assert.throws(() => validateMouseCandidate({ ...f.card, ...change }, context));
  f.save({ ...f.card, schema: "unknown" });
  assert.throws(() => readMouseCandidates(f.root), /unknown candidate schema/);
}));

test("optional metric units are retained, while a linked tasks root is rejected", () => fixture(f => {
  f.save({ ...f.card, primary_metric: { id: "F1", direction: "maximize", unit: "fraction" } });
  assert.equal(mouseCatalogRow(readMouseCandidates(f.root)[0]).primary_metric.unit, "fraction");
  const linkRoot = f.put("link-root/.keep", "");
  symlinkSync(join(f.root, "tasks"), join(dirname(linkRoot), "tasks"));
  assert.throws(() => readMouseCandidates(dirname(linkRoot)), /ordinary directory/);
}));

test("required files and absence of task.yaml are enforced", () => fixture(f => {
  f.put(`tasks/${f.domain}/${f.name}/task.yaml`, "id: mouse-example\n");
  assert.throws(() => readMouseCandidates(f.root), /must not have task.yaml/);
  rmSync(join(f.dir, "task.yaml"));
  rmSync(join(f.dir, "README.md"));
  assert.throws(() => readMouseCandidates(f.root), /ordinary file/);
  f.put(`tasks/${f.domain}/${f.name}/README.md`, "# Candidate\n");
  f.put(`tasks/${f.domain}/${f.name}/protocol.json`, "{}\n");
  assert.throws(() => readMouseCandidates(f.root), /empty protocol/);
}));

test("preparation paths stay ordinary files within the same domain", () => fixture(f => {
  for (const preparation_entry of ["/tmp/prepare.py", "../prepare.py", "scripts/prepare.py",
    `tasks/${f.domain}/../calcium-imaging/prepare.py`, `tasks/${f.domain}/missing.py`, ""]) {
    f.save({ ...f.card, status: "preparation_ready_data_pending", preparation_entry });
    assert.throws(() => readMouseCandidates(f.root));
  }
  f.save({ ...f.card, preparation_entry: `tasks/${f.domain}/_shared/prepare.py` });
  assert.throws(() => readMouseCandidates(f.root), /cannot claim preparation_entry/);
}));

test("candidate, directory, protocol, and intermediate preparation links are rejected", () => fixture(f => {
  const cardPath = join(f.dir, "candidate.json");
  const copy = f.put(`tasks/${f.domain}/${f.name}/card-copy.json`, readFileSync(cardPath));
  rmSync(cardPath);
  symlinkSync(copy, cardPath);
  assert.throws(() => readMouseCandidates(f.root), /ordinary file/);
  rmSync(cardPath);
  f.save(f.card);

  const protocolPath = join(f.dir, "protocol.json");
  rmSync(protocolPath);
  symlinkSync(f.put(`tasks/${f.domain}/${f.name}/protocol-copy.json`, '{"ok":true}\n'), protocolPath);
  assert.throws(() => readMouseCandidates(f.root), /ordinary file/);
  rmSync(protocolPath);
  f.put(`tasks/${f.domain}/${f.name}/protocol.json`, '{"ok":true}\n');

  f.put(`tasks/${f.domain}/real/prepare.py`, "# fixture\n");
  symlinkSync(join(f.root, "tasks", f.domain, "real"), join(f.root, "tasks", f.domain, "real", "linked"));
  f.save({ ...f.card, status: "preparation_ready_data_pending",
    preparation_entry: `tasks/${f.domain}/real/linked/prepare.py` });
  assert.throws(() => readMouseCandidates(f.root), /contains a link/);
  unlinkSync(join(f.root, "tasks", f.domain, "real", "linked"));
  f.save(f.card);

  const linkedDir = join(f.root, "tasks", f.domain, "mouse-linked");
  symlinkSync(f.dir, linkedDir);
  assert.throws(() => readMouseCandidates(f.root), /task directory link forbidden/);
}));
