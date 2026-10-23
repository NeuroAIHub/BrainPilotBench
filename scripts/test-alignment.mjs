import { spawnSync } from 'node:child_process';
const python = process.env.BPB_ALIGNMENT_PYTHON || 'python3';
for (const [exe, args] of [
  [python, ['-B', 'tasks/alignment/_shared/test_alignment.py']],
  [process.execPath, ['scripts/alignment-smoke.mjs']],
]) {
  const result = spawnSync(exe, args, { stdio: 'inherit', env: process.env, timeout: 120000 });
  if (result.error) console.error(result.error.message);
  if (result.status !== 0) process.exit(result.status || 1);
}
