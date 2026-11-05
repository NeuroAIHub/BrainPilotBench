#!/usr/bin/env node
/** Additive metadata/transport evidence for the exact 2026-10-19 private upload.
 * Validation reads only checked-in files. Generation reads the frozen source
 * commit and upload receipt; neither path executes task code or downloads data.
 */
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, lstatSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const INCREMENT_PATH = 'reports/private-evaluator-increment-20261019.json';
export const PRIVATE_REVISION = '62ff438a727aa5ca72c688526410930c8f1f664b';
const SOURCE_COMMIT = '7306cc0b0e8958cc8f84918b68446310d8dbc662';
const REPO_ID = 'BrainPilot-Bench/Tasks-Data-Private';
const PLAN_SHA256 = 'e74eb8a2b1a3bdcd5a4f2f9f2ce3923c6b50ec9906c72305684b0dc7d8d94068';
const RECEIPT_SHA256 = '009100346047f0d62a43156c167faaa85a0149039121c4448f788f93b3381a71';
const BASELINE_LOCKS_SHA256 = '7e4d9d3e155dcb7b12e6071e6b51e17dcc2ad4e52b8bcc5c6fac2eb5cea641cd';
const PRIOR_RECEIPTS_SHA256 = '30c4b2c59ab0e9afbe14914357affbdf0cc38c00d74a5a7c64714677ae3669b8';
const OBJECT_BINDINGS_SHA256 = '8a6a85b35f15a11e37204f13056a58f6fc2111cfff5b7d2f0487e24d93a05e20';
const EXPECTED_FILES = 301;
const EXPECTED_BYTES = 8353488018;
const SHA_RE = /^[0-9a-f]{64}$/;
const SEGMENT_RE = /^[A-Za-z0-9._-]+$/;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = message => { throw new Error(`private evaluator increment: ${message}`); };

const TASK_IDS = Object.freeze([
  'brain-age-mri', 'celegans-structure-function-divergence', 'eeg-cvep-thielen2015',
  'eeg-dementia-dice', 'eeg-erp-ern', 'eeg-erp-lrp', 'eeg-erp-mmn', 'eeg-erp-n170',
  'eeg-erp-n2pc', 'eeg-erp-n400', 'eeg-erp-p3', 'eeg-me-highgamma2017',
  'eeg-me-ofner2017', 'eeg-mental-arithmetic-zyma2019', 'eeg-mi-barachant2012',
  'eeg-mi-cho2017', 'eeg-mi-eegmmidb', 'eeg-mi-openbmi2019', 'eeg-mi-zhou2016',
  'eeg-p3-openbmi2019', 'eeg-sleep-stage-sleepedf', 'eeg-ssvep-openbmi2019',
  'eeg-typing-spanishbcbl', 'falcon-b1-birdsong', 'falcon-h2-handwriting',
  'falcon-m1-emg', 'falcon-m2-finger-velocity', 'ieeg-film-speech-music',
  'ieeg-finger-flexion-bciciv4',
]);
const DELIVERED_INVASIVE = new Set([
  'ieeg-finger-flexion-bciciv4', 'falcon-h2-handwriting', 'falcon-m1-emg',
  'falcon-m2-finger-velocity', 'falcon-b1-birdsong', 'ieeg-film-speech-music',
]);
const BRIDGE_UNCHANGED = new Set([
  'src/data/types.ts', 'src/data/manifest.ts', 'src/data/fetch.ts',
]);
const BRIDGE_CHANGED = new Set([
  'src/workflow.ts', 'src/cli.ts', 'src/data/cache.ts', 'src/data/resolve.ts',
]);
const CORE_FILES = Object.freeze([
  ...BRIDGE_UNCHANGED, ...BRIDGE_CHANGED,
  'src/evaluator.ts', 'src/private-score.ts', 'src/score.ts',
  'src/submission.ts', 'src/sandbox.ts',
  'tasks/_shared/evaluator/prepare.py', 'tasks/_shared/evaluator/score.py',
  'tasks/eeg/_shared/private_score.py', 'scripts/build-private-evaluator-locks.mjs',
].sort());
// Preserve the historical upload receipt. This separate, narrow code increment
// binds source-only lock support; it cannot amend any hosted data identities.
function sourceCompatibility(root, path, previous, current) {
  const baseline = {
    'src/evaluator.ts': 'b5ccbdf0d90894967f763f76cfaa921beec635a4a7f4eb03b0c1f4a6bce458d6',
    'src/workflow.ts': 'f9a79dd440874d323821be66dee22e9f3923e153ed12ab2537829341fb056293',
  };
  if (!Object.hasOwn(baseline, path)) return false;
  const location = 'reports/mouse-closeout-20261026/source-evaluator-compatibility.json';
  if (!existsSync(join(root, location))) return false;
  const item = JSON.parse(fileBytes(root, location));
  return item.schema === 'bpb-source-evaluator-compatibility/1' &&
    item.files?.[path]?.previous_sha256 === previous && item.files[path].current_sha256 === current &&
    previous === baseline[path] &&
    item.test_path === 'src/evaluator-source.test.ts' && SHA_RE.test(item.test_sha256) &&
    sha(fileBytes(root, item.test_path)) === item.test_sha256 &&
    item.historical_publication_replayed === false;
}
const REPORT_KEYS = Object.freeze([
  'schema', 'status', 'scope', 'scientific_acceptance_replayed', 'source_commit',
  'repo_id', 'revision', 'plan_sha256', 'upload_receipt_sha256',
  'object_bindings_sha256', 'remote_verification', 'files', 'bytes',
  'public_entries_unchanged', 'core_file_sha256', 'tasks',
].sort());
const TASK_KEYS = Object.freeze([
  'task_id', 'directory', 'prior_data_lock_sha256', 'prior_dataset_count',
  'prior_private_uris', 'data_lock_sha256', 'evaluator_lock_sha256',
  'public_entries', 'files', 'bytes',
].sort());
const VERIFICATION_NOTE = 'Frozen upload receipt only; catalog validation does not revisit Hugging Face or run model scoring.';

