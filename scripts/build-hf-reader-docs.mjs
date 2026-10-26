#!/usr/bin/env node

// Build reader-facing HF metadata from task guides and a frozen HF catalog.
// This script reads Markdown, catalog JSON, and public manifests only.

import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULT_MANIFEST_ROOT = path.join(ROOT, '.cache/hf-unified-delivery-20261015/metadata');
const SOURCE_BASE = 'https://github.com/NeuroAIHub/BrainPilotBench/blob';
const HF_BASE = 'https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public';
const RETAINED_V0 = new Set(['bciciv-2a', 'sleep-edf', 'tops-fmri', 'neuro-rsc-place-cell']);
const LEGACY_CONTRACTS = {
  'bciciv-2a': {
    evidence: ['(B, 22, 512)', 'returning `torch.Size([2, 4])`', 'session T (230/58 stratified train/val split, seed=42)', 'private session E (288 trials)', '**score** = `mean_kappa` clipped to `[0,1]`'],
    table: '| Field | Task contract |\n|---|---|\n| Input | Cue-relative, 4–38 Hz motor-imagery EEG: `(B, 22, 512)` at 128 Hz. |\n| Output | Four-class `MIAgentModel` prediction: left hand, right hand, feet, or tongue. |\n| Split | Session T has a 230/58 stratified train/valid split per subject. Private session E has 288 trials per subject. |\n| Metric | Mean Cohen’s kappa across nine subjects; the leaderboard `score` clips `mean_kappa` to `[0,1]`. |',
  },
  'sleep-edf': {
    evidence: ['(B, 1, 3000)', '5 sleep stages (Wake / N1 / N2 / N3 / REM)', 'subjects 0-13 with subjects 14-15 for early stopping', 'then predicts every 30 s epoch on subjects 16-19', '**score** = `test_kappa` clipped to `[0,1]`'],
    table: '| Field | Task contract |\n|---|---|\n| Input | Fpz-Cz sleep EEG: a 30-second, 100 Hz epoch shaped `(B, 1, 3000)`. |\n| Output | One of five sleep stages: Wake, N1, N2, N3, or REM. |\n| Split | Subjects 0–13 train the model; 14–15 support early stopping; 16–19 are private Test. |\n| Metric | `test_kappa` across subjects 16–19; the leaderboard `score` clips it to `[0,1]`. |',
  },
  'tops-fmri': {
    evidence: ['279 ROI / 38781 edge functional-connectivity signature', 'public **Study3** fMRI dynamic-FC data', 'Study4 Pearson r (per condition) + Study5 AUC (per site)', '`score = 0.5·study4_score + 0.5·study5_score`'],
    table: '| Field | Task contract |\n|---|---|\n| Input | Public Study3 fMRI dynamic functional connectivity: 279 ROIs, 38,781 edges, and pain ratings. |\n| Output | A linear connectivity signature with saved weights and a NumPy inference script. |\n| Evaluation | Study3 supports public development. Private Study4 and Study5 supply external evaluation labels. |\n| Metric | `score = 0.5·study4_score + 0.5·study5_score`; Study4 uses Pearson `r`, and Study5 uses AUC. |',
  },
  'neuro-rsc-place-cell': {
    evidence: ['mouse retrosplenial cortex Ca²⁺ imaging + VR belt behavior', 'produces `benchmark_summary.json` + `report.md` + `figures/*.png`', '`place_cell_ratio_ok`, `decoding_significance_ok`, and `decoding_error_within_tolerance`', 'The human dimensions are reported separately'],
    table: '| Field | Task contract |\n|---|---|\n| Input | Mouse retrosplenial cortex Ca²⁺ imaging and virtual-reality belt behavior. |\n| Output | `benchmark_summary.json`, `report.md`, and `figures/*.png`. |\n| Evaluation | A deterministic check compares the summary with a frozen reference. Human review scores the report and figures separately. |\n| Metric | Equal-weight mean of `place_cell_ratio_ok`, `decoding_significance_ok`, and `decoding_error_within_tolerance`. Human dimensions do not enter this score. |',
  },
};

function fail(message) {
  throw new Error(message);
}

