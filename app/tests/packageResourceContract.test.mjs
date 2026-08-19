import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

import { dataSources } from '../scripts/build-backend.js';

const appRoot = path.resolve(import.meta.dirname, '..');
const packageJson = JSON.parse(fs.readFileSync(path.join(appRoot, 'package.json'), 'utf8'));

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

test('Linux package identity aligns Electron and desktop-entry names', () => {
  assert.equal(packageJson.version, '1.1.0-alpha.3');
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
  const loaded = loadForVersion('1.1.0-alpha.3');
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
  const loadConfig = (env = {}) => spawnSync(
    process.execPath,
    ['-e', `process.stdout.write(JSON.stringify(require(${JSON.stringify(configPath)})))`],
    { encoding: 'utf8', env: { ...process.env, ...env } },
  );

  const unsigned = loadConfig({
    BETTERFINGERS_SIGNING_MODE: '',
    AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: '',
    AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: '',
  });
  assert.equal(unsigned.status, 0, unsigned.stderr);
  assert.equal('azureSignOptions' in JSON.parse(unsigned.stdout).win, false);
  assert.equal('signtoolOptions' in JSON.parse(unsigned.stdout).win, false);
  assert.equal(JSON.parse(unsigned.stdout).forceCodeSigning, undefined);

  const cliSigned = loadConfig({
    BETTERFINGERS_SIGNING_MODE: 'azure-cli',
    BETTERFINGERS_EXPECTED_SIGNER_SUBJECT: 'CN=Donaven Crenshaw',
  });
  assert.equal(cliSigned.status, 0, cliSigned.stderr);
  const cliConfig = JSON.parse(cliSigned.stdout);
  assert.equal(cliConfig.forceCodeSigning, true);
  assert.deepEqual(
    cliConfig.win.signExts,
    ['!.dll'],
    'preserve vendor DLL signatures while default EXE/installer signing remains enabled',
  );
  assert.deepEqual(cliConfig.win.signtoolOptions, {
    signingHashAlgorithms: ['sha256'],
    publisherName: 'CN=Donaven Crenshaw',
  });
  const hookType = spawnSync(
    process.execPath,
    ['-e', `process.stdout.write(typeof require(${JSON.stringify(configPath)}).win.signtoolOptions.sign)`],
    {
      encoding: 'utf8',
      env: { ...process.env, BETTERFINGERS_SIGNING_MODE: 'azure-cli' },
    },
  );
  assert.equal(hookType.status, 0, hookType.stderr);
  assert.equal(hookType.stdout, 'function');

  const signed = loadConfig({
    BETTERFINGERS_SIGNING_MODE: 'azure',
    AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: 'better-fingers',
    AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: 'CN=Donaven Crenshaw',
  });
  assert.equal(signed.status, 0, signed.stderr);
  assert.deepEqual(JSON.parse(signed.stdout).win.azureSignOptions, {
    endpoint: 'https://wus2.codesigning.azure.net/',
    codeSigningAccountName: 'better-fingers',
    certificateProfileName: 'better-fingers',
    publisherName: 'CN=Donaven Crenshaw',
    fileDigest: 'SHA256',
    timestampDigest: 'SHA256',
    timestampRfc3161: 'http://timestamp.acs.microsoft.com',
  });

  const partial = loadConfig({
    BETTERFINGERS_SIGNING_MODE: 'azure',
    AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: '',
    AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: 'CN=Donaven Crenshaw',
  });
  assert.notEqual(partial.status, 0);
  assert.match(partial.stderr, /requires AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE/);
});

test('the locked Electron version is allowed to install its platform binary', () => {
  const electronVersion = packageJson.devDependencies.electron;
  assert.equal(packageJson.allowScripts[`electron@${electronVersion}`], true);
});
