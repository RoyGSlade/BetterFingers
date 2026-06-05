const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const appRoot = path.resolve(__dirname, '..');
const electronViteBin = process.platform === 'win32'
  ? path.join(appRoot, 'node_modules', '.bin', 'electron-vite.cmd')
  : path.join(appRoot, 'node_modules', '.bin', 'electron-vite');

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

if (env.BETTERFINGERS_PYTHON && /[\\/]/.test(env.BETTERFINGERS_PYTHON)) {
  const pythonPath = path.isAbsolute(env.BETTERFINGERS_PYTHON)
    ? env.BETTERFINGERS_PYTHON
    : path.resolve(appRoot, env.BETTERFINGERS_PYTHON);
  if (!fs.existsSync(pythonPath)) {
    delete env.BETTERFINGERS_PYTHON;
  }
}

const child = spawn(electronViteBin, ['dev'], {
  cwd: appRoot,
  env,
  stdio: 'inherit',
  shell: false,
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exit(code ?? 0);
});

child.on('error', (error) => {
  console.error(`Failed to start electron-vite dev: ${error.message}`);
  process.exit(1);
});
