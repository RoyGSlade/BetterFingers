import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

import {
  backendBundleDir,
  backendBundleName,
  backendExecutableName,
  backendExecutablePath,
  backendOutputDir,
  dataSources,
} from '../scripts/build-backend.js';

const appRoot = path.resolve(import.meta.dirname, '..');
const packageJson = JSON.parse(fs.readFileSync(path.join(appRoot, 'package.json'), 'utf8'));
const uiohookNegation = '!node_modules/uiohook-napi/prebuilds/{darwin-*,linux-*,win32-arm64}/**/*';

test('packaged tray resources include only the four indicator assets', () => {
  const resources = packageJson.build.extraResources;
  const assetResource = resources.find(({ from }) => from === '../assets');

  assert.deepEqual(assetResource, {
    from: '../assets',
    to: 'assets',
    filter: [
      'indicator_idle.png',
      'indicator_listening.png',
      'indicator_processing.png',
      'indicator_recording.png',
    ],
  });
  assert.equal(resources.some(({ from }) => from === '../images'), false);
});

test('backend sidecar data excludes root assets and images', () => {
  assert.equal(dataSources.some(([source]) => source === 'assets' || source === 'images'), false);
});

test('backend packaging pins a recursive PyInstaller onedir resource contract', () => {
  const buildBackendSource = fs.readFileSync(path.join(appRoot, 'scripts', 'build-backend.js'), 'utf8');
  assert.match(buildBackendSource, /'--onedir'/);
  assert.match(buildBackendSource, /'--contents-directory',\s*'_internal'/);
  assert.doesNotMatch(buildBackendSource, /'--onefile'/);

  assert.equal(backendBundleName, 'betterfingers-backend');
  assert.equal(backendOutputDir, path.join(appRoot, 'resources', 'backend'));
  assert.equal(backendBundleDir, path.join(backendOutputDir, backendBundleName));
  assert.ok(
    ['betterfingers-backend', 'betterfingers-backend.exe'].includes(backendExecutableName),
    `unexpected backend executable name: ${backendExecutableName}`,
  );
  assert.equal(backendExecutablePath, path.join(backendBundleDir, backendExecutableName));

  const backendResource = packageJson.build.extraResources.find(({ from }) => from === 'resources/backend');
  assert.deepEqual(backendResource, {
    from: 'resources/backend',
    to: 'backend',
    filter: ['**/*', '!.gitkeep'],
  });
});

test('Linux package identity aligns Electron and desktop-entry names', () => {
  assert.equal(packageJson.version, '1.1.0-alpha.4');
  assert.equal(packageJson.author, 'Donaven Crenshaw');
  assert.equal(packageJson.desktopName, 'BetterFingers');
  assert.equal(packageJson.build.appId, 'com.betterfingers.desktop');
  assert.equal(packageJson.build.productName, 'BetterFingers');
  assert.deepEqual(packageJson.build.linux.executableArgs, []);
  assert.equal(packageJson.build.linux.syncDesktopName, true);
});

test('Windows package identity and assisted installer metadata are explicit', () => {
  assert.equal(packageJson.license, 'MIT');
  assert.equal(packageJson.description, 'Private, local-first dictation for Windows and Linux.');
  assert.equal(packageJson.homepage, 'https://github.com/RoyGSlade/BetterFingers');
  assert.equal(packageJson.build.copyright, 'Copyright © 2026 Donaven Crenshaw');
  assert.equal(packageJson.build.win.icon, 'build/icon.ico');
  assert.equal(packageJson.build.win.executableName, 'BetterFingers');
  assert.equal(packageJson.build.win.requestedExecutionLevel, 'asInvoker');
  assert.deepEqual(packageJson.build.win.target, [{ target: 'nsis', arch: ['x64'] }]);
  assert.equal(packageJson.build.nsis.oneClick, false);
  assert.equal(packageJson.build.nsis.perMachine, false);
  assert.equal(packageJson.build.nsis.allowElevation, false);
  assert.equal(packageJson.build.nsis.packElevateHelper, false);
  assert.equal(packageJson.build.nsis.createStartMenuShortcut, true);
  assert.equal(packageJson.build.nsis.createDesktopShortcut, false);
  assert.equal(packageJson.build.nsis.artifactName, 'BetterFingers-Setup-${version}-${arch}.${ext}');
  assert.equal(packageJson.build.nsis.installerIcon, 'build/icon.ico');
  assert.equal(packageJson.build.nsis.uninstallerIcon, 'build/icon.ico');
  assert.equal(packageJson.build.nsis.license, '../LICENSE');
  assert.equal(packageJson.build.nsis.deleteAppDataOnUninstall, false);
  assert.equal(packageJson.build.nsis.allowToChangeInstallationDirectory, false);
  assert.equal(packageJson.build.nsis.include, 'build/installer.nsh');
  assert.equal('publisherName' in packageJson.build.win, false, 'set this only after the certificate subject is known');
});