export const privateEvaluatorTaskIds = TASK_IDS;
export const privateScoreEntry = 'bp-bench score <bundle> --private --evaluator-root <owner/evaluator> --isolation docker --inference-image <digest>';

function directoryFor(id) {
  const category = id === 'brain-age-mri' ? 'mri'
    : id === 'celegans-structure-function-divergence' ? 'connectomics'
      : id.startsWith('falcon-') ? 'intracortical'
        : id.startsWith('ieeg-') ? 'ieeg' : 'eeg';
  return `tasks/${category}/${id}`;
}
function hostedCategory(id) {
  const category = directoryFor(id).split('/')[1];
  return ['intracortical', 'ieeg'].includes(category) ? 'invasive' : category;
}
function fileBytes(root, path) {
  if (typeof path !== 'string' || path.startsWith('/') ||
      path.split('/').some(segment => !SEGMENT_RE.test(segment) || segment === '.' || segment === '..'))
    fail(`unsafe path ${path}`);
  let current = root;
  for (const segment of path.split('/')) {
    current = join(current, segment);
    if (lstatSync(current).isSymbolicLink()) fail(`symbolic link ${path}`);
  }
  if (!lstatSync(current).isFile()) fail(`not a regular file ${path}`);
  return readFileSync(current);
}
function parseLock(text, id) {
  const doc = YAML.parseDocument(text, { keepSourceTokens: true, uniqueKeys: true });
  if (doc.errors.length) fail(`${id}: invalid data.lock: ${doc.errors[0].message}`);
  const entries = doc.toJS()?.datasets;
  const items = doc.get('datasets', true)?.items;
  if (!Array.isArray(entries) || !items || entries.length !== items.length)
    fail(`${id}: invalid data.lock datasets`);
  return { doc, entries, items };
}
function baselineFromCurrent(text, id, taskRecord) {
  const { entries, items } = parseLock(text, id);
  const oldCount = taskRecord.prior_dataset_count;
  if (!Number.isSafeInteger(oldCount) || oldCount < 0 || oldCount > entries.length)
    fail(`${id}: invalid prior dataset count`);
  const oldUris = taskRecord.prior_private_uris;
  if (!oldUris || typeof oldUris !== 'object' || Array.isArray(oldUris))
    fail(`${id}: invalid private URI reversals`);
  const json = text.trimStart().startsWith('{');
  let reconstructed = oldCount < entries.length ? text.slice(0, items[oldCount].range[0] - 4) : text;
  const edits = [];
  const found = new Set();
  for (let i = 0; i < oldCount; i++) {
    const entry = entries[i];
    if (!Object.hasOwn(oldUris, entry.name)) continue;
    const oldUri = oldUris[entry.name];
    if (entry.scope !== 'private' || typeof oldUri !== 'string' || !oldUri ||
        !entry.uri.startsWith(`hf://datasets/${REPO_ID}@${PRIVATE_REVISION}/`))
      fail(`${id}: unsafe private URI reversal for ${entry.name}`);
    const node = items[i].get('uri', true);
    if (!node?.range) fail(`${id}: URI offset unavailable for ${entry.name}`);
    edits.push([node.range[0], node.range[1], json ? JSON.stringify(oldUri) : oldUri]);
    found.add(entry.name);
  }
  if (found.size !== Object.keys(oldUris).length) fail(`${id}: unused private URI reversal`);
  for (const [start, end, oldUri] of edits.sort((a, b) => b[0] - a[0]))
    reconstructed = reconstructed.slice(0, start) + oldUri + reconstructed.slice(end);
  if (sha(reconstructed) !== taskRecord.prior_data_lock_sha256)
    fail(`${id}: old delivered data.lock cannot be reconstructed`);
  const old = parseLock(reconstructed, id).entries;
  if (old.length !== oldCount) fail(`${id}: reconstructed dataset count differs`);
  for (let i = 0; i < oldCount; i++) {
    if (old[i].name !== entries[i].name || old[i].scope !== entries[i].scope)
      fail(`${id}: prior dataset identity differs`);
    if (old[i].scope !== 'private' && JSON.stringify(old[i]) !== JSON.stringify(entries[i]))
      fail(`${id}: public dataset changed`);
  }
  for (const entry of entries.slice(oldCount))
    if (entry.scope !== 'private') fail(`${id}: appended nonprivate dataset`);
  return { entries, oldCount, publicCount: old.filter(entry => entry.scope !== 'private').length };
}

