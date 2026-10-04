// The installer ships the pinned Systran faster-whisper base.en model so the
// first dictation needs no download. These tests pin the build contract in
// app/scripts/build-backend.js:
//
//   * where the model bytes come from (env-var precedence + the dev skip flag),
//   * that the model is staged and hash-verified BEFORE PyInstaller runs,
//   * the --add-data mapping that lands it at _internal/bundled_models/base.en,
//   * that a bad source fails the build instead of falling back to the network,
//   * that the stage/download cache is short and never the user's HF cache.
//
// The planning functions are pure, so nothing here runs PyInstaller or touches
// app/resources/backend.
//
// Run with:  cd app && node --test tests/buildBackendModelBundle.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  backendBundleDir,
  bundledModelFrozenDir,
  bundledModelTarget,
  buildPyinstallerArgs,
  createStageRoot,
  dataSources,
  executeSteps,
  modelDownloadEnv,
  modelSkipEnv,
  modelSourceEnv,
  hubStateEnv,
  modelStageArgs,
  planBackendBuild,
  repoRoot,
  requiredDataSources,
  resolveModelBundlePlan,
  skipWarning,
  verifyShippedModel,
} from '../scripts/build-backend.js';

const appRoot = path.resolve(import.meta.dirname, '..');
const buildBackendSource = fs.readFileSync(path.join(appRoot, 'scripts', 'build-backend.js'), 'utf8');
const packageJson = JSON.parse(fs.readFileSync(path.join(appRoot, 'package.json'), 'utf8'));
const dataSeparator = process.platform === 'win32' ? ';' : ':';

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-model-bundle-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function mainBody() {
  const start = buildBackendSource.indexOf('async function main()');
  const end = buildBackendSource.indexOf('if (require.main === module)');
  assert.ok(start > 0 && end > start, 'could not isolate main() in build-backend.js');
  return buildBackendSource.slice(start, end);
}

test('the env var names are the documented ones', () => {
  assert.equal(modelSourceEnv, 'BETTERFINGERS_BUNDLED_MODEL_SOURCE');
  assert.equal(modelDownloadEnv, 'BETTERFINGERS_ALLOW_MODEL_DOWNLOAD');
  assert.equal(modelSkipEnv, 'BETTERFINGERS_SKIP_MODEL_BUNDLE');
});

// ---------------------------------------------------------------- precedence

test('precedence 1: a local source wins over download and skip, and the others are reported ignored', (t) => {
  const snapshot = tempDir(t);
  const plan = resolveModelBundlePlan({
    [modelSourceEnv]: snapshot,
    [modelDownloadEnv]: '1',
    [modelSkipEnv]: '1',
  });
  assert.deepEqual(plan, {
    mode: 'local',
    source: snapshot,
    ignored: [modelDownloadEnv, modelSkipEnv],
  });
});

test('precedence 2: the download switch wins over skip', () => {
  assert.deepEqual(
    resolveModelBundlePlan({ [modelDownloadEnv]: '1', [modelSkipEnv]: '1' }),
    { mode: 'download', ignored: [modelSkipEnv] },
  );
  assert.deepEqual(
    resolveModelBundlePlan({ [modelDownloadEnv]: '1' }),
    { mode: 'download', ignored: [] },
  );
});

test('precedence 3: skip applies only when nothing supplies the model', () => {
  assert.deepEqual(resolveModelBundlePlan({ [modelSkipEnv]: '1' }), { mode: 'skip', ignored: [] });
});

test('precedence 4: with no source, download or skip the build fails and says how to fix it', () => {
  assert.throws(
    () => resolveModelBundlePlan({}),
    (error) => {
      for (const name of [modelSourceEnv, modelDownloadEnv, modelSkipEnv]) {
        assert.ok(error.message.includes(name), `message must name ${name}`);
      }
      assert.match(error.message, /not release-ready/);
      assert.match(error.message, /bundled_manifest\.json/);
      return true;
    },
  );
});

