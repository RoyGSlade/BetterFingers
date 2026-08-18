const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const appRoot = path.resolve(__dirname, '..');

function resolveElectronViteEntrypoint(root = appRoot) {
  const packageMain = require.resolve('electron-vite', { paths: [root] });
  return path.resolve(path.dirname(packageMain), '..', 'bin', 'electron-vite.js');
}

function resolveElectronViteCommand({ platform = process.platform, root = appRoot, execPath = process.execPath } = {}) {
  if (platform === 'win32') {
    return {
      command: execPath,
      args: [resolveElectronViteEntrypoint(root), 'dev'],
    };
  }

  return {
    command: path.join(root, 'node_modules', '.bin', 'electron-vite'),
    args: ['dev'],
  };
}

function buildEnvironment(source = process.env, root = appRoot) {
  const env = { ...source };
  delete env.ELECTRON_RUN_AS_NODE;

  if (env.BETTERFINGERS_PYTHON && /[\\/]/.test(env.BETTERFINGERS_PYTHON)) {
    const pythonPath = path.isAbsolute(env.BETTERFINGERS_PYTHON)
      ? env.BETTERFINGERS_PYTHON
      : path.resolve(root, env.BETTERFINGERS_PYTHON);
    if (!fs.existsSync(pythonPath)) {
      delete env.BETTERFINGERS_PYTHON;
    }
  }

  return env;
}

function runDev({ platform = process.platform, root = appRoot, execPath = process.execPath, spawnProcess = spawn } = {}) {
  const { command, args } = resolveElectronViteCommand({ platform, root, execPath });
  const child = spawnProcess(command, args, {
    cwd: root,
    env: buildEnvironment(process.env, root),
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

  return child;
}

if (require.main === module) {
  runDev();
}

module.exports = {
  appRoot,
  buildEnvironment,
  resolveElectronViteCommand,
  resolveElectronViteEntrypoint,
  runDev,
};
