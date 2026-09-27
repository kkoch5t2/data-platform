const { rmSync } = require('node:fs');
const { spawnSync } = require('node:child_process');
const { resolve } = require('node:path');

const root = resolve(__dirname, '..');

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: 'inherit',
    shell: false,
    env: process.env,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

if (process.platform !== 'win32') {
  run('bash', ['scripts/build-locked.sh']);
  process.exit(0);
}

rmSync(resolve(root, 'dist'), { recursive: true, force: true });
run(process.execPath, [resolve(root, 'node_modules/astro/bin/astro.mjs'), 'build']);
run(process.execPath, ['scripts/run-python.cjs', 'scripts/generate-sitemap.py']);