test('only the exact value 1 enables the download and skip switches', () => {
  for (const value of ['true', 'yes', '0', '01', ' 1', 'TRUE']) {
    for (const name of [modelDownloadEnv, modelSkipEnv]) {
      assert.throws(
        () => resolveModelBundlePlan({ [name]: value }),
        (error) => error.message.includes(`${name} is set to "${value}"`) && /exact value 1/.test(error.message),
        `${name}=${JSON.stringify(value)} must not enable it`,
      );
    }
  }
});

test('empty and whitespace-only values count as unset (CI renders unset secrets as empty)', () => {
  assert.throws(() => resolveModelBundlePlan({ [modelSourceEnv]: '', [modelDownloadEnv]: '', [modelSkipEnv]: '' }));
  assert.throws(() => resolveModelBundlePlan({ [modelSourceEnv]: '   ' }));
  assert.deepEqual(
    resolveModelBundlePlan({ [modelSourceEnv]: '', [modelDownloadEnv]: '1' }),
    { mode: 'download', ignored: [] },
  );
});

test('a relative source resolves from the invocation cwd, not the repo root', (t) => {
  const base = tempDir(t);
  fs.mkdirSync(path.join(base, 'snap'));
  const plan = resolveModelBundlePlan({ [modelSourceEnv]: 'snap' }, base);
  assert.equal(plan.source, path.join(base, 'snap'));
});

test('a missing or non-directory source fails the build; it never falls back to download or skip', (t) => {
  const base = tempDir(t);
  const file = path.join(base, 'model.bin');
  fs.writeFileSync(file, 'x');
  for (const bad of [path.join(base, 'does-not-exist'), file]) {
    assert.throws(
      () => resolveModelBundlePlan({
        [modelSourceEnv]: bad,
        [modelDownloadEnv]: '1',
        [modelSkipEnv]: '1',
      }),
      (error) => error.message.includes(bad) && error.message.includes(modelSourceEnv),
    );
  }
});

test('the skip warning is loud and says the result is not release-ready', () => {
  const text = skipWarning();
  assert.match(text, /WARNING/);
  assert.match(text, /NOT release-ready/);
  assert.ok(text.includes(modelSkipEnv));
  assert.match(mainBody(), /console\.warn\(skipWarning\(\)\)/);
});

// ---------------------------------------------------- staging command / env

test('a local source stages with --from and never passes --allow-download', (t) => {
  const snapshot = tempDir(t);
  const plan = resolveModelBundlePlan({
    [modelSourceEnv]: snapshot,
    [modelDownloadEnv]: '1', // also set: must not become a network fallback
  });
  assert.deepEqual(modelStageArgs(plan, '/stage/base.en'), [
    '-m', 'tools.bundle_models', '--output-dir', '/stage/base.en', '--from', snapshot,
  ]);
});

test('download mode stages with --allow-download and no --from', () => {
  assert.deepEqual(modelStageArgs({ mode: 'download', ignored: [] }, '/stage/base.en'), [
    '-m', 'tools.bundle_models', '--output-dir', '/stage/base.en', '--allow-download',
  ]);
});

test('skip mode has no staging command', () => {
  assert.throws(() => modelStageArgs({ mode: 'skip', ignored: [] }, '/stage/base.en'));
});

test('Hugging Face and Xet state is redirected under the stage root', (t) => {
  const stageRoot = tempDir(t);
  const env = hubStateEnv(stageRoot);
  assert.deepEqual(Object.keys(env).sort(), ['HF_HOME', 'HF_XET_CACHE']);
  for (const value of Object.values(env)) {
    const relative = path.relative(stageRoot, value);
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative), `${value} must be inside ${stageRoot}`);
  }
  const homeCache = path.join(os.homedir(), '.cache', 'huggingface');
  for (const value of Object.values(env)) {
    assert.ok(!value.startsWith(homeCache), `${value} must not be the default Hugging Face cache`);
  }
});