test('Windows update dependency and publish-never build contracts are pinned', () => {
  assert.equal(packageJson.dependencies['electron-updater'], '6.8.9');
  for (const script of ['dist', 'dist:win', 'dist:linux']) {
    assert.match(packageJson.scripts[script], /--publish never(?:\s|$)/, `${script} must never upload during packaging`);
  }
});

test('effective builder config emits a fixed public GitHub channel feed', () => {
  const configPath = path.join(appRoot, 'electron-builder.config.cjs');
  const loadForVersion = (version) => spawnSync(
    process.execPath,
    ['-e', `
      const Module = require('node:module');
      const originalLoad = Module._load;
      Module._load = function (request, parent, isMain) {
        if (request === './package.json' && parent && parent.filename === ${JSON.stringify(configPath)}) {
          const pkg = originalLoad.call(this, request, parent, isMain);
          return { ...pkg, version: ${JSON.stringify(version)} };
        }
        return originalLoad.call(this, request, parent, isMain);
      };
      process.stdout.write(JSON.stringify(require(${JSON.stringify(configPath)})));
    `],
    { encoding: 'utf8', env: { ...process.env, BETTERFINGERS_SIGNING_MODE: '' } },
  );
  const loaded = loadForVersion('1.1.0-alpha.4');
  assert.equal(loaded.status, 0, loaded.stderr);
  const config = JSON.parse(loaded.stdout);
  assert.equal(config.appId, 'com.betterfingers.desktop');
  assert.equal(config.generateUpdatesFilesForAllChannels, false);
  assert.deepEqual(config.publish, [{
    provider: 'github',
    owner: 'RoyGSlade',
    repo: 'BetterFingers',
    channel: 'alpha',
  }]);

  const stable = loadForVersion('1.1.0');
  assert.equal(stable.status, 0, stable.stderr);
  assert.equal(JSON.parse(stable.stdout).publish[0].channel, 'latest');
});

test('the intended Windows icon sources exist in the tracked package input directory', () => {
  for (const file of ['icon.png', 'icon.ico']) {
    assert.equal(fs.existsSync(path.join(appRoot, 'build', file)), true, `${file} must be present for CI packaging`);
  }
});

