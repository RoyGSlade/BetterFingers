const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const appRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(appRoot, '..');
const backendSource = path.join(repoRoot, 'server.py');
const backendOutputDir = path.join(appRoot, 'resources', 'backend');
const backendBuildDir = path.join(appRoot, '.electron-backend-build');
const backendBundleName = 'betterfingers-backend';
const backendBundleDir = path.join(backendOutputDir, backendBundleName);
const backendExecutableName = process.platform === 'win32'
  ? `${backendBundleName}.exe`
  : backendBundleName;
const backendExecutablePath = path.join(backendBundleDir, backendExecutableName);

const dataSeparator = process.platform === 'win32' ? ';' : ':';
const dataSources = [
  // The one build version source (D-0008). version.py reads it at import, and
  // raises if it is missing rather than reporting a guessed version into a
  // support report — so the frozen sidecar must carry it or it will not start.
  ['VERSION', '.'],
  ['config.yaml', '.'],
  ['context_rules.yaml', '.'],
  ['Tutorial_Script.txt', '.'],
  // The pinned per-file size/SHA-256 manifest for the bundled speech model.
  // backend.stt.bundled_models reads it with importlib.resources, so the frozen
  // package directory must carry it next to the module.
  ['backend/stt/bundled_manifest.json', 'backend/stt'],
  // Model/runtime license inventory (MIT notice trail for the bundled weights).
  ['LICENSES-MODELS.md', '.'],
  // The verbatim OpenAI Whisper + SYSTRAN MIT notices MIT requires us to ship
  // with the bundled base.en weights.
  ['licenses/bundled-base.en-NOTICE.txt', '.'],
];

// These are not optional the way the other data files are treated: a build that
// warned and skipped them would still "succeed" and ship a backend that cannot
// verify its bundled model, or an installer without its license notices.
const requiredDataSources = [
  'backend/stt/bundled_manifest.json',
  'LICENSES-MODELS.md',
  'licenses/bundled-base.en-NOTICE.txt',
];

// The installer ships the pinned Systran faster-whisper base.en model so the
// first dictation needs no download (docs/design/FIRST_RUN.md §5). It is staged
// and hash-verified by tools/bundle_models.py (backend/stt/bundle_staging.py)
// BEFORE PyInstaller runs, then added to the frozen backend, where
// backend.stt.bundled_models looks for it at _MEIPASS/bundled_models/base.en.
// Where the model bytes come from is chosen by exactly one of these env vars,
// in this precedence (see resolveModelBundlePlan):
const modelSourceEnv = 'BETTERFINGERS_BUNDLED_MODEL_SOURCE'; // local snapshot dir
const modelDownloadEnv = 'BETTERFINGERS_ALLOW_MODEL_DOWNLOAD'; // === '1': pinned fetch
const modelSkipEnv = 'BETTERFINGERS_SKIP_MODEL_BUNDLE'; // === '1': dev-only skip
// Destination of the model inside the PyInstaller contents directory (_internal).
const bundledModelTarget = 'bundled_models/base.en';
const bundledModelFrozenDir = path.join(
  backendBundleDir, '_internal', 'bundled_models', 'base.en',
);

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
        ...(options.env || {}),
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
    if (requiredDataSources.includes(source)) {
      throw new Error(`[build-backend] Required data path is missing: ${sourcePath}`);
    }
    console.warn(`[build-backend] Skipping missing optional data path: ${sourcePath}`);
    return;
  }

  args.push('--add-data', `${sourcePath}${dataSeparator}${target}`);
}

function missingModelSourceMessage(env) {
  // CI systems often render a boolean as "true"; only the exact value 1 counts,
  // so say so instead of leaving the operator to guess why it was ignored.
  const notExactlyOne = [modelDownloadEnv, modelSkipEnv]
    .filter((name) => env[name] !== undefined && env[name] !== '' && env[name] !== '1')
    .map((name) => `  ${name} is set to "${env[name]}", but only the exact value 1 enables it.`);
  return [
    '[build-backend] No source for the bundled speech model (Systran faster-whisper base.en).',
    'The installer ships that model so the first dictation needs no download, so this',
    'build must be told where the bytes come from. Set exactly one of:',
    `  ${`${modelSourceEnv}=<dir>`.padEnd(46)}a local snapshot directory; verified against backend/stt/bundled_manifest.json`,
    `  ${`${modelDownloadEnv}=1`.padEnd(46)}fetch the pinned revision from Hugging Face (hash-verified; release/CI)`,
    `  ${`${modelSkipEnv}=1`.padEnd(46)}DEV ONLY: build without the model; the result is not release-ready`,
    ...notExactlyOne,
  ].join('\n');
}

