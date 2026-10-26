import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';
import { buildPrivateEvaluatorLocks } from './build-private-evaluator-locks.mjs';
import { validatePrivateEvaluatorIncrement } from './private-evaluator-increment.mjs';

const digest = text => createHash('sha256').update(text).digest('hex');
const REPO = 'BrainPilot-Bench/Tasks-Data-Private';
const REVISION = 'a'.repeat(40);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const planPath = root => path.join(root, '.cache/hf-private-preparation-20261019/expanded/delivery-plan.json');
const receiptPath = root => path.join(root, '.cache/hf-private-upload-20261019/private-verify-receipt.json');
const maintainerReceiptsAvailable = root => existsSync(planPath(root)) && existsSync(receiptPath(root));

function fixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'bpb-private-locks-'));
  const taskDir = path.join(root, 'tasks/eeg/task-one');
  mkdirSync(taskDir, { recursive: true });
  writeFileSync(path.join(root, 'tasks/catalog.json'), JSON.stringify({ tasks: [
    { task_id: 'task-one', directory: 'tasks/eeg/task-one' },
  ] }));
  const publicText = '  - name: train.npz\n    scope: public\n    uri: hf://datasets/public@old/train.npz\n    sha256: ' +
    '1'.repeat(64) + '\n    bytes: 10\n    format: npz\n';
  const source = '# Keep this header byte-for-byte.\ndatasets:\n' + publicText +
    '  - name: old-test.npy\n    scope: private\n    uri: local://evaluator/test/test.npy\n    sha256: ' +
    'a'.repeat(64) + '\n    bytes: 12\n    format: npy\n' +
    '  - name: raw-only.bin\n    scope: private\n    uri: https://example.org/raw.bin\n    sha256: ' +
    'b'.repeat(64) + '\n    bytes: 13\n    format: bin\n';
  writeFileSync(path.join(taskDir, 'data.lock'), source);
  const files = [
    { access_role: 'private_evaluator', task_id: 'task-one',
      target_path: 'tasks/eeg/task-one/evaluator/test/test.npy', sha256: 'a'.repeat(64), bytes: 12 },
    { access_role: 'private_evaluator', task_id: 'task-one',
      target_path: 'tasks/eeg/task-one/evaluator/test/labels.json', sha256: 'c'.repeat(64), bytes: 14 },
  ];
  const plan = { schema: 'bpb-private-expanded-delivery-plan/1', destination: { repo_id: REPO },
    new_tasks: 1, new_files: 2, new_bytes: 26, files };
  const planSha256 = digest(JSON.stringify(plan));
  const receipt = { schema: 'bpb-private-final-verify/1', status: 'passed', repo_id: REPO,
    head: REVISION, plan_sha256: planSha256, tree_identity: {
      all_paths_and_lfs_or_git_blobs_checked: true, new_data_objects: 2, new_data_bytes: 26,
    } };
  const build = () => buildPrivateEvaluatorLocks({ root, plan, receipt, planSha256,
    expectedRevision: REVISION, expectedPlanSha256: planSha256,
    expectedTasks: 1, expectedFiles: 2, expectedBytes: 26 });
  return { root, source, publicText, plan, receipt, build };
}

