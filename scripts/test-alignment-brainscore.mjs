/** Offline registry and cache-contract checks. No datasets, weights or network. */
import { spawnSync } from 'node:child_process';
const result = spawnSync(process.env.BPB_ALIGNMENT_PYTHON || 'python3',
  ['-B', 'tasks/alignment/_shared/test_brainscore_scaleup.py'], {
    stdio: 'inherit', timeout: 180000,
    env: { ...process.env, OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1', PYTHONDONTWRITEBYTECODE: '1' },
  });
if (result.error) console.error(result.error.message);
if (result.status !== 0) process.exit(result.status ?? 1);
const metadata = spawnSync(process.execPath, ['scripts/alignment-candidates.test.mjs'], {
  stdio: 'inherit', timeout: 30000,
});
if (metadata.error) console.error(metadata.error.message);
process.exit(metadata.status ?? 1);
