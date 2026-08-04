import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const MAIN = join(HERE, '..', 'src', 'main', 'main.js');
const source = readFileSync(MAIN, 'utf8');

test('enables GlobalShortcutsPortal before Electron is ready', () => {
  const featureIndex = source.indexOf("chromiumFeatures.add('GlobalShortcutsPortal')");
  const switchIndex = source.indexOf("app.commandLine.appendSwitch('enable-features'");
  const readyIndex = source.indexOf('app.whenReady()');

  assert.notEqual(featureIndex, -1, 'main process must add the Wayland portal feature');
  assert.notEqual(switchIndex, -1, 'main process must append the Chromium feature switch');
  assert.ok(featureIndex < readyIndex, 'the portal feature must be configured before app.whenReady()');
  assert.ok(switchIndex < readyIndex, 'the feature switch must be appended before app.whenReady()');
});

test('preserves existing Chromium feature flags while adding the portal feature', () => {
  assert.match(source, /getSwitchValue\('enable-features'\)/);
  assert.match(source, /new Set\(/);
  assert.match(source, /existingChromiumFeatures\.split\(','\)/);
  assert.match(source, /chromiumFeatures\.add\('GlobalShortcutsPortal'\)/);
});
