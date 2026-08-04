import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

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
  assert.equal(packageJson.version, '0.2.0-alpha.1');
  assert.equal(packageJson.author, 'Donaven Crenshaw');
  assert.equal(packageJson.desktopName, 'BetterFingers');
  assert.equal(packageJson.build.appId, 'com.betterfingers.desktop');
  assert.equal(packageJson.build.productName, 'BetterFingers');
  assert.deepEqual(packageJson.build.linux.executableArgs, []);
  assert.equal(packageJson.build.linux.syncDesktopName, true);
});