export function parseArgs(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    if (flag === '--working-draft') {
      options.workingDraft = true;
      continue;
    }
    if (!['--source-revision', '--catalog-input', '--output', '--manifest-root', '--repo-root'].includes(flag)) {
      fail(`Unknown option: ${flag}`);
    }
    if (!argv[i + 1] || argv[i + 1].startsWith('--')) fail(`Missing value for ${flag}`);
    const key = {
      '--source-revision': 'sourceRevision',
      '--catalog-input': 'catalogInput',
      '--output': 'output',
      '--manifest-root': 'manifestRoot',
      '--repo-root': 'repoRoot',
    }[flag];
    options[key] = argv[++i];
  }
  if (!options.catalogInput || !options.output) {
    fail('Required: --catalog-input FROZEN_CATALOG.jsonl --output NEW_DIRECTORY');
  }
  if (Boolean(options.sourceRevision) === Boolean(options.workingDraft)) {
    fail('Use exactly one of --source-revision 40_HEX_SHA or --working-draft');
  }
  if (options.sourceRevision && !/^[a-f0-9]{40}$/i.test(options.sourceRevision)) {
    fail('--source-revision must be the actual published 40-character source commit SHA');
  }
  return options;
}

function readJson(file) {
  return JSON.parse(readFileSync(file, 'utf8'));
}

function cleanText(markdown) {
  return markdown
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/[`*]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function isNavOrMetadata(line) {
  return /^\s*(?:\[[^\]]+\]\([^)]*\)\s*(?:[·|]|$)|Category:|Domain:|Version:|Source experiment:|Task ID:|<a\s)/i.test(line);
}

function paragraphsFromLines(lines) {
  const paragraphs = [];
  let current = [];
  let fenced = false;
  let admonition = false;
  let list = false;
  function flush() {
    if (current.length) paragraphs.push(current.join(' ').replace(/\s+/g, ' ').trim());
    current = [];
  }
  for (const raw of lines) {
    const line = raw.trim();
    if (/^(```|~~~)/.test(line)) { fenced = !fenced; flush(); continue; }
    if (fenced) continue;
    if (!line) { flush(); admonition = false; list = false; continue; }
    if (/^>\s*\[!\w+\]/.test(line)) { flush(); admonition = true; continue; }
    if (admonition && /^>/.test(line)) continue;
    if (admonition) admonition = false;
    if (/^(?:[-*+]\s|\d+\.\s)/.test(line)) { flush(); list = true; continue; }
    if (list) continue;
    if (/^(?:#{1,6}\s|\||[-*+]\s|\d+\.\s|<details|<summary|<\/details|<!--)/.test(line) || isNavOrMetadata(line)) {
      flush();
      continue;
    }
    const prose = line.replace(/^>\s?/, '');
    if (/^\*\*Agent benchmark results:/.test(prose)) { flush(); continue; }
    current.push(prose);
  }
  flush();
  return paragraphs.filter((p) => cleanText(p).length >= 35);
}

