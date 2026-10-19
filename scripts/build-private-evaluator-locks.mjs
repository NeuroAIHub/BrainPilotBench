#!/usr/bin/env node
/** Bind the verified private HF upload to task data.lock and evaluator.lock metadata. */
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PLAN_PATH = join(ROOT, '.cache/hf-private-preparation-20261019/expanded/delivery-plan.json');
const RECEIPT_PATH = join(ROOT, '.cache/hf-private-upload-20261019/private-verify-receipt.json');
const REPO_ID = 'BrainPilot-Bench/Tasks-Data-Private';
const REVISION = '62ff438a727aa5ca72c688526410930c8f1f664b';
const PLAN_SHA256 = 'e74eb8a2b1a3bdcd5a4f2f9f2ce3923c6b50ec9906c72305684b0dc7d8d94068';
const SHA_RE = /^[0-9a-f]{64}$/;
const SEGMENT_RE = /^[A-Za-z0-9._-]+$/;
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = (context, message) => { throw new Error(`${context}: ${message}`); };

function safePath(path, context) {
  if (typeof path !== 'string' || !path || path.split('/').some(part =>
    !SEGMENT_RE.test(part) || part === '.' || part === '..')) fail(context, `unsafe path ${path}`);
  return path;
}

function formatOf(path) {
  const file = basename(path);
  return file.endsWith('.tar.zst') ? 'tar.zst' : file.endsWith('.nii.gz') ? 'nii.gz' : file.split('.').at(-1);
}

function isPrivate(entry) { return entry.scope === 'private'; }