// Where the bundled model bytes come from. Precedence is fixed:
//   1. BETTERFINGERS_BUNDLED_MODEL_SOURCE=<dir>   -> mode 'local'
//   2. BETTERFINGERS_ALLOW_MODEL_DOWNLOAD=1       -> mode 'download'
//   3. BETTERFINGERS_SKIP_MODEL_BUNDLE=1          -> mode 'skip' (dev only)
//   4. none of the above                          -> throw
// The skip flag only applies when nothing else supplies the model, so a release
// pipeline that has a source or the download switch can never silently ship
// without the model because a stray skip flag is also set. `ignored` lists any
// lower-precedence switches that were set but not used, so main() can say so.
// Only the exact value '1' enables a switch.
function resolveModelBundlePlan(env = process.env, cwd = process.cwd()) {
  const source = (env[modelSourceEnv] || '').trim();
  const download = env[modelDownloadEnv] === '1';
  const skip = env[modelSkipEnv] === '1';

  if (source) {
    // The staging step runs with cwd=repoRoot, so a relative path must be
    // anchored to where the operator typed it (same rule as BETTERFINGERS_PYTHON).
    const resolved = path.resolve(cwd, source);
    let isDirectory = false;
    try {
      isDirectory = fs.statSync(resolved).isDirectory();
    } catch {
      // reported below
    }
    if (!isDirectory) {
      throw new Error(
        `[build-backend] ${modelSourceEnv} must name an existing directory (a model snapshot ` +
        `containing config.json, model.bin, tokenizer.json, vocabulary.txt): ${resolved}`,
      );
    }
    return {
      mode: 'local',
      source: resolved,
      ignored: [download && modelDownloadEnv, skip && modelSkipEnv].filter(Boolean),
    };
  }
  if (download) {
    return { mode: 'download', ignored: skip ? [modelSkipEnv] : [] };
  }
  if (skip) {
    return { mode: 'skip', ignored: [] };
  }
  throw new Error(missingModelSourceMessage(env));
}

// Arguments for `python -m tools.bundle_models`. A local source passes ONLY
// --from: an explicit source that fails verification must fail the build, never
// fall back to the network. --allow-download is passed only for mode 'download'.
function modelStageArgs(plan, stageDir) {
  const args = ['-m', 'tools.bundle_models', '--output-dir', stageDir];
  if (plan.mode === 'local') {
    args.push('--from', plan.source);
  } else if (plan.mode === 'download') {
    args.push('--allow-download');
  } else {
    throw new Error(`[build-backend] No model staging step for mode "${plan.mode}"`);
  }
  return args;
}

// Hugging Face state for EVERY Python step of the build lives under the (short)
// stage root, so a build never writes into the developer's ~/.cache/huggingface:
// not the Xet chunk cache or Xet logs (HF_XET_CACHE relocates both), and not the
// hub cache. This is needed even when no model is fetched: PyInstaller's
// analysis of faster_whisper/huggingface_hub imports hf_xet, which creates a log
// file in the default ~/.cache/huggingface/xet/logs on every build.
function hubStateEnv(stageRoot) {
  return {
    HF_HOME: path.join(stageRoot, 'hf-home'),
    HF_XET_CACHE: path.join(stageRoot, 'xet'),
  };
}