test('Azure Artifact Signing config is exact and only enabled explicitly', () => {
  const configPath = path.join(appRoot, 'electron-builder.config.cjs');
  const publisherName = 'CN=Donaven Crenshaw, O=Donaven Crenshaw, C=US';
  const loadConfig = (env = {}) => spawnSync(
    process.execPath,
    ['-e', `process.stdout.write(JSON.stringify(require(${JSON.stringify(configPath)})))`],
    { encoding: 'utf8', env: { ...process.env, ...env } },
  );
  const loadHookType = (mode) => spawnSync(
    process.execPath,
    ['-e', `process.stdout.write(typeof require(${JSON.stringify(configPath)}).win.signtoolOptions.sign)`],
    {
      encoding: 'utf8',
      env: { ...process.env, BETTERFINGERS_SIGNING_MODE: mode },
    },
  );

  // '' is a plain `npm run dist:win`; 'unsigned' is what the CI qualification
  // step sets explicitly. Both must pin the publisher without any signing hook.
  for (const unsignedMode of ['', 'unsigned']) {
    const unsigned = loadConfig({
      BETTERFINGERS_SIGNING_MODE: unsignedMode,
      AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: '',
      AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: '',
    });
    assert.equal(unsigned.status, 0, unsigned.stderr);
    const unsignedConfig = JSON.parse(unsigned.stdout);
    assert.equal('azureSignOptions' in unsignedConfig.win, false);
    assert.deepEqual(unsignedConfig.win.signtoolOptions, { publisherName });
    assert.equal('sign' in unsignedConfig.win.signtoolOptions, false);
    assert.equal('forceCodeSigning' in unsignedConfig, false);
    // The x64-only Windows package drops every non-win32-x64 uiohook prebuild;
    // the filter is Windows-scoped, so it must not leak into the shared files.
    // A platform list holding only that negation would make electron-builder
    // pack all of app/ into app.asar, so it must repeat the root patterns; the
    // 'effective electron-builder file patterns' tests below check what that
    // list actually does.
    assert.deepEqual(unsignedConfig.win.files, [...unsignedConfig.files, uiohookNegation]);
    assert.equal(unsignedConfig.files.some((pattern) => pattern.includes('prebuilds')), false);
    // JSON drops functions, so inspect the live property as well.
    const unsignedHookType = loadHookType(unsignedMode);
    assert.equal(unsignedHookType.status, 0, unsignedHookType.stderr);
    assert.equal(unsignedHookType.stdout, 'undefined');
  }

  const cliSigned = loadConfig({
    BETTERFINGERS_SIGNING_MODE: 'azure-cli',
    BETTERFINGERS_EXPECTED_SIGNER_SUBJECT: 'CN=Donaven Crenshaw',
  });
  assert.equal(cliSigned.status, 0, cliSigned.stderr);
  const cliConfig = JSON.parse(cliSigned.stdout);
  assert.equal(cliConfig.forceCodeSigning, true);
  assert.equal('azureSignOptions' in cliConfig.win, false);
  assert.deepEqual(
    cliConfig.win.signExts,
    ['.dll', '.pyd', '.node'],
    'Electron-builder includes all Windows native extensions; the custom hook preserves already-valid vendor signatures and signs only missing or invalid signatures',
  );
  assert.deepEqual(cliConfig.win.signtoolOptions, {
    signingHashAlgorithms: ['sha256'],
    publisherName,
  });
  const hookType = loadHookType('azure-cli');
  assert.equal(hookType.status, 0, hookType.stderr);
  assert.equal(hookType.stdout, 'function');

  const legacy = loadConfig({
    BETTERFINGERS_SIGNING_MODE: 'azure',
    AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: 'better-fingers',
    AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: 'CN=Donaven Crenshaw',
  });
  assert.notEqual(legacy.status, 0);
  assert.match(legacy.stderr, /Legacy Azure signing is disabled/);

  const partial = loadConfig({
    BETTERFINGERS_SIGNING_MODE: 'azure',
    AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: '',
    AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: 'CN=Donaven Crenshaw',
  });
  assert.notEqual(partial.status, 0);
  assert.match(partial.stderr, /Legacy Azure signing is disabled/);
});

test('the locked Electron version is allowed to install its platform binary', () => {
  const electronVersion = packageJson.devDependencies.electron;
  assert.equal(packageJson.allowScripts[`electron@${electronVersion}`], true);
});

// ---------------------------------------------------------------------------
// Effective electron-builder file patterns.
//
// The config *shape* is not enough: in Alpha 4 `win.files` held only a negation,
// every shape assertion passed, and electron-builder still packed all of app/
// (src/, tests/, a second 546 MB copy of resources/backend) into app.asar,
// 684 MB, because it prepends `**/*` to a platform list with no positive
// pattern. These tests run the same electron-builder code that the packaging
// step runs (app-builder-lib is pinned exactly in package.json, and these are
// its internal APIs, so a version bump may need this helper updated) and check
// which files and node_modules paths would be selected.
// ---------------------------------------------------------------------------

const requireFromApp = createRequire(path.join(appRoot, 'package.json'));

