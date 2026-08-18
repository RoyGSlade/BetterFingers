import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const launcher = require('../scripts/dev.js');

test('Windows launches electron-vite JS entrypoint through Node without a shell', () => {
  const command = launcher.resolveElectronViteCommand({
    platform: 'win32',
    root: launcher.appRoot,
    execPath: 'C:\\Program Files\\nodejs\\node.exe',
  });

  assert.equal(command.command, 'C:\\Program Files\\nodejs\\node.exe');
  assert.equal(command.args[0], launcher.resolveElectronViteEntrypoint());
  assert.equal(path.basename(command.args[0]), 'electron-vite.js');
  assert.deepEqual(command.args.slice(1), ['dev']);
  assert.equal(command.command.endsWith('.cmd'), false);
});

test('Linux preserves the electron-vite shim and dev argv contract', () => {
  const command = launcher.resolveElectronViteCommand({ platform: 'linux', root: launcher.appRoot });

  assert.equal(command.command, path.join(launcher.appRoot, 'node_modules', '.bin', 'electron-vite'));
  assert.deepEqual(command.args, ['dev']);
});

test('environment preserves values, removes Electron run-as-node, and drops missing Python paths', () => {
  const env = launcher.buildEnvironment({
    KEEP_ME: 'preserved',
    ELECTRON_RUN_AS_NODE: '1',
    BETTERFINGERS_PYTHON: 'missing/python',
  }, launcher.appRoot);

  assert.equal(env.KEEP_ME, 'preserved');
  assert.equal(env.ELECTRON_RUN_AS_NODE, undefined);
  assert.equal(env.BETTERFINGERS_PYTHON, undefined);
});

test('environment preserves an existing Python path', () => {
  const env = launcher.buildEnvironment({ BETTERFINGERS_PYTHON: process.execPath }, launcher.appRoot);

  assert.equal(env.BETTERFINGERS_PYTHON, process.execPath);
  assert.equal(fs.existsSync(env.BETTERFINGERS_PYTHON), true);
});
