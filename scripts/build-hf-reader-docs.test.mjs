import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { buildReaderDocs, extractReaderContent, parseArgs, pinMarkdownLinks } from './build-hf-reader-docs.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASELINE = path.join(ROOT, '.cache/reader-docs-20261016/hf-baseline/catalog.jsonl');
const CATALOG = path.join(ROOT, 'tasks/catalog.json');

function makeMetadataFixture(scratch) {
  const tasks = JSON.parse(readFileSync(CATALOG, 'utf8')).tasks.filter((item) => item.entry_kind === 'runnable');
  const manifestRoot = path.join(scratch, 'manifests');
  const catalogInput = path.join(scratch, 'catalog.jsonl');
  const rows = [];
  for (const task of tasks) {
    const category = ['intracortical', 'ieeg'].includes(task.directory.split('/')[1])
      ? 'invasive'
      : task.directory.split('/')[1];
    const access = task.task_id === 'falcon-h1-reach-grasp' ? 'source_only' : 'hosted_public';
    const fileCount = access === 'source_only' ? 0 : 1;
    const bytes = fileCount * 17;
    const sourceReference = task.task_id === 'psych101-lefebvre2017behavioural-exp1'
      ? `https://github.com/NeuroAIHub/BrainPilotBench/blob/${'1'.repeat(40)}/${task.directory}/README.md`
      : `https://example.org/source/${task.task_id}`;
    const row = {
      access, agent_results: ['bciciv-2a', 'sleep-edf', 'tops-fmri', 'neuro-rsc-place-cell'].includes(task.task_id)
        ? 'historical_v0_only' : 'not_yet_available',
      collection: 'v1', data_category: category, public_bytes: bytes,
      public_file_count: fileCount, summary: `CSV technical summary for ${task.task_id}`,
      protocol_url: `https://example.org/old-guide/${task.task_id}`,
      source_url: sourceReference, task_id: task.task_id, task_version: task.task_version, title: task.task_id,
    };
    rows.push(JSON.stringify(row));
    const manifest = {
      access, data_category: category, task_id: task.task_id, task_version: task.task_version,
      public_file_count: fileCount, public_bytes: bytes, private_evaluation_data_included: false,
      source_reference: sourceReference, license_notice: 'Original source terms apply.',
    };
    const directory = path.join(manifestRoot, 'tasks', category, task.task_id);
    mkdirSync(directory, { recursive: true });
    writeFileSync(path.join(directory, 'manifest.json'), `${JSON.stringify(manifest)}\n`);
  }
  writeFileSync(catalogInput, `${rows.join('\n')}\n`);
  return { catalogInput, manifestRoot };
}

test('requires a frozen catalog and an exact source revision for publishable output', () => {
  assert.throws(() => parseArgs(['--catalog-input', 'catalog.jsonl', '--output', 'out']), /exactly one/);
  assert.throws(() => parseArgs(['--catalog-input', 'catalog.jsonl', '--output', 'out', '--source-revision', 'main']), /40-character/);
  assert.equal(parseArgs(['--catalog-input', 'catalog.jsonl', '--output', 'out', '--working-draft']).workingDraft, true);
});

test('skips navigation, status admonitions, and technical summaries', () => {
  const sample = `# Choice under uncertainty\n\n[Catalog](../../../README.md) · [Data lock](data.lock)\n\nParticipants choose between two slot machines in four casinos. The agent predicts each recorded choice.\n\n> [!NOTE]\n> Agent benchmark results are not yet available.\n\n## Task at a glance\n\n| Field | Details |\n|---|---|\n| Input | [Public trials](public/train.jsonl) |\n| Output | Choice probability |\n| Metric | Mean response NLL |\n`;
  const result = extractReaderContent(sample, 'sample-task');
  assert.match(result.plain, /Participants choose between two slot machines/);
  assert.doesNotMatch(result.plain, /Catalog|Data lock|benchmark results/);
  assert.match(result.tables[0], /Choice probability/);
  assert.equal(pinMarkdownLinks(result.tables[0], 'tasks/psychology/sample-task', 'a'.repeat(40)).includes(`/blob/${'a'.repeat(40)}/tasks/psychology/sample-task/public/train.jsonl`), true);
  assert.throws(() => extractReaderContent('# Empty\n\n[Catalog](../../../README.md)\n\n> [!NOTE]\n> No results.\n', 'missing-task'), /no reader-facing introduction/);
});

