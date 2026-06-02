const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const appRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(appRoot, '..');
const backendSource = path.join(repoRoot, 'server.py');
const backendOutputDir = path.join(appRoot, 'resources', 'backend');
const backendBuildDir = path.join(appRoot, '.electron-backend-build');

const dataSeparator = process.platform === 'win32' ? ';' : ':';
const dataSources = [
  ['config.yaml', '.'],
  ['context_rules.yaml', '.'],
  ['Tutorial_Script.txt', '.'],
  ['images', 'images'],
  ['assets', 'assets'],
];

function run(command, args, options = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: options.cwd || repoRoot,
      stdio: 'inherit',
      shell: false,
      env: {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
      },
    });

    child.on('error', rejectPromise);
    child.on('exit', (code) => {
      if (code === 0) {
        resolvePromise();
      } else {
        rejectPromise(new Error(`${command} exited with code ${code}`));
      }
    });
  });
}

function ensureBackendSourceExists() {
  if (!fs.existsSync(backendSource)) {
    throw new Error(`Unable to find backend source at ${backendSource}`);
  }
}

function addDataIfExists(args, source, target) {
  const sourcePath = path.join(repoRoot, source);
  if (!fs.existsSync(sourcePath)) {
    console.warn(`[build-backend] Skipping missing optional data path: ${sourcePath}`);
    return;
  }

  args.push('--add-data', `${sourcePath}${dataSeparator}${target}`);
}

async function main() {
  ensureBackendSourceExists();

  fs.mkdirSync(backendOutputDir, { recursive: true });
  for (const entry of fs.readdirSync(backendOutputDir)) {
    if (entry !== '.gitkeep') {
      fs.rmSync(path.join(backendOutputDir, entry), { recursive: true, force: true });
    }
  }

  fs.rmSync(backendBuildDir, { recursive: true, force: true });
  fs.mkdirSync(backendBuildDir, { recursive: true });

  const pyinstallerArgs = [
    '-m',
    'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onefile',
    '--name',
    'betterfingers-backend',
    '--distpath',
    backendOutputDir,
    '--workpath',
    path.join(backendBuildDir, 'work'),
    '--specpath',
    path.join(backendBuildDir, 'spec'),
  ];

  for (const [source, target] of dataSources) {
    addDataIfExists(pyinstallerArgs, source, target);
  }

  pyinstallerArgs.push(backendSource);

  await run('python', pyinstallerArgs, { cwd: repoRoot });
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
