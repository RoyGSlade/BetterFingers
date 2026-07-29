// One build version source, from the renderer/Electron side (D-0008, Wave 11).
//
// The Python half of this contract lives in tests/test_version_source.py. This
// half guards the things only the JS side can see: that package.json (which
// electron-builder turns into artifact filenames, and which app.getVersion()
// reports to the renderer) equals the repo-root VERSION file, and that no
// renderer page prints a version literal instead of asking the bridge.
//
// Run with:  cd app && node --test tests/versionSource.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_DIR = join(HERE, '..');
const REPO_ROOT = join(APP_DIR, '..');
const RENDERER = join(APP_DIR, 'src/renderer');

const versionFile = readFileSync(join(REPO_ROOT, 'VERSION'), 'utf8').trim();
const pkg = JSON.parse(readFileSync(join(APP_DIR, 'package.json'), 'utf8'));

test('VERSION holds the Wave 11 release target', () => {
  assert.equal(versionFile, '0.2.0-alpha.1');
});

test('package.json version equals the VERSION file', () => {
  // package.json cannot import VERSION (npm needs a literal), so it is a COPY.
  // This test is what makes the copy non-authoritative: electron-builder names
  // every release artifact from this field, so drift here ships an installer
  // labelled with a version no other part of the app reports.
  assert.equal(
    pkg.version,
    versionFile,
    `app/package.json version ${pkg.version} != VERSION ${versionFile}`,
  );
});

test('the app version reaches the renderer through the IPC bridge, not a literal', () => {
  const preload = readFileSync(join(APP_DIR, 'src/preload/preload.js'), 'utf8');
  const ipc = readFileSync(join(APP_DIR, 'src/main/ipc.js'), 'utf8');
  const config = readFileSync(join(APP_DIR, 'src/main/config.js'), 'utf8');
  const bootstrap = readFileSync(join(RENDERER, 'bootstrap/signalDeskApp.js'), 'utf8');

  assert.match(preload, /getAppVersion:\s*\(\)\s*=>\s*ipcRenderer\.invoke\('app:get-version'\)/);
  assert.match(ipc, /handleTrusted\('app:get-version'/);
  assert.match(config, /APP_VERSION\s*=\s*app\.getVersion\(\)/);
  assert.match(bootstrap, /getAppVersion\?\.\(\)/);
});

test('no renderer page hardcodes a version number', () => {
  const offenders = [];
  for (const entry of readdirSync(RENDERER)) {
    if (!entry.endsWith('.html')) continue;
    const text = readFileSync(join(RENDERER, entry), 'utf8');
    for (const match of text.matchAll(/\bv\d+\.\d+\.\d+[\w.-]*/g)) {
      offenders.push(`${entry}: ${match[0]}`);
    }
  }
  assert.deepEqual(offenders, [], `renderer pages must not invent a version: ${offenders}`);
});

test('the frozen sidecar carries VERSION so version.py can read it', () => {
  // version.py raises rather than guessing when VERSION is absent, so a build
  // that forgets this --add-data entry produces a backend that will not start.
  const buildBackend = readFileSync(join(APP_DIR, 'scripts/build-backend.js'), 'utf8');
  assert.match(buildBackend, /\['VERSION',\s*'\.'\]/);
});
