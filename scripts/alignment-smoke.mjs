/** Real CLI lifecycle with locally generated arrays; never fetch, install, pull or call a model. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { discoverTaskDirs } from '../dist/discover.js';

const root = resolve(import.meta.dirname, '..');
const temp = mkdtempSync(join(tmpdir(), 'bpb-alignment-cli-'));
const workspace = join(temp, 'workspace');
const runs = join(temp, 'runs');
const bundle = join(runs, 'synthetic-smoke');
const python = process.env.BPB_ALIGNMENT_PYTHON || 'python3';
const env = { ...process.env, BPB_ALIGNMENT_PYTHON: python, BPB_ALIGNMENT_TRUSTED_LOCAL: '1',
              BPB_OFFICIAL_SCORING: '0', BPB_SUBMISSION_ISOLATION: 'process', BPB_NO_PROXY: '1', PYTHONDONTWRITEBYTECODE: '1',
              OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1' };
function run(exe, args, expected = 0) {
  const r = spawnSync(exe, args, { cwd: root, env, encoding: 'utf8', timeout: 120000 });
  assert.equal(r.status, expected, `${exe} ${args.join(' ')}\n${r.stdout}\n${r.stderr}`);
  return r.stdout;
}
const cli = args => run(process.execPath, [join(root, 'dist/cli.js'), ...args]);
try {
  const dirs = discoverTaskDirs([join(root, 'tasks')]);
  assert.ok(!dirs.some(d => d.includes('alignment')));
  cli(['prepare', 'alignment-synthetic', '--workspace', workspace]);
  cli(['prepare', 'alignment-synthetic', '--workspace', workspace]); // intact packet is idempotent
  assert.ok(existsSync(join(workspace, 'inputs/manifest.json')));
  assert.ok(!existsSync(join(workspace, 'submission/analyze.py'))); // setup does not hand out solution
  cli(['run', 'alignment-synthetic', '--adapter', 'manual', '--agent', 'synthetic-reference-not-agent-benchmark',
       '--workspace', workspace, '--out', runs, '--run-id', 'synthetic-smoke']);
  mkdirSync(join(workspace, 'submission'));
  cpSync(join(root, 'tasks/_example/alignment-synthetic/solution/analyze.py'), join(workspace, 'submission/analyze.py'));
  cpSync(join(root, 'tasks/alignment/_shared/contract.py'), join(workspace, 'submission/alignment_contract.py'));
  run(python, ['-B', join(workspace, 'submission/analyze.py'), '--inputs', join(workspace, 'inputs'), '--output', workspace]);
  cli(['run', 'alignment-synthetic', '--adapter', 'manual', '--resume', bundle]);
  cli(['submit', 'verify', bundle]);
  cli(['score', bundle, '--isolation', 'process']);
  const report = JSON.parse(readFileSync(join(bundle, 'alignment-score.json'), 'utf8'));
  assert.equal(report.analysis_success, 1, JSON.stringify(report));
  assert.equal(report.status, 'scored');
  assert.equal(report.synthetic_only, true);
  const meta = JSON.parse(readFileSync(join(bundle, 'meta.json'), 'utf8'));
  assert.equal(meta.taskVersion, '0.1');
  assert.ok(!existsSync(join(bundle, 'artifacts/inputs')));
  const board = cli(['leaderboard', runs, '--format', 'json']);
  assert.equal(JSON.parse(board)[0].rows[0].cells[0].metric, 'analysis_success');
  assert.equal(JSON.parse(board)[0].rows[0].cells[0].value, 1);
  assert.match(board, /synthetic-reference-not-agent-benchmark/);
  console.log(board.trim());
  cli(['validate', 'alignment-synthetic', '--schema-only']);
  cli(['validate', 'alignment-synthetic']);
  // Missing artifacts must be blocked before invoking the scorer.
  rmSync(join(bundle, 'artifacts/report.md'));
  const invalid = spawnSync(process.execPath, [join(root, 'dist/cli.js'), 'submit', 'verify', bundle],
                            { cwd: root, env, encoding: 'utf8', timeout: 10000 });
  assert.notEqual(invalid.status, 0);
  console.log('Alignment synthetic CLI lifecycle passed; no real-data/Agent results retained.');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
