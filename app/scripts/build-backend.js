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
  // The one build version source (D-0008). version.py reads it at import, and
  // raises if it is missing rather than reporting a guessed version into a
  // support report — so the frozen sidecar must carry it or it will not start.
  ['VERSION', '.'],
  ['config.yaml', '.'],
  ['context_rules.yaml', '.'],
  ['Tutorial_Script.txt', '.'],
];

// Packages PyInstaller can't fully trace on its own. `collect-all` pulls in data
// files, binaries, and submodules; these are the sidecar's runtime deps only —
// the legacy flet/tkinter UI is intentionally excluded from the backend bundle.
const collectAllPackages = [
  'kokoro_onnx',
  'espeakng_loader',
  'language_tags',
  'faster_whisper',
];
const hiddenImports = [
  'ctranslate2',
  'sounddevice',
  'av',
];

function repoVenvPython() {
  const venvPython = process.platform === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python');
  return fs.existsSync(venvPython) ? venvPython : null;
}

// This repo's runtime dependencies (fastapi, PyInstaller, etc.) live ONLY in
// the repo-local .venv. A bare `python3`/`python` resolves to the system
// interpreter, which lacks them — that either fails outright or produces a
// sidecar broken in ways that only surface at runtime. Prefer, in order: an
// explicit override, the repo venv, then the platform default (documented as
// a last resort, not something this build is actually expected to work with).
function resolvePython() {
  const explicit = process.env.BETTERFINGERS_PYTHON;
  if (explicit) {
    const resolved = path.isAbsolute(explicit)
      ? explicit
      : path.resolve(process.cwd(), explicit);
    console.log(`[build-backend] Using BETTERFINGERS_PYTHON override: ${resolved}`);
    return resolved;
  }

  const venvPython = repoVenvPython();
  if (venvPython) {
    console.log(`[build-backend] Using repo-local venv interpreter: ${venvPython}`);
    return venvPython;
  }

  const platformDefault = process.platform === 'win32' ? 'python' : 'python3';
  console.warn(
    `[build-backend] No repo-local .venv found at ${path.join(repoRoot, '.venv')}; ` +
    `falling back to platform default "${platformDefault}". This is unlikely to have ` +
    'the required dependencies — set BETTERFINGERS_PYTHON or create the venv.',
  );
  return platformDefault;
}

// PyInstaller failures deep inside its own traceback (missing fastapi, etc.)
// are confusing and don't name the interpreter that caused them. Check the
// two things that actually need to be true — PyInstaller itself, and one
// representative runtime dependency — before spending time on a build.
async function verifyPythonEnvironment(python) {
  const probeModules = ['PyInstaller', 'fastapi'];
  for (const moduleName of probeModules) {
    try {
      await run(python, ['-c', `import ${moduleName}`], { cwd: repoRoot });
    } catch (error) {
      throw new Error(
        `[build-backend] The interpreter "${python}" cannot import "${moduleName}". ` +
        `Set BETTERFINGERS_PYTHON to an interpreter that has the project's dependencies ` +
        `installed, or create the repo venv (.venv) and install requirements into it.`,
      );
    }
  }
}

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

  for (const pkg of collectAllPackages) {
    pyinstallerArgs.push('--collect-all', pkg);
  }

  for (const mod of hiddenImports) {
    pyinstallerArgs.push('--hidden-import', mod);
  }

  pyinstallerArgs.push(backendSource);

  const python = resolvePython();
  await verifyPythonEnvironment(python);
  console.log(`[build-backend] Building sidecar with ${python} (PyInstaller onefile)…`);
  await run(python, pyinstallerArgs, { cwd: repoRoot });
  console.log(`[build-backend] Backend written to ${backendOutputDir}`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message || error);
    process.exit(1);
  });
}

module.exports = {
  dataSources,
  repoRoot,
  repoVenvPython,
  resolvePython,
  verifyPythonEnvironment,
};
