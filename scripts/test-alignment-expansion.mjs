/** Offline B–F numerical and evaluator checks; no downloads. */
import { spawnSync } from 'node:child_process';
const result = spawnSync(process.env.BPB_ALIGNMENT_PYTHON || 'python3',
  ['-B', 'tasks/alignment/_shared/test_expansion.py'], {
    stdio: 'inherit', timeout: 180000,
    env: { ...process.env, OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1', PYTHONDONTWRITEBYTECODE: '1' },
  });
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
