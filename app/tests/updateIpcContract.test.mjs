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
  for (const channel of ['updates:get-state', 'updates:set-automatic', 'updates:check', 'updates:download', 'updates:install']) {
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
  for (const source of [preload, preload.replace(/\r?\n/g, '\r\n')]) {
    const updateBridge = source.match(/updates:\s*\{([\s\S]*?)\r?\n\s{2}\},\r?\n\s{2}\/\/ Durable/)?.[1] || '';
    assert.ok(updateBridge, 'updates bridge block must be extractable with LF or CRLF line endings');
    assert.doesNotMatch(updateBridge, /(?:url|channel|path|executable)\s*:/i);
  }
});

test('main wires durable consent and preference to the testable scheduler', () => {
  assert.match(main, /consentGuard: .*onboardingStore.needsConsent/);
  assert.match(main, /automaticUpdatesGuard: .*onboardingStore.readState\(\).automatic_updates === true/);
  assert.match(main, /saveAutomaticUpdates: .*onboardingStore.recordAutomaticUpdates/);
  assert.match(main, /onAutomaticUpdatesChanged: .*updateCheckScheduler\?\.refresh/);
  assert.match(main, /createUpdateCheckScheduler\(\{ controller: updateController/);
  assert.match(main, /onConsentChanged: \(\) => \{[\s\S]*updateController.refreshConsent\(\)/);
  assert.match(main, /updateCheckScheduler\?\.cancel\(\)/);
  assert.match(ipc, /onboarding:accept',[\s\S]*const result = onboardingStore.recordAcceptance\(\)/);
  assert.match(ipc, /if \(result.ok\) onConsentChanged\?\.\(\)/);
  assert.match(ipc, /updates:set-automatic', \(_event, enabled\) => updateController\?\.setAutomaticUpdates\?\.\(enabled\)/);
  assert.match(preload, /setAutomatic: \(enabled\) => ipcRenderer.invoke\('updates:set-automatic', enabled\)/);
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
  assert.match(windows, /if \(url === MANUAL_UPDATE_URL && !onboardingStore.needsConsent\(onboardingStore.readState\(\)\)\)[\s\S]*shell\.openExternal\(MANUAL_UPDATE_URL\)/);
  assert.match(windows, /return \{ action: 'deny' \}/);
});

test('the IPC state schema contains only serializable public fields', () => {
  for (const field of [
    'status', 'currentVersion', 'availableVersion', 'channel', 'releaseDate',
    'releaseNotes', 'percent', 'bytesTransferred', 'bytesTotal', 'errorCode',
  ]) assert.match(controller, new RegExp(`\\b${field}\\b`));
  assert.doesNotMatch(controller, /state\s*=\s*\{[^}]*?(?:token|stack|executable|url|updater)\s*:/is);
});


test('update disclosure is visible before manual check and consent guards network entry points', () => {
  const html = read('src', 'renderer', 'signal-desk.html');
  assert.match(html, /Update checks contact GitHub releases to find a newer BetterFingers version/);
  assert.match(html, /id="sdSetUpdateAutomatic" disabled> Check for updates automatically/);
  assert.match(controller, /async function check\(\) \{\s*if \(!consentGranted\(\)\) return set\(\{ errorCode: 'CONSENT_REQUIRED' \}\)/);
  assert.match(controller, /async function download\(\) \{\s*if \(!consentGranted\(\)\) return set\(\{ errorCode: 'CONSENT_REQUIRED' \}\)/);
  assert.match(ipc, /const result = await broker\(\)\.factoryReset\([\s\S]*?onConsentChanged\?\.\(\)/);
});
