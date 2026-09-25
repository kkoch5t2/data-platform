const { spawnSync } = require('node:child_process');

const args = process.argv.slice(2);
if (!args.length) {
  console.error('Usage: node scripts/run-python.cjs <script.py> [...args]');
  process.exit(2);
}

for (const cmd of process.platform === 'win32' ? ['python', 'py'] : ['python3', 'python']) {
  const cmdArgs = cmd === 'py' ? ['-3', ...args] : args;
  const probe = spawnSync(cmd, ['--version'], { stdio: 'ignore' });
  if (probe.status !== 0) continue;

  const run = spawnSync(cmd, cmdArgs, { stdio: 'inherit' });
  if (run.error) {
    console.error(run.error.message);
    process.exit(1);
  }
  process.exit(run.status ?? 1);
}

console.error('Python 3 was not found on PATH.');
process.exit(127);