function validateEvaluatorLock(root, id, directory, dataEntries) {
  const content = fileBytes(root, `${directory}/evaluator.lock`);
  const lock = JSON.parse(content);
  if (lock.schema !== 'bpb-evaluator-data/1' || lock.task_id !== id ||
      lock.repo_id !== REPO_ID || lock.revision !== PRIVATE_REVISION ||
      !Array.isArray(lock.files) || !lock.files.length)
    fail(`${id}: invalid evaluator.lock identity`);
  const names = new Set(), paths = new Set();
  let bytes = 0;
  const objects = [];
  for (const file of lock.files) {
    if (typeof file.name !== 'string' || !SEGMENT_RE.test(file.name) ||
        typeof file.path !== 'string' || !file.path ||
        file.path.split('/').some(part => !SEGMENT_RE.test(part) || part === '.' || part === '..') ||
        !SHA_RE.test(file.sha256 ?? '') || !Number.isSafeInteger(file.bytes) || file.bytes <= 0)
      fail(`${id}: unsafe evaluator mapping`);
    const name = file.name.toLowerCase(), path = file.path.toLowerCase();
    if (names.has(name) || [...paths].some(other => other === path ||
        other.startsWith(`${path}/`) || path.startsWith(`${other}/`)))
      fail(`${id}: duplicate evaluator mapping`);
    names.add(name); paths.add(path);
    const matches = dataEntries.filter(entry => entry.name === file.name);
    const expectedUri = `hf://datasets/${REPO_ID}@${PRIVATE_REVISION}/tasks/${hostedCategory(id)}/${id}/evaluator/${file.path}`;
    if (matches.length !== 1 || matches[0].scope !== 'private' ||
        matches[0].uri !== expectedUri || matches[0].sha256 !== file.sha256 || matches[0].bytes !== file.bytes)
      fail(`${id}: evaluator file does not match pinned private data.lock entry`);
    bytes += file.bytes;
    objects.push([`tasks/${hostedCategory(id)}/${id}/evaluator/${file.path}`, file.sha256, file.bytes]);
  }
  return { sha256: sha(content), files: lock.files.length, bytes, names, objects };
}