function evaluatorPathFor(entry, targetPrefix) {
  if (typeof entry.uri !== 'string') return null;
  if (entry.uri.startsWith('local://'))
    return entry.uri.slice('local://'.length).replace(/^evaluator\//, '');
  const hosted = /^hf:\/\/datasets\/BrainPilot-Bench\/Tasks-Data-Private@[0-9a-f]{40}\/(.+)$/.exec(entry.uri);
  return hosted?.[1].startsWith(targetPrefix) ? hosted[1].slice(targetPrefix.length) : null;
}

function replacementsInYaml(source, doc, changes) {
  const items = doc.get('datasets', true)?.items;
  if (!items || items.length !== changes.datasetCount) fail('data.lock', 'YAML item offsets unavailable');
  const jsonLock = source.trimStart().startsWith('{');
  if (jsonLock && changes.newEntries.length) fail('data.lock', 'cannot append YAML to a JSON lock');
  const edits = changes.uriByIndex.map(([index, uri]) => {
    const node = items[index]?.get('uri', true);
    if (!node?.range) fail('data.lock', `URI offset unavailable at dataset ${index}`);
    return [node.range[0], node.range[1], jsonLock ? JSON.stringify(uri) : uri];
  }).sort((a, b) => b[0] - a[0]);
  let output = source;
  for (const [start, end, uri] of edits) output = output.slice(0, start) + uri + output.slice(end);
  if (changes.newEntries.length) {
    const appended = YAML.stringify({ datasets: changes.newEntries }).replace(/^datasets:\n/, '');
    output += `${output.endsWith('\n') ? '' : '\n'}${appended}`;
  }
  return output;
}

/** Pure metadata transformation. Caller supplies an exact local plan digest. */
export function buildPrivateEvaluatorLocks({ root, plan, receipt, planSha256,
  expectedRevision = REVISION, expectedPlanSha256 = PLAN_SHA256,
  expectedTasks = 29, expectedFiles = 301, expectedBytes = 8353488018 }) {
  if (planSha256 !== expectedPlanSha256 || receipt.plan_sha256 !== planSha256)
    fail('plan', 'frozen SHA-256 does not match verified upload receipt');
  if (plan.schema !== 'bpb-private-expanded-delivery-plan/1' ||
      plan.destination?.repo_id !== REPO_ID || plan.new_tasks !== expectedTasks ||
      plan.new_files !== expectedFiles || plan.new_bytes !== expectedBytes ||
      !Array.isArray(plan.files) || plan.files.length !== expectedFiles)
    fail('plan', 'unexpected source plan or object counts');
  if (receipt.schema !== 'bpb-private-final-verify/1' || receipt.status !== 'passed' ||
      receipt.repo_id !== REPO_ID || receipt.head !== expectedRevision ||
      receipt.tree_identity?.all_paths_and_lfs_or_git_blobs_checked !== true ||
      receipt.tree_identity.new_data_objects !== expectedFiles ||
      receipt.tree_identity.new_data_bytes !== expectedBytes)
    fail('receipt', 'private upload is not verified at the expected immutable revision');
  const catalog = JSON.parse(readFileSync(join(root, 'tasks/catalog.json'), 'utf8'));
  const directoryById = new Map(catalog.tasks.map(item => [item.task_id, item.directory]));
  const grouped = new Map();
  const globalPaths = new Set();
  const digestSizes = new Map();
  let totalBytes = 0;
  for (const op of plan.files) {
    const context = `plan ${op.task_id}`;
    if (op.access_role !== 'private_evaluator' || !directoryById.has(op.task_id) ||
        typeof op.sha256 !== 'string' || !SHA_RE.test(op.sha256) ||
        !Number.isSafeInteger(op.bytes) || op.bytes < 0) fail(context, 'invalid object metadata');
    const target = safePath(op.target_path, context);
    const directory = directoryById.get(op.task_id);
    const category = ['intracortical', 'ieeg'].includes(directory.split('/')[1])
      ? 'invasive' : directory.split('/')[1];
    const prefix = `tasks/${category}/${op.task_id}/evaluator/`;
    if (!target.startsWith(prefix)) fail(context, `noncanonical target ${target}`);
    const path = safePath(target.slice(prefix.length), context);
    const folded = target.toLowerCase();
    if ([...globalPaths].some(previous => previous === folded ||
        previous.startsWith(`${folded}/`) || folded.startsWith(`${previous}/`)))
      fail(context, `duplicate or overlapping target ${target}`);
    globalPaths.add(folded);
    if (digestSizes.has(op.sha256) && digestSizes.get(op.sha256) !== op.bytes)
      fail(context, `same SHA-256 has conflicting byte counts`);
    digestSizes.set(op.sha256, op.bytes);
    totalBytes += op.bytes;
    if (!grouped.has(op.task_id)) grouped.set(op.task_id, []);
    grouped.get(op.task_id).push({ path, sha256: op.sha256, bytes: op.bytes, target });
  }
  if (grouped.size !== expectedTasks || totalBytes !== expectedBytes)
    fail('plan', 'task or byte total differs from frozen upload');

  const outputs = new Map();
  let addedEntries = 0;
  let reboundEntries = 0;
  let preservedPrivateEntries = 0;
  for (const [id, files] of grouped) {
    const directory = safePath(directoryById.get(id), id);
    const lockPath = join(root, directory, 'data.lock');
    if (!existsSync(lockPath) || lstatSync(lockPath).isSymbolicLink()) fail(id, 'missing or linked data.lock');
    const source = readFileSync(lockPath, 'utf8');
    const jsonLock = source.trimStart().startsWith('{');
    const doc = YAML.parseDocument(source, { keepSourceTokens: true, uniqueKeys: true });
    if (doc.errors.length) fail(id, `invalid data.lock: ${doc.errors[0].message}`);
    const data = doc.toJS();
    if (!Array.isArray(data.datasets)) fail(id, 'data.lock has no datasets');
    const oldPublic = data.datasets.filter(entry => !isPrivate(entry));
    const oldPrivate = data.datasets.filter(isPrivate);
    const byName = new Set();
    for (const entry of data.datasets) {
      if (typeof entry.name !== 'string' || !SEGMENT_RE.test(entry.name) ||
          byName.has(entry.name.toLowerCase())) fail(id, `duplicate or unsafe dataset name ${entry.name}`);
      byName.add(entry.name.toLowerCase());
    }
    const indexedPrivate = data.datasets.map((entry, index) => [entry, index]).filter(([entry]) => isPrivate(entry));
    const consumed = new Set();
    const uriByIndex = [];
    const newEntries = [];
    const evaluatorFiles = [];
    for (const file of files.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0)) {
      const uri = `hf://datasets/${REPO_ID}@${expectedRevision}/${file.target}`;
      const targetPrefix = file.target.slice(0, -file.path.length);
      const pathMatches = indexedPrivate.filter(([entry]) => evaluatorPathFor(entry, targetPrefix) === file.path);
      if (pathMatches.length > 1) fail(id, `ambiguous existing path ${file.path}`);
      let match = pathMatches[0];
      if (!match) {
        const digestMatches = indexedPrivate.filter(([entry]) =>
          entry.sha256 === file.sha256 && entry.bytes === file.bytes && !consumed.has(entry.name));
        const preparedMatches = files.filter(other => other.sha256 === file.sha256 && other.bytes === file.bytes);
        if (digestMatches.length === 1 && preparedMatches.length === 1) match = digestMatches[0];
      }
      let name;
      if (match) {
        const [entry, index] = match;
        if (entry.sha256 !== file.sha256 || entry.bytes !== file.bytes)
          fail(id, `existing ${entry.name} differs from uploaded ${file.path}`);
        if (consumed.has(entry.name)) fail(id, `existing ${entry.name} mapped twice`);
        consumed.add(entry.name);
        name = entry.name;
        const uriNode = doc.get('datasets', true)?.items[index]?.get('uri', true);
        const rawUri = uriNode?.range ? source.slice(uriNode.range[0], uriNode.range[1]) : '';
        if (entry.uri !== uri || (jsonLock && rawUri !== JSON.stringify(uri))) {
          uriByIndex.push([index, uri]);
          if (entry.uri !== uri) reboundEntries++;
        }
      } else {
        name = `evaluator__${file.path.replaceAll('/', '__')}`;
        if (!SEGMENT_RE.test(name) || byName.has(name.toLowerCase()))
          fail(id, `generated dataset name collision ${name}`);
        byName.add(name.toLowerCase());
        newEntries.push({ name, scope: 'private', uri, sha256: file.sha256,
          bytes: file.bytes, format: formatOf(file.path) });
        addedEntries++;
      }
      evaluatorFiles.push({ name, path: file.path, sha256: file.sha256, bytes: file.bytes });
    }
    preservedPrivateEntries += oldPrivate.length - consumed.size;
    const nextSource = replacementsInYaml(source, doc, { datasetCount: data.datasets.length,
      uriByIndex, newEntries });
    const nextData = YAML.parse(nextSource);
    if (JSON.stringify(nextData.datasets.filter(entry => !isPrivate(entry))) !== JSON.stringify(oldPublic))
      fail(id, 'public entries changed');
    for (const [entry] of indexedPrivate) {
      const next = nextData.datasets.find(candidate => candidate.name === entry.name);
      if (!next || next.sha256 !== entry.sha256 || next.bytes !== entry.bytes ||
          next.format !== entry.format) fail(id, `existing private metadata changed: ${entry.name}`);
    }
    if (nextSource !== source) outputs.set(relative(root, lockPath), nextSource);
    const evaluatorLock = { schema: 'bpb-evaluator-data/1', task_id: id, repo_id: REPO_ID,
      revision: expectedRevision, files: evaluatorFiles };
    const evaluatorLockPath = join(root, directory, 'evaluator.lock');
    if (existsSync(evaluatorLockPath) && lstatSync(evaluatorLockPath).isSymbolicLink())
      fail(id, 'linked evaluator.lock');
    const nextEvaluator = `${JSON.stringify(evaluatorLock, null, 2)}\n`;
    if (!existsSync(evaluatorLockPath) || readFileSync(evaluatorLockPath, 'utf8') !== nextEvaluator)
      outputs.set(relative(root, evaluatorLockPath), nextEvaluator);
  }
  return { outputs, tasks: grouped.size, files: plan.files.length, bytes: totalBytes,
    addedEntries, reboundEntries, preservedPrivateEntries };
}

export function main(args = process.argv.slice(2)) {
  if (args.some(arg => !['--apply', '--check'].includes(arg)) ||
      (args.includes('--apply') && args.includes('--check')))
    fail('arguments', 'use --apply or --check (default: dry run)');
  const planBytes = readFileSync(PLAN_PATH);
  const result = buildPrivateEvaluatorLocks({ root: ROOT, plan: JSON.parse(planBytes),
    receipt: JSON.parse(readFileSync(RECEIPT_PATH, 'utf8')), planSha256: sha256(planBytes) });
  const mode = args.includes('--apply') ? 'apply' : args.includes('--check') ? 'check' : 'dry-run';
  if (mode === 'check' && result.outputs.size) fail('locks', `${result.outputs.size} files differ`);
  if (mode === 'apply') for (const [path, content] of result.outputs)
    writeFileSync(join(ROOT, path), content);
  console.log(JSON.stringify({ mode, revision: REVISION, tasks: result.tasks,
    files: result.files, bytes: result.bytes, addedEntries: result.addedEntries,
    reboundEntries: result.reboundEntries, preservedPrivateEntries: result.preservedPrivateEntries,
    changed: [...result.outputs.keys()] }, null, 2));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
