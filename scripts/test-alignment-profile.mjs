import { spawnSync } from 'node:child_process';
const python = process.env.BPB_ALIGNMENT_PROFILE_PYTHON || 'python3';
for (const [executable, args] of [
  [python, ['-B', 'tasks/_example/alignment-profile-synthetic/checks/test_profile.py']],
  [process.execPath, ['scripts/alignment-profile-smoke.mjs']],
]) {
  const result = spawnSync(executable, args, { stdio: 'inherit', timeout: 120000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
  if (result.error) console.error(result.error.message);
  if (result.status !== 0) process.exit(result.status || 1);
}