test('the stage root is a short per-build temp dir outside the repo', (t) => {
  const base = tempDir(t);
  const stageRoot = createStageRoot(base);
  assert.equal(path.dirname(stageRoot), base);
  assert.match(path.basename(stageRoot), /^bfm-/);
  assert.equal(fs.statSync(stageRoot).isDirectory(), true);
  assert.notEqual(createStageRoot(base), stageRoot);
  assert.match(mainBody(), /createStageRoot\(\)/);
  assert.equal(path.relative(repoRoot, os.tmpdir()).startsWith('..'), true, 'temp dir must not be inside the repo');

  // Worst case under the stage root is the Hugging Face cache tree a pinned
  // download writes (bundle_staging.py: <stage temp>/download-cache/...). With
  // LongPathsEnabled=0 it must stay under 260 chars on a typical Windows temp.
  const typicalWindowsTemp = 'C:\\Users\\SomeLongUserName\\AppData\\Local\\Temp\\bfm-AbCdEf';
  const worstCase = path.win32.join(
    typicalWindowsTemp,
    '.base.en-stage-abcdefgh',
    'download-cache',
    'models--Systran--faster-whisper-base.en',
    'snapshots',
    '3d3d5dee26484f91867d81cb899cfcf72b96be6c',
    'model.bin',
  );
  assert.ok(worstCase.length < 230, `HF cache path ${worstCase.length} chars leaves too little margin under 260`);
});

// ------------------------------------------------------- ordering and wiring

test('the stage step runs before PyInstaller and PyInstaller adds exactly that directory', (t) => {
  const stageRoot = tempDir(t);
  const python = path.join(repoRoot, '.venv', 'python-stand-in');
  const snapshot = tempDir(t);
  const modelPlan = resolveModelBundlePlan({ [modelSourceEnv]: snapshot });
  const { modelStageDir, steps } = planBackendBuild({ python, modelPlan, stageRoot });

  assert.deepEqual(steps.map((step) => step.name), ['stage-model', 'pyinstaller']);
  const [stage, pyinstaller] = steps;
  assert.equal(modelStageDir, path.join(stageRoot, 'base.en'));

  assert.equal(stage.command, python);
  assert.equal(stage.cwd, repoRoot, 'tools.bundle_models is run as a module from the repo root');
  assert.deepEqual(stage.args, modelStageArgs(modelPlan, modelStageDir));
  assert.deepEqual(stage.env, hubStateEnv(stageRoot));

  assert.equal(pyinstaller.command, python);
  assert.equal(pyinstaller.cwd, repoRoot);
  assert.deepEqual(pyinstaller.args.slice(0, 2), ['-m', 'PyInstaller']);

  // The directory that was staged and verified is the directory that ships.
  const stagedOutput = stage.args[stage.args.indexOf('--output-dir') + 1];
  const addData = [];
  pyinstaller.args.forEach((arg, index) => {
    if (arg === '--add-data') addData.push(pyinstaller.args[index + 1]);
  });
  assert.ok(
    addData.includes(`${stagedOutput}${dataSeparator}${bundledModelTarget}`),
    `PyInstaller must --add-data ${stagedOutput}${dataSeparator}${bundledModelTarget}; got ${JSON.stringify(addData)}`,
  );
  assert.equal(addData.filter((value) => value.endsWith(`${dataSeparator}${bundledModelTarget}`)).length, 1);
});

test('download mode plans the same two steps with the pinned fetch switch', (t) => {
  const stageRoot = tempDir(t);
  const { steps } = planBackendBuild({
    python: 'python',
    modelPlan: resolveModelBundlePlan({ [modelDownloadEnv]: '1' }),
    stageRoot,
  });
  assert.deepEqual(steps.map((step) => step.name), ['stage-model', 'pyinstaller']);
  assert.ok(steps[0].args.includes('--allow-download'));
  assert.ok(!steps[0].args.includes('--from'));
});