function buildPyinstallerArgs({ modelStageDir = null } = {}) {
  const pyinstallerArgs = [
    '-m',
    'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onedir',
    '--contents-directory',
    '_internal',
    '--name',
    backendBundleName,
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

  if (modelStageDir) {
    pyinstallerArgs.push('--add-data', `${modelStageDir}${dataSeparator}${bundledModelTarget}`);
  }

  for (const pkg of collectAllPackages) {
    pyinstallerArgs.push('--collect-all', pkg);
  }

  for (const mod of hiddenImports) {
    pyinstallerArgs.push('--hidden-import', mod);
  }

  pyinstallerArgs.push(backendSource);
  return pyinstallerArgs;
}

// The ordered commands of a backend build. Pure (no filesystem or process
// effects) so the contract "stage and verify the model BEFORE PyInstaller" is
// testable. `stageRoot` is a short directory the caller owns (required in every
// mode): the model is staged to <stageRoot>/base.en, which is what PyInstaller
// then adds, and every step's Hugging Face state is redirected under it.
//
// Keep the stage root SHORT: a hash-verified fetch writes a Hugging Face cache
// tree (models--Systran--faster-whisper-base.en/snapshots/<40 hex>/model.bin)
// under it, and with LongPathsEnabled=0 a build tree under a long checkout path
// exceeded the 260-character Windows limit.
function planBackendBuild({ python, modelPlan, stageRoot }) {
  if (!stageRoot) {
    throw new Error('[build-backend] A stage root is required to plan a backend build');
  }
  const env = hubStateEnv(stageRoot);
  const steps = [];
  let modelStageDir = null;
  if (modelPlan.mode !== 'skip') {
    modelStageDir = path.join(stageRoot, 'base.en');
    steps.push({
      name: 'stage-model',
      description: `Staging and verifying the bundled base.en model (${modelPlan.mode})…`,
      command: python,
      args: modelStageArgs(modelPlan, modelStageDir),
      env,
      cwd: repoRoot,
    });
  }
  steps.push({
    name: 'pyinstaller',
    description: `Building sidecar with ${python} (PyInstaller onedir)…`,
    command: python,
    args: buildPyinstallerArgs({ modelStageDir }),
    env,
    cwd: repoRoot,
  });
  return { modelStageDir, steps };
}

// Runs steps in order and stops at the first failure, so a model that fails
// verification never reaches PyInstaller.
async function executeSteps(steps, runner = run) {
  for (const step of steps) {
    console.log(`[build-backend] ${step.description}`);
    await runner(step.command, step.args, { cwd: step.cwd, env: step.env });
  }
}

// After PyInstaller: re-verify the bytes that will actually ship against the
// manifest. `tools.bundle_models` on an existing output directory only verifies
// it (valid -> no-op, invalid -> refused), so this catches an --add-data
// mapping mistake or a mangled copy before the installer is packaged.
async function verifyShippedModel(python, { dir = bundledModelFrozenDir, runner = run, env } = {}) {
  if (!fs.existsSync(dir)) {
    throw new Error(
      `[build-backend] PyInstaller completed without the bundled speech model at ${dir}`,
    );
  }
  console.log('[build-backend] Verifying the bundled speech model inside the frozen backend…');
  await runner(python, ['-m', 'tools.bundle_models', '--output-dir', dir], { cwd: repoRoot, env });
}

// A fresh, SHORT, per-build directory outside the repo (see planBackendBuild and
// hubStateEnv). Always created, including for the dev skip build.
function createStageRoot(tmpBase = os.tmpdir()) {
  return fs.mkdtempSync(path.join(tmpBase, 'bfm-'));
}

function skipWarning() {
  const bar = '='.repeat(72);
  return [
    bar,
    `[build-backend] WARNING: ${modelSkipEnv}=1 - building WITHOUT the bundled speech model.`,
    '[build-backend] This backend is NOT release-ready: the first dictation would have to',
    '[build-backend] download base.en. Never package, sign, or publish an installer from it.',
    bar,
  ].join('\n');
}

async function main() {
  ensureBackendSourceExists();

  // Decide the model source BEFORE wiping anything: a missing or wrong
  // configuration must not cost the developer their existing app/resources/backend.
  const modelPlan = resolveModelBundlePlan();
  if (modelPlan.mode === 'skip') {
    console.warn(skipWarning());
  } else if (modelPlan.mode === 'local') {
    console.log(`[build-backend] Bundled model source: local snapshot ${modelPlan.source}`);
  } else {
    console.log(
      `[build-backend] Bundled model source: pinned Hugging Face fetch (${modelDownloadEnv}=1)`,
    );
  }
  for (const name of modelPlan.ignored) {
    console.warn(
      `[build-backend] NOTE: ${name}=1 is also set but ignored; ` +
      (name === modelSkipEnv
        ? 'the model WILL be bundled.'
        : `the model comes from ${modelSourceEnv}, with no download fallback.`),
    );
  }

  fs.mkdirSync(backendOutputDir, { recursive: true });
  for (const entry of fs.readdirSync(backendOutputDir)) {
    if (entry !== '.gitkeep') {
      fs.rmSync(path.join(backendOutputDir, entry), { recursive: true, force: true });
    }
  }

  fs.rmSync(backendBuildDir, { recursive: true, force: true });
  fs.mkdirSync(backendBuildDir, { recursive: true });

  const python = resolvePython();
  await verifyPythonEnvironment(python);

  // Short, per-build temp root (never under the repo): holds the staged model,
  // the download cache for 'download' mode, and all Hugging Face state.
  const stageRoot = createStageRoot();
  try {
    const { steps } = planBackendBuild({ python, modelPlan, stageRoot });
    await executeSteps(steps);
    if (!fs.existsSync(backendExecutablePath)) {
      throw new Error(
        `[build-backend] PyInstaller completed without the expected onedir executable: ` +
        `${backendExecutablePath}`,
      );
    }
    if (modelPlan.mode !== 'skip') {
      await verifyShippedModel(python, { env: hubStateEnv(stageRoot) });
    }
  } finally {
    fs.rmSync(stageRoot, { recursive: true, force: true });
  }
  console.log(`[build-backend] Backend bundle written to ${backendBundleDir}`);
  if (modelPlan.mode === 'skip') {
    console.warn('[build-backend] (built WITHOUT the bundled speech model: not release-ready)');
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message || error);
    process.exit(1);
  });
}

module.exports = {
  backendBundleDir,
  backendBundleName,
  backendExecutableName,
  backendExecutablePath,
  backendOutputDir,
  bundledModelFrozenDir,
  bundledModelTarget,
  buildPyinstallerArgs,
  createStageRoot,
  dataSources,
  executeSteps,
  modelDownloadEnv,
  modelSkipEnv,
  modelSourceEnv,
  modelStageArgs,
  hubStateEnv,
  planBackendBuild,
  repoRoot,
  repoVenvPython,
  requiredDataSources,
  resolveModelBundlePlan,
  resolvePython,
  skipWarning,
  verifyPythonEnvironment,
  verifyShippedModel,
};
