/** Offline scientific/worker tests. Real-data acceptance is recorded separately. */
import { spawnSync } from 'node:child_process';
const python = process.env.BPB_ALIGNMENT_PYTHON || 'python3';
const result = spawnSync(python, ['-B', 'tasks/alignment/_shared/test_incremental.py'], {
  stdio: 'inherit', timeout: 120000,
  env: { ...process.env, OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1', PYTHONDONTWRITEBYTECODE: '1' },
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
