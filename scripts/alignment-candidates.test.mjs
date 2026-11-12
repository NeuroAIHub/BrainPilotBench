/** Planning registries must not inflate counts or bypass candidate acceptance. */
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import { readAlignmentCandidates } from './alignment-candidates.mjs';

function registry(t) {
  const root = mkdtempSync(join(tmpdir(), 'bpb-alignment-registry-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const dir = join(root, 'tasks/alignment/brainscore');
  mkdirSync(dir, { recursive: true });
  for (const name of ['sources', 'candidates', 'instances']) {
    writeFileSync(join(dir, `${name}.json`), JSON.stringify({
      schema: `bpb-bs-${name}/1`, ...(name === 'instances' ? { instances: [{ status: 'planned' }] } : {}),
    }));
  }
  return { root, dir };
}

test('repository plans add no task candidates', () => {
  const entries = readAlignmentCandidates(resolve(import.meta.dirname, '..'));
  assert.deepEqual(entries.map(e => e.card.id), ['alignment-pereira2018-analysis']);
});

test('planning registry is excluded, unknown incomplete task folders still fail', t => {
  const { root } = registry(t);
  assert.deepEqual(readAlignmentCandidates(root), []);
  mkdirSync(join(root, 'tasks/alignment/incomplete-task'));
  assert.throws(() => readAlignmentCandidates(root), /candidate.json/);
});

test('a registry cannot declare its instances ready', t => {
  const { root, dir } = registry(t);
  writeFileSync(join(dir, 'instances.json'), JSON.stringify({
    schema: 'bpb-bs-instances/1', instances: [{ status: 'ready' }],
  }));
  assert.throws(() => readAlignmentCandidates(root), /invalid planning registry/);
});

test('a registry task.yaml cannot bypass real-data acceptance', t => {
  const { root, dir } = registry(t);
  writeFileSync(join(dir, 'task.yaml'), '{}');
  assert.throws(() => readAlignmentCandidates(root), /cannot be runnable/);
});