test('the Casino catalog summary is the human task description', () => {
  const readme = readFileSync(path.join(ROOT, 'tasks/psychology/psych101-lefebvre2017behavioural-exp1/README.md'), 'utf8');
  const result = extractReaderContent(readme, 'psych101-lefebvre2017behavioural-exp1');
  assert.match(result.plain, /four casinos.*two slot machines/);
  assert.doesNotMatch(result.plain, /\.csv|task\.yaml|data\.lock|source experiment/i);
});

test('all runnable task guides yield a meaningful introduction', () => {
  const tasks = JSON.parse(readFileSync(CATALOG, 'utf8')).tasks.filter((item) => item.entry_kind === 'runnable');
  assert.equal(tasks.length, 112);
  for (const task of tasks) {
    const readme = readFileSync(path.join(ROOT, task.directory, 'README.md'), 'utf8');
    const result = extractReaderContent(readme, task.task_id);
    assert.ok(result.plain.length >= 55, task.task_id);
    assert.ok(result.tables.length >= 1, `${task.task_id}: missing task contract table`);
    assert.doesNotMatch(result.plain, /\.csv|task\.yaml|data\.lock|\.jsonl|public_data/i, task.task_id);
  }
});

test('retained v0 contract tables trace to literal source-guide facts', () => {
  const sources = [
    ['bciciv-2a', 'tasks/eeg/bciciv-2a/README.md', 'session T (230/58 stratified train/val split, seed=42)', 'mean_kappa'],
    ['sleep-edf', 'tasks/eeg/sleep-edf/README.md', 'subjects 0-13 with subjects 14-15 for early stopping', 'test_kappa'],
    ['tops-fmri', 'tasks/mri/tops-fmri/README.md', 'Study4 Pearson r (per condition) + Study5 AUC (per site)', '0.5·study4_score + 0.5·study5_score'],
    ['neuro-rsc-place-cell', 'tasks/calcium-imaging/neuro-rsc-place-cell/README.md', 'The human dimensions are reported separately', 'decoding_error_within_tolerance'],
  ];
  for (const [taskId, relative, sourceFact, metric] of sources) {
    const readme = readFileSync(path.join(ROOT, relative), 'utf8');
    assert.ok(readme.replace(/\s+/g, ' ').includes(sourceFact), `${taskId}: source fact absent`);
    const contract = extractReaderContent(readme, taskId).tables[0];
    assert.match(contract, /\| Input \|/);
    assert.match(contract, /\| Output \|/);
    assert.match(contract, /\| (?:Split|Evaluation) \|/);
    assert.match(contract, /\| Metric \|/);
    assert.ok(contract.includes(metric), `${taskId}: sourced metric absent`);
  }
  const rsc = readFileSync(path.join(ROOT, 'tasks/calcium-imaging/neuro-rsc-place-cell/README.md'), 'utf8');
  assert.throws(() => extractReaderContent(rsc.replace('The human dimensions are reported separately', 'Human dimensions have changed'), 'neuro-rsc-place-cell'), /source contract changed/);
});