function baselineListDigest(tasks) {
  return sha(JSON.stringify(tasks.map(task => [task.task_id, task.prior_data_lock_sha256])));
}

/** Strictly validates the checked-in additive evidence. No Git or remote access. */
export function validatePrivateEvaluatorIncrement(root = ROOT, supplied) {
  const report = supplied ?? JSON.parse(fileBytes(root, INCREMENT_PATH));
  if (JSON.stringify(Object.keys(report).sort()) !== JSON.stringify(REPORT_KEYS) ||
      report.schema !== 'bpb-private-evaluator-increment/1' || report.status !== 'binding_verified' ||
      report.scope !== 'metadata_transport_only' || report.scientific_acceptance_replayed !== false ||
      report.source_commit !== SOURCE_COMMIT || report.repo_id !== REPO_ID ||
      report.revision !== PRIVATE_REVISION || report.plan_sha256 !== PLAN_SHA256 ||
      report.upload_receipt_sha256 !== RECEIPT_SHA256 || report.files !== EXPECTED_FILES ||
      report.object_bindings_sha256 !== OBJECT_BINDINGS_SHA256 ||
      report.bytes !== EXPECTED_BYTES || !Array.isArray(report.tasks) ||
      report.tasks.length !== TASK_IDS.length ||
      JSON.stringify(report.tasks.map(task => task.task_id)) !== JSON.stringify(TASK_IDS) ||
      baselineListDigest(report.tasks) !== BASELINE_LOCKS_SHA256 ||
      sha(JSON.stringify(report.tasks.filter(task => DELIVERED_INVASIVE.has(task.task_id))
        .map(task => [task.task_id, task.prior_acceptance_sha256, task.prior_delivery_sha256]))) !== PRIOR_RECEIPTS_SHA256 ||
      JSON.stringify(Object.keys(report.remote_verification ?? {}).sort()) !==
        JSON.stringify(['tree_identity_checked', 'full_byte_readbacks', 'metadata_objects', 'note'].sort()) ||
      report.remote_verification.tree_identity_checked !== true ||
      report.remote_verification.full_byte_readbacks !== 288 ||
      report.remote_verification.metadata_objects !== 143 ||
      report.remote_verification.note !== VERIFICATION_NOTE ||
      JSON.stringify(Object.keys(report.core_file_sha256 ?? {}).sort()) !== JSON.stringify(CORE_FILES))
    fail('unexpected schema, scope, frozen upload, task set, or core bindings');
  for (const path of CORE_FILES) {
    const current = sha(fileBytes(root, path));
    if (!SHA_RE.test(report.core_file_sha256[path]) ||
        (current !== report.core_file_sha256[path] &&
         !sourceCompatibility(root, path, report.core_file_sha256[path], current)))
      fail(`stale core code hash: ${path}`);
  }
  let files = 0, bytes = 0, publicEntries = 0;
  const objects = [];
  const byId = new Map();
  for (const item of report.tasks) {
    const id = item.task_id, directory = directoryFor(id);
    const expectedKeys = DELIVERED_INVASIVE.has(id)
      ? [...TASK_KEYS, 'prior_acceptance_sha256', 'prior_delivery_sha256'].sort() : TASK_KEYS;
    if (JSON.stringify(Object.keys(item).sort()) !== JSON.stringify(expectedKeys) ||
        item.directory !== directory || !SHA_RE.test(item.prior_data_lock_sha256) ||
        !SHA_RE.test(item.data_lock_sha256) || !SHA_RE.test(item.evaluator_lock_sha256))
      fail(`${id}: invalid task binding`);
    const source = fileBytes(root, `${directory}/data.lock`);
    if (sha(source) !== item.data_lock_sha256) fail(`${id}: stale data.lock hash`);
    const reconstructed = baselineFromCurrent(source.toString('utf8'), id, item);
    if (item.public_entries !== reconstructed.publicCount)
      fail(`${id}: public entry count differs`);
    const evaluator = validateEvaluatorLock(root, id, directory, reconstructed.entries);
    if (item.evaluator_lock_sha256 !== evaluator.sha256 || item.files !== evaluator.files ||
        item.bytes !== evaluator.bytes)
      fail(`${id}: stale evaluator.lock binding`);
    for (const entry of reconstructed.entries.slice(reconstructed.oldCount))
      if (!evaluator.names.has(entry.name.toLowerCase()))
        fail(`${id}: appended private entry absent from evaluator.lock`);
    if (DELIVERED_INVASIVE.has(id)) {
      const acceptanceBytes = fileBytes(root, `${directory}/acceptance.json`);
      const deliveryBytes = fileBytes(root, `${directory}/delivery-acceptance.json`);
      const delivery = JSON.parse(deliveryBytes);
      if (item.prior_acceptance_sha256 !== sha(acceptanceBytes) ||
          item.prior_delivery_sha256 !== sha(deliveryBytes) ||
          delivery.prior_acceptance_sha256 !== item.prior_acceptance_sha256 ||
          delivery.new_file_sha256?.[`${directory}/data.lock`] !== item.prior_data_lock_sha256 ||
          delivery.new_file_sha256?.[`${directory}/env/setup.sh`] !== sha(fileBytes(root, `${directory}/env/setup.sh`)))
        fail(`${id}: old scientific/public delivery receipts no longer bind`);
      for (const [path, prior] of Object.entries(delivery.bridge_file_sha256 ?? {})) {
        if (!CORE_FILES.includes(path) || !SHA_RE.test(prior) ||
            (BRIDGE_UNCHANGED.has(path) && report.core_file_sha256[path] !== prior) ||
            (!BRIDGE_UNCHANGED.has(path) && !BRIDGE_CHANGED.has(path)))
          fail(`${id}: bridge changed outside the explicit increment`);
      }
    } else if (item.prior_acceptance_sha256 !== undefined || item.prior_delivery_sha256 !== undefined) {
      fail(`${id}: unexpected old invasive receipt binding`);
    }
    files += evaluator.files; bytes += evaluator.bytes; publicEntries += reconstructed.publicCount;
    objects.push(...evaluator.objects);
    byId.set(id, item);
  }
  objects.sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
  if (files !== EXPECTED_FILES || bytes !== EXPECTED_BYTES || publicEntries !== 504 ||
      report.public_entries_unchanged !== publicEntries ||
      sha(JSON.stringify(objects)) !== OBJECT_BINDINGS_SHA256)
    fail('object or unchanged public-entry totals differ');
  return { report, byId, tasks: TASK_IDS.length, files, bytes, publicEntries,
    verifiedCoreSha256: Object.fromEntries(CORE_FILES.map(path => [path, sha(fileBytes(root, path))])) };
}