function sectionLines(lines, heading) {
  const start = lines.findIndex((line) => new RegExp(`^## ${heading}\\s*$`, 'i').test(line));
  if (start < 0) return [];
  let end = lines.findIndex((line, index) => index > start && /^##\s/.test(line));
  if (end < 0) end = lines.length;
  return lines.slice(start + 1, end);
}

function markdownTables(lines) {
  const tables = [];
  let current = [];
  for (const line of lines) {
    if (/^\|.*\|\s*$/.test(line.trim())) current.push(line.trim());
    else if (current.length) { if (current.length >= 3 && /^\|[\s:|-]+\|$/.test(current[1])) tables.push(current.join('\n')); current = []; }
  }
  if (current.length >= 3 && /^\|[\s:|-]+\|$/.test(current[1])) tables.push(current.join('\n'));
  return tables;
}

export function extractReaderContent(readme, taskId) {
  const lines = readme.replace(/\r\n/g, '\n').split('\n');
  const heading = lines.find((line) => /^#\s+\S/.test(line));
  if (!heading) fail(`${taskId}: source README has no title`);
  const title = cleanText(heading.replace(/^#\s+/, ''));
  const firstSection = lines.findIndex((line) => /^##\s/.test(line));
  let paragraphs = paragraphsFromLines(lines.slice(lines.indexOf(heading) + 1, firstSection < 0 ? lines.length : firstSection));
  let sourceSection = 'README lead';
  // The retained v0 cards draw their description from the existing task section.
  if (RETAINED_V0.has(taskId)) {
    sourceSection = 'What the agent does';
    const taskParagraph = paragraphsFromLines(sectionLines(lines, 'What the agent does'))[0];
    if (!taskParagraph) fail(`${taskId}: no task description under What the agent does`);
    if (taskId === 'neuro-rsc-place-cell') {
      if (!/5 sub-analyses on RSC place-cell dynamics/.test(taskParagraph)) {
        fail(`${taskId}: source task description changed; review its reader introduction`);
      }
      paragraphs = ['The agent performs five analyses of RSC place-cell dynamics using the staged recording.'];
    } else {
      const sentence = taskParagraph
        .replace(/\s*The submitted file goes to:\s*$/i, '')
        .replace(/,?\s*then submit:\s*$/i, '')
        .replace(/^Design a /, 'The agent designs a ')
        .replace(/^Train a /, 'The agent trains a ')
        .trim();
      paragraphs = [/\.$/.test(sentence) ? sentence : `${sentence}.`];
    }
  }
  if (!paragraphs.length) fail(`${taskId}: no reader-facing introduction in source README`);
  const intro = paragraphs.slice(0, RETAINED_V0.has(taskId) ? 1 : 2).join('\n\n');
  const plain = cleanText(intro);
  if (plain.length < 55 || /^(?:Only public|From the repository root|The fetch command|Category:)/i.test(plain)) {
    fail(`${taskId}: introduction is too short or technical; add a scientific lead to the source README`);
  }
  const atGlance = markdownTables(sectionLines(lines, 'Task at a glance'));
  const splitSections = ['Data and split', 'Source and split', 'Split and score'];
  const splitTables = splitSections.flatMap((name) => markdownTables(sectionLines(lines, name)))
    .filter((table) => /\|\s*(?:Role|Split)\s*\|/i.test(table.split('\n')[0]));
  const tables = [...atGlance, ...splitTables];
  if (RETAINED_V0.has(taskId)) {
    const contract = LEGACY_CONTRACTS[taskId];
    const source = readme.replace(/\s+/g, ' ');
    for (const evidence of contract.evidence) {
      if (!source.includes(evidence)) fail(`${taskId}: source contract changed near ${evidence}; review the HF table`);
    }
    tables.unshift(contract.table);
  }
  return { title, intro, plain, sourceSection, tables: [...new Set(tables)] };
}

function sourceUrl(sourceDir, target, sourceRevision) {
  if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(target)) return target;
  if (target.startsWith('#')) return `${SOURCE_BASE}/${sourceRevision}/${sourceDir}/README.md${target}`;
  const [localPath, fragment = ''] = target.split('#', 2);
  const relative = path.posix.normalize(path.posix.join(sourceDir, localPath));
  if (relative === '..' || relative.startsWith('../') || path.posix.isAbsolute(relative)) {
    fail(`Unsafe relative link in ${sourceDir}/README.md: ${target}`);
  }
  return `${SOURCE_BASE}/${sourceRevision}/${relative}${fragment ? `#${fragment}` : ''}`;
}

export function pinMarkdownLinks(markdown, sourceDir, sourceRevision) {
  return markdown.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, target) => {
    const [url, optionalTitle = ''] = target.trim().split(/\s+(?=")/, 2);
    return `[${label}](${sourceUrl(sourceDir, url, sourceRevision)}${optionalTitle ? ` ${optionalTitle}` : ''})`;
  });
}

function replaceReaderFields(rawLine, changes, taskId) {
  const original = JSON.parse(rawLine);
  let changed = rawLine;
  const fields = [
    ['summary', /"summary"\s*:\s*"(?:\\.|[^"\\])*"/g],
    ['protocol_url', /"protocol_url"\s*:\s*"(?:\\.|[^"\\])*"/g],
  ];
  for (const [field, pattern] of fields) {
    const matches = [...changed.matchAll(pattern)];
    if (matches.length !== 1) fail(`${taskId}: expected exactly one JSON ${field} field`);
    const token = matches[0][0];
    const colon = token.indexOf(':');
    const replacement = token.slice(0, colon + 1) + token.slice(colon + 1).match(/^\s*/)[0] + JSON.stringify(changes[field]);
    changed = changed.slice(0, matches[0].index) + replacement + changed.slice(matches[0].index + token.length);
  }
  const updated = JSON.parse(changed);
  const expected = { ...original, ...changes };
  if (JSON.stringify(updated) !== JSON.stringify(expected)) fail(`${taskId}: catalog update changed another field`);
  return changed;
}

function readCatalogLines(file) {
  const text = readFileSync(file, 'utf8');
  if (!text.endsWith('\n')) fail('Frozen HF catalog must end with a newline');
  const lines = text.split('\n').slice(0, -1);
  if (lines.some((line) => !line.trim())) fail('Frozen HF catalog contains a blank row');
  return lines;
}

function buildCard({ task, row, manifest, reader, sourceRevision }) {
  const sourceDir = task.directory.replaceAll(path.sep, '/');
  const pinnedGuide = `${SOURCE_BASE}/${sourceRevision}/${sourceDir}/README.md`;
  const intro = pinMarkdownLinks(reader.intro, sourceDir, sourceRevision);
  const tables = reader.tables.map((table) => pinMarkdownLinks(table, sourceDir, sourceRevision));
  const status = row.agent_results === 'historical_v0_only'
    ? 'Historical Agent results for this retained task are recorded in the v0 report.'
    : 'Agent benchmark results are not yet available.';
  const access = manifest.access === 'source_only'
    ? `This task uses source download and local preparation. No H1 source or derived arrays are hosted here. Read the [source agreement](${manifest.source_reference}) before download.`
    : `The [public folder](${HF_BASE}/tree/main/tasks/${row.data_category}/${row.task_id}/public) contains ${manifest.public_file_count} ${manifest.public_file_count === 1 ? 'file' : 'files'} (${manifest.public_bytes.toLocaleString('en-US')} bytes). The [manifest](manifest.json) lists each path, byte count, and SHA-256 digest.`;
  const filmBoundary = row.task_id === 'ieeg-film-speech-music'
    ? 'The public package supports Agent preparation. Block-first scoring requires the trusted evaluator’s owner mapping. That mapping is not public.\n\n'
    : '';
  const sourceLabel = manifest.source_reference.startsWith(`${SOURCE_BASE}/`)
    ? 'Frozen source record'
    : 'Source record';
  const tableText = tables.length ? `## Task at a glance\n\n${tables.join('\n\n')}\n\n` : '';
  return `# ${reader.title}\n\n${intro}\n\n${status}\n\n${tableText}## Data access\n\n${access}\n\n${filmBoundary}${manifest.license_notice}\n\n## Protocol and source\n\nThe [versioned task guide](${pinnedGuide}) defines the scientific protocol, preparation, and scoring.\n\n[${sourceLabel}](${manifest.source_reference}) · [Source attribution](../../../ATTRIBUTION.md)\n`;
}

export function buildReaderDocs(options) {
  const root = path.resolve(options.repoRoot ?? ROOT);
  const catalogInput = path.resolve(options.catalogInput);
  const manifestRoot = path.resolve(options.manifestRoot ?? path.join(root, path.relative(ROOT, DEFAULT_MANIFEST_ROOT)));
  const output = path.resolve(options.output);
  if (existsSync(output)) fail(`Output already exists: ${output}`);
  if (output === root || root.startsWith(`${output}${path.sep}`)) fail('Output must be a new task-specific directory');
  const sourceRevision = options.sourceRevision ?? execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
  if (!/^[a-f0-9]{40}$/i.test(sourceRevision)) fail('Could not resolve a 40-character source commit SHA');
  if (!options.workingDraft) {
    let objectType;
    try {
      objectType = execFileSync('git', ['cat-file', '-t', sourceRevision], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
    } catch {
      fail(`Source revision ${sourceRevision} is not available in the local repository`);
    }
    if (objectType !== 'commit') fail(`Source revision ${sourceRevision} is not a commit`);
    const currentCatalog = readFileSync(path.join(root, 'tasks/catalog.json'));
    let committedCatalog;
    try {
      committedCatalog = execFileSync('git', ['show', `${sourceRevision}:tasks/catalog.json`], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch {
      fail(`Task catalog is absent from source revision ${sourceRevision}`);
    }
    if (!currentCatalog.equals(committedCatalog)) {
      fail(`Working task catalog differs from source revision ${sourceRevision}; publish the final catalog first`);
    }
  }
  // Local source-only additions do not silently expand the frozen HF delivery.
  // Their guides are checked separately; publication requires a new HF snapshot.
  const tasks = readJson(path.join(root, 'tasks/catalog.json')).tasks.filter((task) =>
    task.entry_kind === 'runnable' && !(task.data_status === 'source_prepared_role_separated' &&
      task.hosted_data_availability !== 'published_public_snapshot'));
  if (!tasks.length) fail('No tasks belong to the frozen HF delivery');
  const taskMap = new Map(tasks.map((task) => [task.task_id, task]));
  if (taskMap.size !== tasks.length) fail('Task catalog has duplicate runnable IDs');
  const rawRows = readCatalogLines(catalogInput);
  if (rawRows.length !== tasks.length) fail(`HF catalog has ${rawRows.length} rows; expected ${tasks.length}`);
  const outputs = [];
  const seen = new Set();
  const updatedRows = [];
  const introductionSources = { 'README lead': 0, 'What the agent does': 0 };
  for (const rawRow of rawRows) {
    const row = JSON.parse(rawRow);
    const task = taskMap.get(row.task_id);
    if (!task || seen.has(row.task_id)) fail(`HF catalog has an unknown or duplicate task ID: ${row.task_id}`);
    seen.add(row.task_id);
    const sourceCategory = task.directory.split('/')[1];
    const expectedCategory = ['intracortical', 'ieeg'].includes(sourceCategory) ? 'invasive' : sourceCategory;
    if (row.data_category !== expectedCategory || row.task_version !== task.task_version) {
      fail(`${row.task_id}: frozen HF category or task version disagrees with the tracked task catalog`);
    }
    const directory = `tasks/${row.data_category}/${row.task_id}`;
    const manifest = readJson(path.join(manifestRoot, directory, 'manifest.json'));
    if (manifest.task_id !== row.task_id || manifest.data_category !== row.data_category ||
        manifest.task_version !== row.task_version || manifest.access !== row.access ||
        manifest.public_file_count !== row.public_file_count || manifest.public_bytes !== row.public_bytes ||
        manifest.private_evaluation_data_included !== false) {
      fail(`${row.task_id}: frozen HF row and public manifest disagree`);
    }
    const readmePath = path.join(root, task.directory, 'README.md');
    const readmeBytes = readFileSync(readmePath);
    if (!options.workingDraft) {
      let committedBytes;
      try {
        committedBytes = execFileSync('git', ['show', `${sourceRevision}:${task.directory}/README.md`], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
      } catch {
        fail(`${row.task_id}: README is absent from source revision ${sourceRevision}`);
      }
      if (!readmeBytes.equals(committedBytes)) {
        fail(`${row.task_id}: working README differs from source revision ${sourceRevision}; commit and publish the final guide first`);
      }
    }
    const reader = extractReaderContent(readmeBytes.toString('utf8'), row.task_id);
    introductionSources[reader.sourceSection] += 1;
    const protocolUrl = `${SOURCE_BASE}/${sourceRevision}/${task.directory}/README.md`;
    updatedRows.push(replaceReaderFields(rawRow, { summary: reader.plain, protocol_url: protocolUrl }, row.task_id));
    outputs.push({ relative: `${directory}/README.md`, content: buildCard({ task, row, manifest, reader, sourceRevision }) });
  }
  if (seen.size !== taskMap.size) fail('HF catalog does not cover every runnable task');
  mkdirSync(output);
  writeFileSync(path.join(output, 'catalog.jsonl'), `${updatedRows.join('\n')}\n`);
  for (const { relative, content } of outputs) {
    const destination = path.join(output, relative);
    mkdirSync(path.dirname(destination), { recursive: true });
    writeFileSync(destination, content);
  }
  return { tasks: outputs.length, files: outputs.length + 1, introductionSources, output, sourceRevision, workingDraft: Boolean(options.workingDraft) };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = buildReaderDocs(parseArgs(process.argv.slice(2)));
    process.stdout.write(`${JSON.stringify(result)}\n`);
    if (result.workingDraft) process.stderr.write('Working-draft preview: source links point to HEAD, not uncommitted README edits.\n');
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
