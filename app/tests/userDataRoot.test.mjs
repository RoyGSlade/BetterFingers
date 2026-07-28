// userDataRoot.js is a deliberate Node mirror of app_paths.resolve_base().
// These tests exercise every branch of that precedence order with fully
// injected env/platform/homedir — never touching the real HOME or real env,
// since a mistake here could accidentally read/write real user data.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';

import userDataRoot from '../src/main/userDataRoot.js';

const { resolveUserDataRoot } = userDataRoot;

const FAKE_HOME = '/fake/home/tester';
const homedir = () => FAKE_HOME;
const alwaysEmpty = () => false;
const alwaysHasContents = () => true;

test('BETTERFINGERS_DATA_DIR override wins over everything else', () => {
  const root = resolveUserDataRoot({
    env: { BETTERFINGERS_DATA_DIR: '/explicit/override', APPDATA: 'C:\\Users\\x\\AppData\\Roaming' },
    platform: 'linux',
    homedir,
    existsWithContents: alwaysHasContents,
  });
  assert.equal(root, '/explicit/override');
});

test('override expands a leading ~', () => {
  const root = resolveUserDataRoot({
    env: { BETTERFINGERS_DATA_DIR: '~/custom-data' },
    platform: 'linux',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, path.join(FAKE_HOME, 'custom-data'));
});

test('bare ~ override expands to the home directory itself', () => {
  const root = resolveUserDataRoot({
    env: { BETTERFINGERS_DATA_DIR: '~' },
    platform: 'linux',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, FAKE_HOME);
});

test('APPDATA set (no override) resolves to APPDATA/BetterFingers, even if legacy is empty', () => {
  const root = resolveUserDataRoot({
    env: { APPDATA: 'C:\\Users\\tester\\AppData\\Roaming' },
    platform: 'win32',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, path.join('C:\\Users\\tester\\AppData\\Roaming', 'BetterFingers'));
});

test('an existing non-empty legacy ~/BetterFingers wins when no override/APPDATA', () => {
  const root = resolveUserDataRoot({
    env: {},
    platform: 'linux',
    homedir,
    existsWithContents: (dir) => dir === path.join(FAKE_HOME, 'BetterFingers'),
  });
  assert.equal(root, path.join(FAKE_HOME, 'BetterFingers'));
});

test('an empty/missing legacy dir falls through to the platform default', () => {
  const root = resolveUserDataRoot({
    env: {},
    platform: 'linux',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, path.join(FAKE_HOME, '.local', 'share', 'BetterFingers'));
});

test('platform default: win32 without APPDATA uses homedir/AppData/Roaming', () => {
  const root = resolveUserDataRoot({
    env: {},
    platform: 'win32',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, path.join(FAKE_HOME, 'AppData', 'Roaming', 'BetterFingers'));
});

test('platform default: darwin uses Library/Application Support', () => {
  const root = resolveUserDataRoot({
    env: {},
    platform: 'darwin',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, path.join(FAKE_HOME, 'Library', 'Application Support', 'BetterFingers'));
});

test('platform default: linux with XDG_DATA_HOME set uses it', () => {
  const root = resolveUserDataRoot({
    env: { XDG_DATA_HOME: '/xdg/data' },
    platform: 'linux',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, path.join('/xdg/data', 'BetterFingers'));
});

test('platform default: linux without XDG_DATA_HOME uses ~/.local/share', () => {
  const root = resolveUserDataRoot({
    env: {},
    platform: 'linux',
    homedir,
    existsWithContents: alwaysEmpty,
  });
  assert.equal(root, path.join(FAKE_HOME, '.local', 'share', 'BetterFingers'));
});

test('APPDATA still wins even when a non-empty legacy dir also exists', () => {
  const root = resolveUserDataRoot({
    env: { APPDATA: 'C:\\Users\\tester\\AppData\\Roaming' },
    platform: 'win32',
    homedir,
    existsWithContents: alwaysHasContents,
  });
  assert.equal(root, path.join('C:\\Users\\tester\\AppData\\Roaming', 'BetterFingers'));
});

test('default injected collaborators are not required — call with no args is safe to construct', () => {
  // Not asserting a specific path (that depends on the real machine); just
  // confirming the default-argument wiring doesn't throw.
  assert.doesNotThrow(() => resolveUserDataRoot());
});
