import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  createSettingsConsumerSyncHooks,
} from '../src/renderer/bootstrap/signalDeskApp.js';

test('settings save and profile mutation share the complete consumer refresh', async () => {
  for (const hookName of ['onProfileChanged', 'onProfileSaved']) {
    const calls = [];
    let releaseProfile;
    const profileReady = new Promise((resolve) => { releaseProfile = resolve; });
    const hooks = createSettingsConsumerSyncHooks({
      refreshProfileSettings: async () => {
        calls.push('profile:start');
        await profileReady;
        calls.push('profile:done');
      },
      refreshOutputSettings: async () => { calls.push('output'); },
      refreshModels: async () => { calls.push('models'); },
      refreshStudio: async () => { calls.push('studio'); },
    });

    const pending = hooks[hookName]();
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(calls, ['profile:start', 'output']);

    releaseProfile();
    await pending;
    assert.deepEqual(calls, [
      'profile:start',
      'output',
      'profile:done',
      'models',
      'studio',
    ]);
  }
});

test('one failed profile consumer cannot suppress the remaining refreshes', async () => {
  const calls = [];
  const hooks = createSettingsConsumerSyncHooks({
    refreshProfileSettings: () => { calls.push('profile'); throw new Error('offline'); },
    refreshOutputSettings: () => { calls.push('output'); },
    refreshModels: () => { calls.push('models'); throw new Error('models offline'); },
    refreshStudio: () => { calls.push('studio'); },
  });

  await assert.doesNotReject(() => hooks.onProfileSaved());
  assert.deepEqual(calls, ['profile', 'output', 'models', 'studio']);
});

test('production Settings composition installs both synchronization hooks', () => {
  const source = readFileSync(
    new URL('../src/renderer/bootstrap/signalDeskApp.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /createSettingsConsumerSyncHooks\(\{[\s\S]*refreshProfileSettings,[\s\S]*refreshOutputSettings,[\s\S]*utilitiesWorkspace\.refreshModels\(\)[\s\S]*studioWorkspace\.refresh\(\)/);
  assert.match(source, /createSettingsWorkspaceFeature\(\{[\s\S]*hooks:\s*\{[\s\S]*\.\.\.settingsConsumerSyncHooks/);
});
