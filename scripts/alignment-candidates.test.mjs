/** Planning registries must not inflate counts or bypass candidate acceptance. */
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import { alignmentCatalogRow, readAlignmentCandidates } from './alignment-candidates.mjs';

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

test('the catalog lists each staged alignment protocol once across its model variants', () => {
  const entries = readAlignmentCandidates(resolve(import.meta.dirname, '..'));
  const metrics = [
    ['alignment-l1-cell-tuning', 'unit_tuning_r', 'correlation'],
    ['alignment-l2-unit-transfer', 'search_delta_r', 'correlation'],
    ['alignment-l3-circuit-paths', 'path_specific_gain', 'nat'],
    ['alignment-l4-network-edges', 'network_edge_r', 'correlation'],
  ];
  assert.deepEqual(entries.map(e => e.card.id).sort(), [...metrics.map(row => row[0]), 'alignment-pereira2018-analysis']);
  for (const [id, metric, unit] of metrics) {
    const task = alignmentCatalogRow(entries.find(e => e.card.id === id));
    assert.equal(task.preparation_available, true);
    assert.deepEqual(task.primary_metric, { id: metric, direction: 'maximize', unit });
  }
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

test('grouped source tasks and their subtasks both require planned status', t => {
  const { root, dir } = registry(t);
  const grouped = { schema: 'bpb-bs-instances/2', instances: [{ status: 'planned' }], subtasks: [{ status: 'planned' }] };
  writeFileSync(join(dir, 'instances.json'), JSON.stringify(grouped));
  assert.deepEqual(readAlignmentCandidates(root), []);
  grouped.subtasks[0].status = 'ready';
  writeFileSync(join(dir, 'instances.json'), JSON.stringify(grouped));
  assert.throws(() => readAlignmentCandidates(root), /invalid planning registry/);
});
