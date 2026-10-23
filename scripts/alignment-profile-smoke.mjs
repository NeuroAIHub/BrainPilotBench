/** Offline stdlib fixtures + actual MCP stdio + the benchmark CLI. No downloads. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { discoverTaskDirs } from '../dist/discover.js';

const root = resolve(import.meta.dirname, '..');
const task = join(root, 'tasks/_example/alignment-profile-synthetic');
const temp = mkdtempSync(join(tmpdir(), 'bpb-profile-smoke-'));
const workspace = join(temp, 'workspace'), runs = join(temp, 'runs'), bundle = join(runs, 'fixture');
const evidence = join(temp, 'operator-evidence');
const python = process.env.BPB_ALIGNMENT_PROFILE_PYTHON || 'python3';
const env = { ...process.env, BPB_NO_PROXY: '1', PYTHONDONTWRITEBYTECODE: '1', BPB_ALIGNMENT_PROFILE_PYTHON: python };
delete env.BPB_ALIGNMENT_PROFILE_EVIDENCE_DIR;
function run(executable, args, extraEnv = {}, status = 0) {
  const result = spawnSync(executable, args, { cwd: root, env: { ...env, ...extraEnv }, encoding: 'utf8', timeout: 30000 });
  assert.equal(result.status, status, `${executable} ${args.join(' ')}\n${result.stdout}\n${result.stderr}`);
  return result.stdout;
}
const cli = (args, extra = {}, status = 0) => run(process.execPath, [join(root, 'dist/cli.js'), ...args], extra, status);
try {
  assert.ok(!discoverTaskDirs([join(root, 'tasks')]).includes(task));
  cli(['prepare', 'alignment-profile-synthetic', '--workspace', workspace]);
  assert.ok(existsSync(join(workspace, 'PROFILE_CONTEXT.json')));
  assert.ok(!existsSync(join(workspace, 'packet.json')));
  const contextPath = join(workspace, 'PROFILE_CONTEXT.json');
  const context = JSON.parse(readFileSync(contextPath, 'utf8'));
  assert.equal(context.protocol_id, 'synthetic-profile-descriptive-v2');
  writeFileSync(contextPath, JSON.stringify({ ...context, protocol_id: 'synthetic-profile-descriptive-v1' }));
  cli(['prepare', 'alignment-profile-synthetic', '--workspace', workspace], {}, 1);
  assert.equal(JSON.parse(readFileSync(contextPath, 'utf8')).protocol_id, 'synthetic-profile-descriptive-v1');
  writeFileSync(contextPath, JSON.stringify(context));
  cli(['prepare', 'alignment-profile-synthetic', '--workspace', workspace]);
  cli(['run', 'alignment-profile-synthetic', '--adapter', 'manual', '--agent', 'synthetic-scripted-baseline', '--workspace', workspace, '--out', runs, '--run-id', 'fixture']);
  mkdirSync(evidence);
  run(python, ['-B', join(task, 'lib/fixtures.py'), '--output', join(evidence, 'packet.json')]);
  run(python, ['-B', join(task, 'solution/reference_report.py'), '--packet', join(evidence, 'packet.json'), '--journal', join(evidence, 'journal.jsonl'), '--output', workspace]);
  cli(['run', 'alignment-profile-synthetic', '--adapter', 'manual', '--resume', bundle]);
  cli(['submit', 'verify', bundle]);
  cli(['score', bundle], { BPB_ALIGNMENT_PROFILE_EVIDENCE_DIR: evidence });
  const report = JSON.parse(readFileSync(join(bundle, 'alignment-profile-score.json'), 'utf8'));
  assert.equal(report.profile_analysis_success, 1, JSON.stringify(report));
  assert.equal(report.question_results.length, 4);
  assert.equal(report.synthetic_only, true);
  assert.equal(JSON.parse(readFileSync(join(bundle, 'meta.json'), 'utf8')).taskVersion, '0.2');
  const answers = JSON.parse(readFileSync(join(bundle, 'artifacts/answers.json'), 'utf8'));
  assert.equal(answers.schema, 'bpb-profile-answers/2');
  assert.deepEqual(answers.questions.q3.answer.scope, ['observed_subjects']);
  assert.equal(answers.questions.q4.answer.advantage_conclusion, 'advantage_retained');
  assert.equal(answers.questions.q4.answer.scope, 'same_subjects_new_material');
  assert.ok(!existsSync(join(bundle, 'artifacts/journal.jsonl')));
  const tables = JSON.parse(cli(['leaderboard', runs, '--format', 'json']));
  const cell = tables.flatMap(t => t.rows).flatMap(r => r.cells).find(c => c.metric === 'profile_analysis_success');
  assert.equal(cell.value, 1);
  cli(['validate', 'alignment-profile-synthetic', '--schema-only']);
  rmSync(join(bundle, 'artifacts/answers.json'));
  cli(['submit', 'verify', bundle], {}, 1);
  console.log('Profile fixture: MCP + prepare/manual/resume/verify/score/leaderboard passed. Four questions verified.');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
