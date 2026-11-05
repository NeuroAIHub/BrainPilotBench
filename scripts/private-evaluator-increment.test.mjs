import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { INCREMENT_PATH, validatePrivateEvaluatorIncrement } from './private-evaluator-increment.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const report = JSON.parse(readFileSync(path.join(ROOT, INCREMENT_PATH), 'utf8'));

function copyEvidence() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'bpb-private-increment-'));
  const paths = new Set([INCREMENT_PATH, ...Object.keys(report.core_file_sha256)]);
  paths.add('reports/mouse-closeout-20261026/source-evaluator-compatibility.json');
  paths.add('src/evaluator-source.test.ts');
  for (const item of report.tasks) {
    paths.add(`${item.directory}/data.lock`);
    paths.add(`${item.directory}/evaluator.lock`);
    if (item.prior_delivery_sha256) {
      paths.add(`${item.directory}/acceptance.json`);
      paths.add(`${item.directory}/delivery-acceptance.json`);
      paths.add(`${item.directory}/env/setup.sh`);
    }
  }
  for (const name of paths) {
    mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    copyFileSync(path.join(ROOT, name), path.join(root, name));
  }
  return { root, report: structuredClone(report), cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

test('additive record checks 29 exact locks without replaying scientific acceptance', () => {
  const verified = validatePrivateEvaluatorIncrement(ROOT);
  assert.equal(verified.tasks, 29);
  assert.equal(verified.files, 301);
  assert.equal(verified.bytes, 8353488018);
  assert.equal(verified.publicEntries, 504);
  assert.equal(verified.report.scope, 'metadata_transport_only');
  assert.equal(verified.report.scientific_acceptance_replayed, false);
  assert.equal(Object.hasOwn(verified.report, 'model_scoring_run'), false);
});

test('checked-in evidence validates in an isolated checkout without .cache receipts', () => {
  const f = copyEvidence();
  try {
    assert.equal(existsSync(path.join(f.root, '.cache')), false);
    const verified = validatePrivateEvaluatorIncrement(f.root);
    assert.equal(verified.tasks, 29);
    assert.equal(verified.files, 301);
  } finally { f.cleanup(); }
});

test('changed public URI cannot be hidden by updating the new lock hash', () => {
  const f = copyEvidence();
  try {
    const item = f.report.tasks.find(task => task.task_id === 'eeg-mi-barachant2012');
    const file = path.join(f.root, item.directory, 'data.lock');
    const original = readFileSync(file, 'utf8');
    const changed = original.replace('Tasks-Data-Public@f506', 'Tasks-Data-Public@e506');
    assert.notEqual(changed, original);
    writeFileSync(file, changed);
    item.data_lock_sha256 = sha(changed);
    assert.throws(() => validatePrivateEvaluatorIncrement(f.root, f.report), /cannot be reconstructed/);
  } finally { f.cleanup(); }
});

test('uploaded evaluator object identity stays fixed even if both new locks are edited', () => {
  const f = copyEvidence();
  try {
    const item = f.report.tasks.find(task => task.task_id === 'eeg-mi-barachant2012');
    const dataPath = path.join(f.root, item.directory, 'data.lock');
    const lockPath = path.join(f.root, item.directory, 'evaluator.lock');
    const evaluator = JSON.parse(readFileSync(lockPath, 'utf8'));
    const oldDigest = evaluator.files[0].sha256, newDigest = 'd'.repeat(64);
    assert.notEqual(oldDigest, newDigest);
    evaluator.files[0].sha256 = newDigest;
    const nextEvaluator = `${JSON.stringify(evaluator, null, 2)}\n`;
    writeFileSync(lockPath, nextEvaluator);
    item.evaluator_lock_sha256 = sha(nextEvaluator);
    const nextData = readFileSync(dataPath, 'utf8').replace(oldDigest, newDigest);
    writeFileSync(dataPath, nextData);
    item.data_lock_sha256 = sha(nextData);
    assert.throws(() => validatePrivateEvaluatorIncrement(f.root, f.report), /object or unchanged public-entry totals differ/);
  } finally { f.cleanup(); }
});

test('old receipts and core code remain exact; future edits require new evidence', () => {
  const f = copyEvidence();
  try {
    const delivery = f.report.tasks.find(task => task.task_id === 'falcon-m1-emg');
    const deliveryPath = path.join(f.root, delivery.directory, 'delivery-acceptance.json');
    writeFileSync(deliveryPath, readFileSync(deliveryPath, 'utf8') + '\n');
    assert.throws(() => validatePrivateEvaluatorIncrement(f.root, f.report), /old scientific\/public delivery receipts/);
    copyFileSync(path.join(ROOT, delivery.directory, 'delivery-acceptance.json'), deliveryPath);
    const corePath = path.join(f.root, 'src/private-score.ts');
    writeFileSync(corePath, readFileSync(corePath, 'utf8') + '\n');
    assert.throws(() => validatePrivateEvaluatorIncrement(f.root, f.report), /stale core code hash/);
  } finally { f.cleanup(); }
});

test('source compatibility cannot hide an unbound evaluator edit', () => {
  const f = copyEvidence();
  try {
    const file = path.join(f.root, 'src/evaluator.ts');
    writeFileSync(file, readFileSync(file, 'utf8') + '\n// unbound edit\n');
    assert.throws(() => validatePrivateEvaluatorIncrement(f.root), /stale core code hash/);
  } finally { f.cleanup(); }
});