test('binds exact uploaded paths while preserving public and unrelated private entries', () => {
  const f = fixture();
  try {
    const result = f.build();
    assert.equal(result.files, 2);
    assert.equal(result.addedEntries, 1);
    assert.equal(result.reboundEntries, 1);
    assert.equal(result.preservedPrivateEntries, 1);
    const next = result.outputs.get('tasks/eeg/task-one/data.lock');
    assert.ok(next.startsWith(f.source.slice(0, f.source.indexOf('    uri: local://'))));
    assert.ok(next.includes(f.publicText));
    const parsed = YAML.parse(next);
    assert.equal(parsed.datasets.find(x => x.name === 'raw-only.bin').uri, 'https://example.org/raw.bin');
    assert.equal(parsed.datasets.find(x => x.name === 'old-test.npy').uri,
      `hf://datasets/${REPO}@${REVISION}/tasks/eeg/task-one/evaluator/test/test.npy`);
    const lock = JSON.parse(result.outputs.get('tasks/eeg/task-one/evaluator.lock'));
    assert.deepEqual(lock.files.map(x => [x.name, x.path]), [
      ['evaluator__test__labels.json', 'test/labels.json'], ['old-test.npy', 'test/test.npy'],
    ]);
    assert.deepEqual(Object.keys(lock), ['schema', 'task_id', 'repo_id', 'revision', 'files']);
    assert.ok(!JSON.stringify([...result.outputs.values()]).includes('/Users/'));
    for (const [file, content] of result.outputs) writeFileSync(path.join(f.root, file), content);
    assert.equal(f.build().outputs.size, 0, 'rebuilding applied locks must be idempotent');
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});

test('rejects changed receipt, path traversal, and mismatched native private data', () => {
  const f = fixture();
  try {
    f.receipt.head = 'b'.repeat(40);
    assert.throws(f.build, /receipt/);
    f.receipt.head = REVISION;
    f.plan.files[0].target_path = 'tasks/eeg/task-one/evaluator/../bad.npy';
    assert.throws(f.build, /unsafe path/);
    f.plan.files[0].target_path = 'tasks/eeg/task-one/evaluator/test/test.npy';
    f.plan.files[0].sha256 = 'd'.repeat(64);
    assert.throws(f.build, /differs from uploaded/);
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});

test('rebound URI scalars keep an existing JSON data.lock valid and idempotent', () => {
  const f = fixture();
  try {
    const file = path.join(f.root, 'tasks/eeg/task-one/data.lock');
    const original = { datasets: [
      { name: 'train.bin', scope: 'public', uri: 'https://example.org/train.bin',
        sha256: 'f'.repeat(64), bytes: 10 },
      { name: 'old-test.npy', scope: 'private', uri: 'local://evaluator/test/test.npy',
        sha256: 'a'.repeat(64), bytes: 12 },
      { name: 'old-labels.json', scope: 'private', uri: 'local://evaluator/test/labels.json',
        sha256: 'c'.repeat(64), bytes: 14 },
    ] };
    writeFileSync(file, `${JSON.stringify(original, null, 2)}\n`);
    const built = f.build();
    const next = built.outputs.get('tasks/eeg/task-one/data.lock');
    const parsed = JSON.parse(next);
    assert.deepEqual(parsed.datasets[0], original.datasets[0]);
    assert.equal(parsed.datasets[1].uri.startsWith(`hf://datasets/${REPO}@${REVISION}/`), true);
    for (const [target, content] of built.outputs) writeFileSync(path.join(f.root, target), content);
    assert.equal(f.build().outputs.size, 0);
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});

test('maintainer source comparison is optional when ignored upload receipts are absent', () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'bpb-clean-checkout-'));
  try { assert.equal(maintainerReceiptsAvailable(root), false); }
  finally { rmSync(root, { recursive: true, force: true }); }
});

test('checked-in increment binds 29 tasks and 301 evaluator files without local source paths', () => {
  const validated = validatePrivateEvaluatorIncrement(ROOT);
  assert.equal(validated.tasks, 29);
  assert.equal(validated.files, 301);
  assert.equal(validated.bytes, 8353488018);
  assert.equal(validated.publicEntries, 504);
  let count = 0;
  let unrelatedPrivate = 0;
  for (const item of validated.report.tasks) {
    const content = readFileSync(path.join(ROOT, item.directory, 'evaluator.lock'), 'utf8');
    const lock = JSON.parse(content);
    const entries = YAML.parse(readFileSync(path.join(ROOT, item.directory, 'data.lock'), 'utf8')).datasets;
    const selected = new Set(lock.files.map(file => file.name));
    unrelatedPrivate += entries.filter(entry => entry.scope === 'private' && !selected.has(entry.name)).length;
    count += lock.files.length;
    assert.equal(new Set(lock.files.map(file => file.path.toLowerCase())).size, lock.files.length);
    assert.equal(new Set(lock.files.map(file => file.name.toLowerCase())).size, lock.files.length);
    assert.ok(!content.includes('source_path'));
    assert.ok(!content.includes('/Users/'));
  }
  assert.equal(count, 301);
  // Historical private source entries remain outside the evaluator whitelist.
  assert.equal(unrelatedPrivate, 317);
});

test('maintainer-only source plan reproduces checked-in bindings', {
  skip: !maintainerReceiptsAvailable(ROOT)
    ? 'local private upload plan/receipt are unavailable in clean CI' : false,
}, () => {
  const planBytes = readFileSync(planPath(ROOT));
  const plan = JSON.parse(planBytes);
  const receipt = JSON.parse(readFileSync(receiptPath(ROOT)));
  const result = buildPrivateEvaluatorLocks({ root: ROOT, plan, receipt, planSha256: digest(planBytes) });
  assert.equal(result.tasks, 29);
  assert.equal(result.files, 301);
  assert.equal(result.bytes, 8353488018);
  // The 301 evaluator bindings do not mean every historical data.lock private
  // entry is hosted; 317 unrelated entries remain outside this whitelist.
  assert.equal(result.preservedPrivateEntries, 317);
  let count = 0;
  const directoryById = new Map(JSON.parse(readFileSync(path.join(ROOT, 'tasks/catalog.json')))
    .tasks.map(task => [task.task_id, task.directory]));
  for (const id of new Set(plan.files.map(file => file.task_id))) {
    const file = `${directoryById.get(id)}/evaluator.lock`;
    const content = result.outputs.get(file) ?? readFileSync(path.join(ROOT, file), 'utf8');
    const lock = JSON.parse(content);
    count += lock.files.length;
    assert.equal(new Set(lock.files.map(x => x.path.toLowerCase())).size, lock.files.length);
    assert.equal(new Set(lock.files.map(x => x.name.toLowerCase())).size, lock.files.length);
    assert.ok(!content.includes('source_path'));
    assert.ok(!content.includes('/Users/'));
  }
  assert.equal(count, 301);
});
