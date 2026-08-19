import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const appRoot = path.resolve(import.meta.dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(appRoot, ...parts), 'utf8');
const ipc = read('src', 'main', 'ipc.js');
const main = read('src', 'main', 'main.js');
const preload = read('src', 'preload', 'preload.js');
const windows = read('src', 'main', 'windows.js');
const controller = read('src', 'main', 'updateController.js');

test('all updater IPC actions use the centralized trusted-sender wrapper', () => {
  for (const channel of ['updates:get-state', 'updates:check', 'updates:download', 'updates:install']) {
    assert.match(ipc, new RegExp(`handleTrusted\\('${channel.replace(':', '\\:')}'`));
    assert.doesNotMatch(ipc, new RegExp(`ipcMain\\.(?:handle|on)\\('${channel.replace(':', '\\:')}'`));
  }
  assert.match(ipc, /updates:check', \(\) => updateController\?\.check\?\.\(\)/);
  assert.match(ipc, /updates:download', \(\) => updateController\?\.download\?\.\(\)/);
  assert.match(ipc, /updates:install', \(\) => updateController\?\.install\?\.\(\)/);
});

test('preload exposes fixed no-argument actions and removes state listeners', () => {
  for (const [method, channel] of [
    ['getState', 'updates:get-state'], ['check', 'updates:check'],
    ['download', 'updates:download'], ['install', 'updates:install'],
  ]) {
    assert.match(preload, new RegExp(`${method}: \\(\\) => ipcRenderer\\.invoke\\('${channel}'\\)`));
  }
  assert.match(preload, /ipcRenderer\.on\('updates:state', handler\)/);
  assert.match(preload, /return \(\) => ipcRenderer\.removeListener\('updates:state', handler\)/);
  const updateBridge = preload.match(/updates:\s*\{([\s\S]*?)\n\s{2}\},\n\s{2}\/\/ Durable/)?.[1] || '';
  assert.ok(updateBridge, 'updates bridge block must be extractable');
  assert.doesNotMatch(updateBridge, /(?:url|channel|path|executable)\s*:/i);
});

test('main schedules one delayed packaged check and guards destroyed renderer windows', () => {
  assert.match(main, /let updateCheckScheduled = false/);
  assert.match(main, /if \(updateCheckScheduled \|\| !updateController\?\.isSupported\?\.\(\)\) return/);
  assert.match(main, /setTimeout\(\(\) => \{[\s\S]*updateController\.check\(\)[\s\S]*\}, 15000\)/);
  assert.match(main, /win\.isDestroyed\(\)[\s\S]*win\.webContents\.isDestroyed\?\.\(\)/);
  assert.match(main, /win\.webContents\.send\('updates:state', state\)/);
});

test('update install has a separate exact-once shutdown path without app.exit', () => {
  const prepareBody = main.match(/async function prepareForUpdateInstall\(\) \{([\s\S]*?)\n\}/)?.[1] || '';
  assert.match(prepareBody, /shutdownMode === 'update'/);
  assert.match(prepareBody, /await stopRuntimeServices\(\)/);
  assert.doesNotMatch(prepareBody, /app\.exit|app\.quit/);
  assert.match(main, /async function requestQuit\(\)[\s\S]*app\.exit\(0\)/);
  assert.match(controller, /installStarted = true/);
  assert.match(controller, /await options\.prepareQuit\?\.\(\)[\s\S]*updater\.quitAndInstall\?\.\(\)/);
  assert.match(controller, /installPending = true[\s\S]*await authoritativeActivity\(\)[\s\S]*state\.status !== 'ready'/);
  assert.match(main, /restoreActiveHotkeys/);
  const recoveryBody = main.match(/async function recoverFromFailedUpdateInstall\(\) \{([\s\S]*?)\n\}/)?.[1] || '';
  assert.match(recoveryBody, /await sidecar\.start\(\)/);
  assert.match(recoveryBody, /restoreActiveHotkeys\(\)/);
  assert.match(recoveryBody, /finally[\s\S]*shutdownMode = null[\s\S]*isQuitting = false/);
});

test('install authorization uses fixed authenticated backend state, not renderer status', () => {
  assert.match(ipc, /onRuntimeStatus\?\.\(status\)/);
  assert.match(main, /activityGuard: \(\) => runtimeActivityStatus/);
  assert.match(main, /authoritativeActivityGuard: getAuthoritativeRuntimeActivity/);
  const guard = main.match(/async function getAuthoritativeRuntimeActivity\(\) \{([\s\S]*?)\n\}/)?.[1] || '';
  assert.match(guard, /backendProxy\.request\(\{/);
  assert.match(guard, /method: 'GET'/);
  assert.match(guard, /path: '\/runtime\/status'/);
  assert.match(guard, /typeof body\.recording_active !== 'boolean'/);
  assert.match(guard, /typeof body\.processing_active !== 'boolean'/);
  assert.match(controller, /await options\.authoritativeActivityGuard\(\)/);
  assert.match(controller, /RUNTIME_STATUS_UNAVAILABLE/);
  assert.match(main, /updateController\?\.refreshInstallEligibility\?\.\(\)/);
});

test('the fixed manual URL is the only updater external-navigation exception', () => {
  assert.match(windows, /const MANUAL_UPDATE_URL = 'https:\/\/github\.com\/RoyGSlade\/BetterFingers\/releases'/);
  assert.match(windows, /if \(url === MANUAL_UPDATE_URL\) shell\.openExternal\(MANUAL_UPDATE_URL\)/);
  assert.match(windows, /return \{ action: 'deny' \}/);
});

test('the IPC state schema contains only serializable public fields', () => {
  for (const field of [
    'status', 'currentVersion', 'availableVersion', 'channel', 'releaseDate',
    'releaseNotes', 'percent', 'bytesTransferred', 'bytesTotal', 'errorCode',
  ]) assert.match(controller, new RegExp(`\\b${field}\\b`));
  assert.doesNotMatch(controller, /state\s*=\s*\{[^}]*?(?:token|stack|executable|url|updater)\s*:/is);
});