function loadEffectiveBuilderConfig() {
  const configPath = path.join(appRoot, 'electron-builder.config.cjs');
  const loaded = spawnSync(
    process.execPath,
    ['-e', `process.stdout.write(JSON.stringify(require(${JSON.stringify(configPath)})))`],
    { encoding: 'utf8', env: { ...process.env, BETTERFINGERS_SIGNING_MODE: '' } },
  );
  assert.equal(loaded.status, 0, loaded.stderr);
  return JSON.parse(loaded.stdout);
}

function effectiveFileSelection(config, platformKey) {
  const { doMergeConfigs } = requireFromApp('app-builder-lib/out/util/config/config.js');
  const { FileMatcher, getMainFileMatchers, getNodeModuleFileMatcher } = requireFromApp('app-builder-lib/out/fileMatcher.js');
  const { AppFileWalker } = requireFromApp('app-builder-lib/out/util/AppFileWalker.js');

  // The same normalization electron-builder applies when it loads a config.
  const merged = doMergeConfigs([structuredClone(config)]);
  const platformOptions = merged[platformKey] ?? {};
  const outDir = path.join(appRoot, merged.directories.output);
  const destination = path.join(outDir, 'asar-destination');
  const expand = (value) => value;
  const info = {
    config: merged,
    projectDir: appRoot,
    appDir: appRoot,
    buildResourcesDir: merged.directories.buildResources,
    isPrepackedAppAsar: false,
    debugLogger: { isEnabled: false, add() {} },
  };

  const mainMatchers = getMainFileMatchers(appRoot, destination, expand, platformOptions, { info }, outDir, false);
  // Snapshot the patterns before AppFileWalker adds its "match everything"
  // fallback to a matcher that holds only negations.
  const mainPatterns = mainMatchers.map((matcher) => [...matcher.patterns]);
  const mainOnlyIgnore = mainMatchers.map((matcher) => matcher.containsOnlyIgnore());
  const walkers = mainMatchers.map((matcher) => new AppFileWalker(matcher, info));
  const nodeModuleMatcher = getNodeModuleFileMatcher(appRoot, destination, expand, platformOptions, info);

  const fakeStat = (isDirectory) => ({ isDirectory: () => isDirectory });
  return {
    mainPatterns,
    mainOnlyIgnore,
    nodeModulePatterns: [...nodeModuleMatcher.patterns],
    // Would any main matcher copy this app-relative path into app.asar?
    copiesAppFile(relativePath, isDirectory = false) {
      const file = path.join(appRoot, ...relativePath.split('/'));
      return walkers.some((walker) => walker.matcherFilter(file, fakeStat(isDirectory)));
    },
    // Would electron-builder keep this path inside a collected node_modules
    // package? It builds one FileMatcher per package from the node-module
    // patterns and matches app-root-relative `node_modules/<pkg>/...` paths.
    keepsNodeModuleFile(packageName, relativePath) {
      const packageDir = path.join(appRoot, 'node_modules', ...packageName.split('/'));
      const matcher = new FileMatcher(packageDir, destination, expand, nodeModuleMatcher.patterns);
      const filter = matcher.createFilter();
      return filter(
        path.join(packageDir, ...relativePath.split('/')),
        { ...fakeStat(false), moduleFullFilePath: ['node_modules', packageName, relativePath].join('/') },
      );
    },
  };
}

const intendedAppFiles = ['out/main/main.js', 'out/preload/preload.js', 'out/renderer/index.html', 'package.json'];
const neverPackedIntoAsar = [
  'src/main/main.js',
  'tests/packageResourceContract.test.mjs',
  'resources/backend/betterfingers-backend/betterfingers-backend.exe',
  'resources/backend/betterfingers-backend/_internal/base_library.zip',
  'scripts/build-backend.js',
  'build/icon.ico',
  'electron-builder.config.cjs',
  'electron.vite.config.js',
  '.electron-backend-build/work/bundle.bin',
  'release/win-unpacked/resources/app.asar',
];