test('skip mode plans PyInstaller only and adds no model data', (t) => {
  const stageRoot = tempDir(t);
  const { modelStageDir, steps } = planBackendBuild({
    python: 'python',
    modelPlan: resolveModelBundlePlan({ [modelSkipEnv]: '1' }),
    stageRoot,
  });
  assert.equal(modelStageDir, null);
  assert.deepEqual(steps.map((step) => step.name), ['pyinstaller']);
  assert.ok(!steps[0].args.some((arg) => arg.includes('bundled_models')));
});

test('every Python step of every mode keeps Hugging Face state out of the default cache', (t) => {
  // PyInstaller's analysis imports hf_xet (faster_whisper -> huggingface_hub),
  // which writes a log under ~/.cache/huggingface/xet even when nothing is
  // fetched, so the redirect covers the PyInstaller step and the dev skip build
  // too, not just the staging step.
  const stageRoot = tempDir(t);
  const snapshot = tempDir(t);
  for (const modelPlan of [
    resolveModelBundlePlan({ [modelSourceEnv]: snapshot }),
    resolveModelBundlePlan({ [modelDownloadEnv]: '1' }),
    resolveModelBundlePlan({ [modelSkipEnv]: '1' }),
  ]) {
    const { steps } = planBackendBuild({ python: 'python', modelPlan, stageRoot });
    assert.ok(steps.length >= 1);
    for (const step of steps) {
      assert.deepEqual(step.env, hubStateEnv(stageRoot), `${modelPlan.mode}/${step.name} must redirect HF state`);
    }
  }
});

test('planning a build without a stage root is a programming error, not a silent default', () => {
  for (const mode of ['local', 'download', 'skip']) {
    assert.throws(() => planBackendBuild({
      python: 'python',
      modelPlan: { mode, source: '/snap', ignored: [] },
      stageRoot: null,
    }));
  }
});

test('the add-data mapping lands the model where the frozen runtime looks', () => {
  assert.equal(bundledModelTarget, 'bundled_models/base.en');
  assert.equal(
    bundledModelFrozenDir,
    path.join(backendBundleDir, '_internal', 'bundled_models', 'base.en'),
  );
  // Cross-language contract: backend/stt/bundled_models.py resolves the frozen
  // location as <_MEIPASS>/bundled_models/base.en, and _MEIPASS is _internal.
  const runtime = fs.readFileSync(path.join(repoRoot, 'backend', 'stt', 'bundled_models.py'), 'utf8');
  assert.match(runtime, /Path\(sys\._MEIPASS\)\s*\/\s*"bundled_models"/);
  assert.match(runtime, /root\s*\/\s*"base\.en"/);
  assert.match(buildBackendSource, /'--contents-directory',\s*'_internal'/);
});

test('the model rides in the existing backend resource; no second 148 MB payload entry', () => {
  const extraResources = packageJson.build.extraResources;
  assert.equal(extraResources.some((entry) => JSON.stringify(entry).includes('bundled_models')), false);
  assert.equal(extraResources.some((entry) => /model/i.test(entry.from || '')), false);
  assert.ok(extraResources.some((entry) => entry.from === 'resources/backend' && entry.to === 'backend'));
});

test('the manifest, license inventory and model notices are shipped and are required, not warn-and-skip', () => {
  const manifest = ['backend/stt/bundled_manifest.json', 'backend/stt'];
  const licenses = ['LICENSES-MODELS.md', '.'];
  const notices = ['licenses/bundled-base.en-NOTICE.txt', '.'];
  assert.deepEqual(dataSources.find(([source]) => source === manifest[0]), manifest);
  assert.deepEqual(dataSources.find(([source]) => source === licenses[0]), licenses);
  assert.deepEqual(dataSources.find(([source]) => source === notices[0]), notices);
  assert.deepEqual([...requiredDataSources].sort(), [manifest[0], licenses[0], notices[0]].sort());
  for (const source of requiredDataSources) {
    assert.equal(fs.existsSync(path.join(repoRoot, source)), true, `${source} must exist in the repo`);
  }
  // MIT: both upstream copyright lines must travel with the weights.
  const noticeText = fs.readFileSync(path.join(repoRoot, notices[0]), 'utf8');
  assert.match(noticeText, /Copyright \(c\) 2022 OpenAI/);
  assert.match(noticeText, /Copyright \(c\) 2023 SYSTRAN/);
  assert.match(noticeText, /3d3d5dee26484f91867d81cb899cfcf72b96be6c/);
  const args = buildPyinstallerArgs({ modelStageDir: null });
  for (const [source, target] of [manifest, licenses, notices]) {
    assert.ok(
      args.includes(`${path.join(repoRoot, source)}${dataSeparator}${target}`),
      `PyInstaller must add ${source} -> ${target}`,
    );
  }
});