test('build changes only reader fields and creates one card per task', () => {
  const scratch = mkdtempSync(path.join(os.tmpdir(), 'bpb-reader-docs-'));
  try {
    const { catalogInput, manifestRoot } = makeMetadataFixture(scratch);
    const input = readFileSync(catalogInput, 'utf8');
    const output = path.join(scratch, 'preview');
    const result = buildReaderDocs({ repoRoot: ROOT, catalogInput, manifestRoot, output, workingDraft: true });
    assert.equal(result.tasks, 112);
    assert.deepEqual(result.introductionSources, { 'README lead': 108, 'What the agent does': 4 });
    const oldLines = input.trimEnd().split('\n');
    const newLines = readFileSync(path.join(output, 'catalog.jsonl'), 'utf8').trimEnd().split('\n');
    assert.equal(newLines.length, oldLines.length);
    const ids = new Set();
    for (let i = 0; i < oldLines.length; i += 1) {
      const before = JSON.parse(oldLines[i]);
      const after = JSON.parse(newLines[i]);
      ids.add(after.task_id);
      assert.notEqual(after.summary, before.summary, before.task_id);
      const task = JSON.parse(readFileSync(CATALOG, 'utf8')).tasks.find((item) => item.task_id === after.task_id);
      assert.equal(after.protocol_url, `https://github.com/NeuroAIHub/BrainPilotBench/blob/${result.sourceRevision}/${task.directory}/README.md`);
      assert.deepEqual({ ...after, summary: before.summary, protocol_url: before.protocol_url }, before);
      assert.equal(after.task_version, before.task_version);
      const mask = (line) => line
        .replace(/"summary"\s*:\s*"(?:\\.|[^"\\])*"/, '"summary":"MASK"')
        .replace(/"protocol_url"\s*:\s*"(?:\\.|[^"\\])*"/, '"protocol_url":"MASK"');
      assert.equal(mask(newLines[i]), mask(oldLines[i]), before.task_id);
      const directory = path.join(output, 'tasks', after.data_category, after.task_id);
      assert.deepEqual(readdirSync(directory), ['README.md']);
      const card = readFileSync(path.join(directory, 'README.md'), 'utf8');
      assert.match(card, /^# .+\n\n/m);
      assert.ok(card.indexOf(after.agent_results === 'historical_v0_only' ? 'Historical Agent results' : 'Agent benchmark results') < card.indexOf('## Data access'));
      assert.match(card, /## Task at a glance/);
      assert.ok(card.indexOf(after.agent_results === 'historical_v0_only' ? 'Historical Agent results' : 'Agent benchmark results') < card.indexOf('## Task at a glance'));
      assert.match(card, /## Data access/);
      assert.match(card, /## Protocol and source/);
      assert.doesNotMatch(card, /\b1 files\b/);
      if (after.task_id === 'ieeg-film-speech-music') {
        assert.match(card, /Block-first scoring requires the trusted evaluator’s owner mapping/);
        assert.match(card, /That mapping is not public/);
      }
      if (after.task_id === 'falcon-h1-reach-grasp') {
        assert.match(card, /No H1 source or derived arrays are hosted here/);
        assert.doesNotMatch(card, /\[public folder\]/);
      }
      if (after.task_id === 'psych101-lefebvre2017behavioural-exp1') {
        assert.match(card, /\[Frozen source record\]/);
      }
    }
    assert.equal(ids.size, 112);
    assert.deepEqual(readdirSync(output).sort(), ['catalog.jsonl', 'tasks']);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test('publish mode rejects a revision that is not a local commit', () => {
  const output = path.join(os.tmpdir(), `bpb-reader-invalid-${process.pid}-${Date.now()}`);
  const scratch = mkdtempSync(path.join(os.tmpdir(), 'bpb-reader-invalid-metadata-'));
  try {
    const { catalogInput, manifestRoot } = makeMetadataFixture(scratch);
    assert.throws(() => buildReaderDocs({ repoRoot: ROOT, catalogInput, manifestRoot, output, sourceRevision: 'f'.repeat(40) }), /not available in the local repository/);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test('local frozen HF catalog keeps fields outside summary and protocol_url', { skip: !existsSync(BASELINE) }, () => {
  const scratch = mkdtempSync(path.join(os.tmpdir(), 'bpb-reader-frozen-'));
  try {
    const output = path.join(scratch, 'preview');
    const manifestRoot = path.join(ROOT, '.cache/hf-unified-delivery-20261015/metadata');
    const input = readFileSync(BASELINE, 'utf8').trimEnd().split('\n');
    buildReaderDocs({ repoRoot: ROOT, catalogInput: BASELINE, manifestRoot, output, workingDraft: true });
    const updated = readFileSync(path.join(output, 'catalog.jsonl'), 'utf8').trimEnd().split('\n');
    assert.equal(updated.length, input.length);
    for (let i = 0; i < input.length; i += 1) {
      const mask = (line) => line
        .replace(/"summary"\s*:\s*"(?:\\.|[^"\\])*"/, '"summary":"MASK"')
        .replace(/"protocol_url"\s*:\s*"(?:\\.|[^"\\])*"/, '"protocol_url":"MASK"');
      assert.equal(mask(updated[i]), mask(input[i]));
      const before = JSON.parse(input[i]);
      const after = JSON.parse(updated[i]);
      assert.equal(after.source_url, before.source_url);
      assert.equal(after.task_version, before.task_version);
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test('build fails before output when one source introduction is absent', () => {
  const catalog = JSON.parse(readFileSync(CATALOG, 'utf8'));
  const sourceTask = catalog.tasks.find((item) => item.task_id === 'psych101-lefebvre2017behavioural-exp1');
  const source = path.join(ROOT, sourceTask.directory, 'README.md');
  const original = readFileSync(source, 'utf8');
  const missing = original.replace(/Participants visit four casinos[^\n]+\n/, '');
  assert.throws(() => extractReaderContent(missing, sourceTask.task_id), /no reader-facing introduction/);
});