test('effective electron-builder file patterns for win keep the base out/ patterns and pack nothing else', () => {
  const config = loadEffectiveBuilderConfig();
  const win = effectiveFileSelection(config, 'win');

  // The first (default) matcher is the one electron-builder decorates with its
  // standard exclusions. Without a positive pattern it would be permissive.
  const [winMain] = win.mainPatterns;
  assert.equal(win.mainOnlyIgnore[0], false, 'the Windows file list must contain a positive pattern');
  assert.equal(winMain.includes('**/*'), false, 'a permissive **/* pattern would pack all of app/');
  for (const base of config.files) {
    assert.ok(winMain.includes(base), `base files pattern ${base} must survive in the effective Windows patterns`);
  }
  assert.ok(winMain.includes('out/**/*'));
  assert.ok(winMain.includes('package.json'));
  assert.ok(winMain.includes(uiohookNegation), 'the uiohook prebuild negation must be effective on Windows');
  assert.ok(win.nodeModulePatterns.includes(uiohookNegation), 'the negation must also reach collected node_modules');

  for (const relativePath of intendedAppFiles) {
    assert.equal(win.copiesAppFile(relativePath), true, `${relativePath} must be packed into app.asar`);
  }
  assert.equal(win.copiesAppFile('out', true), true);
  assert.equal(win.copiesAppFile('out/main', true), true);
  for (const relativePath of neverPackedIntoAsar) {
    assert.equal(win.copiesAppFile(relativePath), false, `${relativePath} must not be packed into app.asar`);
  }
});

test('effective electron-builder file patterns for win keep only the win32-x64 uiohook prebuild', () => {
  const win = effectiveFileSelection(loadEffectiveBuilderConfig(), 'win');
  const prebuild = (arch) => `prebuilds/${arch}/uiohook-napi.node`;

  assert.equal(win.keepsNodeModuleFile('uiohook-napi', prebuild('win32-x64')), true);
  assert.equal(win.keepsNodeModuleFile('uiohook-napi', 'package.json'), true);
  assert.equal(win.keepsNodeModuleFile('uiohook-napi', 'dist/index.js'), true);
  for (const arch of ['win32-arm64', 'linux-x64', 'linux-arm64', 'darwin-x64', 'darwin-arm64']) {
    assert.equal(win.keepsNodeModuleFile('uiohook-napi', prebuild(arch)), false, `${arch} prebuild must not ship in the Windows package`);
  }
  assert.equal(win.keepsNodeModuleFile('electron-updater', 'package.json'), true);
});

test('effective electron-builder file patterns for linux are untouched by the Windows filter', () => {
  const config = loadEffectiveBuilderConfig();
  const linux = effectiveFileSelection(config, 'linux');

  assert.equal(linux.mainOnlyIgnore[0], false);
  assert.equal(linux.mainPatterns[0].some((pattern) => pattern.includes('prebuilds')), false);
  assert.equal(linux.nodeModulePatterns.some((pattern) => pattern.includes('prebuilds')), false);
  for (const relativePath of intendedAppFiles) {
    assert.equal(linux.copiesAppFile(relativePath), true, `${relativePath} must be packed on Linux`);
  }
  for (const relativePath of neverPackedIntoAsar) {
    assert.equal(linux.copiesAppFile(relativePath), false, `${relativePath} must not be packed on Linux`);
  }
  // The AppImage needs the Linux prebuild; only the Windows package drops it.
  assert.equal(linux.keepsNodeModuleFile('uiohook-napi', 'prebuilds/linux-x64/uiohook-napi.node'), true);
});

test('the effective-pattern check flags a negation-only Windows files list (the Alpha 4 defect)', () => {
  const config = loadEffectiveBuilderConfig();
  const defective = { ...config, win: { ...config.win, files: [uiohookNegation] } };
  const win = effectiveFileSelection(defective, 'win');

  // The old shape is permissive: electron-builder prepends **/* to it, so the
  // checks in the tests above fail for it. This proves they can fail.
  assert.equal(win.mainPatterns[0].includes('out/**/*'), false);
  assert.equal(win.copiesAppFile('src/main/main.js'), true);
  assert.equal(win.copiesAppFile('resources/backend/betterfingers-backend/betterfingers-backend.exe'), true);
  assert.equal(win.copiesAppFile('tests/packageResourceContract.test.mjs'), true);
});