/** Generate the additive record from the fixed pre-upload Git commit. */
export function buildPrivateEvaluatorIncrement(root = ROOT) {
  const planPath = '.cache/hf-private-preparation-20261019/expanded/delivery-plan.json';
  const receiptPath = '.cache/hf-private-upload-20261019/private-verify-receipt.json';
  const planBytes = readFileSync(join(root, planPath));
  const receiptBytes = readFileSync(join(root, receiptPath));
  if (sha(planBytes) !== PLAN_SHA256 || sha(receiptBytes) !== RECEIPT_SHA256)
    fail('frozen local plan or receipt bytes differ');
  const plan = JSON.parse(planBytes), receipt = JSON.parse(receiptBytes);
  if (plan.source_commit !== SOURCE_COMMIT || plan.new_tasks !== TASK_IDS.length ||
      plan.new_files !== EXPECTED_FILES || plan.new_bytes !== EXPECTED_BYTES ||
      sha(JSON.stringify(plan.files.map(file => [file.target_path, file.sha256, file.bytes])
        .sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))) !== OBJECT_BINDINGS_SHA256 ||
      receipt.status !== 'passed' || receipt.head !== PRIVATE_REVISION ||
      receipt.plan_sha256 !== PLAN_SHA256 ||
      receipt.tree_identity?.all_paths_and_lfs_or_git_blobs_checked !== true ||
      receipt.full_byte_readback_count !== 288)
    fail('frozen upload metadata differs');
  const tasks = [];
  for (const id of TASK_IDS) {
    const directory = directoryFor(id), lockPath = `${directory}/data.lock`;
    const priorBytes = execFileSync('git', ['show', `${SOURCE_COMMIT}:${lockPath}`], { cwd: root });
    const prior = parseLock(priorBytes.toString('utf8'), id).entries;
    const currentBytes = fileBytes(root, lockPath);
    const current = parseLock(currentBytes.toString('utf8'), id).entries;
    if (current.length < prior.length) fail(`${id}: removed dataset entries`);
    const uriRebindings = {};
    for (let index = 0; index < prior.length; index++) {
      if (prior[index].name !== current[index].name) fail(`${id}: old dataset order differs`);
      if (prior[index].uri !== current[index].uri) {
        if (prior[index].scope !== 'private') fail(`${id}: public URI changed`);
        uriRebindings[prior[index].name] = prior[index].uri;
      }
    }
    const evaluator = validateEvaluatorLock(root, id, directory, current);
    const item = {
      task_id: id, directory, prior_data_lock_sha256: sha(priorBytes),
      prior_dataset_count: prior.length, prior_private_uris: uriRebindings,
      data_lock_sha256: sha(currentBytes), evaluator_lock_sha256: evaluator.sha256,
      public_entries: prior.filter(entry => entry.scope !== 'private').length,
      files: evaluator.files, bytes: evaluator.bytes,
    };
    if (DELIVERED_INVASIVE.has(id)) {
      item.prior_acceptance_sha256 = sha(fileBytes(root, `${directory}/acceptance.json`));
      item.prior_delivery_sha256 = sha(fileBytes(root, `${directory}/delivery-acceptance.json`));
    }
    tasks.push(item);
  }
  if (baselineListDigest(tasks) !== BASELINE_LOCKS_SHA256)
    fail('source commit data.lock baseline differs');
  const core_file_sha256 = Object.fromEntries(CORE_FILES.map(path => [path, sha(fileBytes(root, path))]));
  const report = {
    schema: 'bpb-private-evaluator-increment/1', status: 'binding_verified',
    scope: 'metadata_transport_only', scientific_acceptance_replayed: false,
    source_commit: SOURCE_COMMIT, repo_id: REPO_ID, revision: PRIVATE_REVISION,
    plan_sha256: PLAN_SHA256, upload_receipt_sha256: RECEIPT_SHA256,
    object_bindings_sha256: OBJECT_BINDINGS_SHA256,
    remote_verification: { tree_identity_checked: true, full_byte_readbacks: 288,
      metadata_objects: 143, note: VERIFICATION_NOTE },
    files: EXPECTED_FILES, bytes: EXPECTED_BYTES, public_entries_unchanged: 504,
    core_file_sha256, tasks,
  };
  validatePrivateEvaluatorIncrement(root, report);
  return report;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.some(arg => !['--apply', '--check'].includes(arg)) ||
      (args.includes('--apply') && args.includes('--check')))
    fail('use --apply to generate or --check to validate (default: dry run)');
  const mode = args.includes('--apply') ? 'apply' : args.includes('--check') ? 'check' : 'dry-run';
  if (mode === 'check') {
    const verified = validatePrivateEvaluatorIncrement(ROOT);
    console.log(JSON.stringify({ mode, tasks: verified.tasks, files: verified.files,
      bytes: verified.bytes, public_entries_unchanged: verified.publicEntries }));
  } else {
    const report = buildPrivateEvaluatorIncrement(ROOT);
    const content = `${JSON.stringify(report, null, 2)}\n`;
    const path = join(ROOT, INCREMENT_PATH);
    if (mode === 'apply' && (!existsSync(path) || readFileSync(path, 'utf8') !== content))
      writeFileSync(path, content);
    console.log(JSON.stringify({ mode, path: INCREMENT_PATH, tasks: report.tasks.length,
      files: report.files, bytes: report.bytes, public_entries_unchanged: report.public_entries_unchanged }));
  }
}