test('executeSteps runs steps in order and passes cwd/env through', async () => {
  const calls = [];
  const steps = [
    { name: 'a', description: 'a', command: 'py', args: ['1'], cwd: '/repo', env: { X: '1' } },
    { name: 'b', description: 'b', command: 'py', args: ['2'], cwd: '/repo' },
  ];
  await executeSteps(steps, async (command, args, options) => {
    calls.push({ command, args, options });
  });
  assert.deepEqual(calls, [
    { command: 'py', args: ['1'], options: { cwd: '/repo', env: { X: '1' } } },
    { command: 'py', args: ['2'], options: { cwd: '/repo', env: undefined } },
  ]);
});

test('a failing stage step stops the build before PyInstaller ever starts', async (t) => {
  const stageRoot = tempDir(t);
  const { steps } = planBackendBuild({
    python: 'python',
    modelPlan: resolveModelBundlePlan({ [modelDownloadEnv]: '1' }),
    stageRoot,
  });
  const started = [];
  await assert.rejects(
    () => executeSteps(steps, async (command, args) => {
      started.push(args[1] === 'tools.bundle_models' ? 'stage-model' : 'pyinstaller');
      if (args[1] === 'tools.bundle_models') {
        throw new Error('python exited with code 1');
      }
    }),
    /exited with code 1/,
  );
  assert.deepEqual(started, ['stage-model']);
});

test('main resolves the model source before it wipes anything, and verifies the frozen copy after PyInstaller', () => {
  const body = mainBody();
  const at = (needle) => {
    const index = body.indexOf(needle);
    assert.ok(index >= 0, `main() must contain ${needle}`);
    return index;
  };
  const resolve = at('resolveModelBundlePlan()');
  assert.ok(resolve < at('fs.rmSync(path.join(backendOutputDir'), 'a bad model config must not cost the previous backend build');
  assert.ok(resolve < at('fs.rmSync(backendBuildDir'));
  assert.ok(at('await verifyPythonEnvironment(python)') < at('createStageRoot()'));
  assert.ok(at('createStageRoot()') < at('planBackendBuild('));
  assert.ok(at('planBackendBuild(') < at('await executeSteps(steps)'));
  assert.ok(at('await executeSteps(steps)') < at('await verifyShippedModel(python'));
  // The temp stage root (and any download cache in it) is always removed.
  assert.match(body, /finally\s*\{[\s\S]*fs\.rmSync\(stageRoot,\s*\{\s*recursive:\s*true,\s*force:\s*true\s*\}\)/);
});

test('verifyShippedModel fails clearly when PyInstaller left no model behind', async (t) => {
  const missing = path.join(tempDir(t), 'nope');
  let called = false;
  await assert.rejects(
    () => verifyShippedModel('python', { dir: missing, runner: async () => { called = true; } }),
    (error) => error.message.includes(missing) && /bundled speech model/.test(error.message),
  );
  assert.equal(called, false);
});

test('verifyShippedModel re-verifies the frozen directory through tools.bundle_models', async (t) => {
  const dir = tempDir(t);
  const calls = [];
  const env = hubStateEnv(dir);
  await verifyShippedModel('python', {
    dir,
    env,
    runner: async (command, args, options) => { calls.push({ command, args, options }); },
  });
  assert.deepEqual(calls, [{
    command: 'python',
    args: ['-m', 'tools.bundle_models', '--output-dir', dir],
    options: { cwd: repoRoot, env },
  }]);
});
