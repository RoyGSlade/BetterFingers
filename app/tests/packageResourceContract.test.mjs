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
  assert.equal(packageJson.version, '1.1.0-alpha.1');
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
  assert.equal('publisherName' in packageJson.build.win, false, 'set this only after the certificate subject is known');
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

  const signed = loadConfig({
    BETTERFINGERS_SIGNING_MODE: 'azure',
    AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: 'better-fingers-public',
    AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: 'CN=Donaven Crenshaw',
  });
  assert.equal(signed.status, 0, signed.stderr);
  assert.deepEqual(JSON.parse(signed.stdout).win.azureSignOptions, {
    endpoint: 'https://wus2.codesigning.azure.net/',
    codeSigningAccountName: 'better-fingers',
    certificateProfileName: 'better-fingers-public',
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
