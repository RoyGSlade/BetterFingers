// Round 2, item 2, end to end through ipc.js: a renderer cannot make a typed key the send
// shortcut, and cannot change it without a native dialog. Run with: node --test app/tests/ipcHotkeyGate.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));

function setup(t, { answers = [0] } = {}) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-hk-'));
  t.after(() => fs.rmSync(userData, { recursive: true, force: true }));
  const Module = require('node:module');
  const original = Module._load;
  const listeners = new Map();
  const registered = [];
  const queue = [...answers];
  const dialogs = [];
  const electron = {
    app: { getPath: () => userData, getVersion: () => '0' }, clipboard: {}, session: {}, shell: {}, webContents: {},
    dialog: { showMessageBox: async (...args) => { dialogs.push(args[args.length - 1]); return { response: queue.length ? queue.shift() : 1 }; } },
    ipcMain: { handle() {}, on: (channel, fn) => listeners.set(channel, fn) },
  };
  Module._load = function patched(request, parent, isMain) {
    if (request === 'electron') return electron;
    if (request === './hotkeys') {
      return { registerHotkeys: (config) => registered.push({ ...config }), setPrimaryActionHandler() {} };
    }
    return original.call(this, request, parent, isMain);
  };
  t.after(() => { Module._load = original; });
  const modulePath = require.resolve('../src/main/ipc.js');
  delete require.cache[modulePath];
  require(modulePath).registerIpc({ getMainWindow: () => null, getApprovalKey: () => '00'.repeat(32), getAuthToken: () => 't' });
  const dir = path.join(HERE, '..', 'src', 'renderer');
  const frame = { url: `file://${dir}/signal-desk.html` };
  const event = { senderFrame: frame, sender: { mainFrame: frame } };
  const send = (config) => listeners.get('update-hotkeys')(event, config);
  const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
  return { send, registered, dialogs, userData, settle };
}

test('a bare letter set through the settings bridge is not registered; the default stays', async (t) => {
  const ctx = setup(t);
  ctx.send({ hotkey: 'f8', manual_send_hotkey: 'a' });
  await ctx.settle();
  assert.equal(ctx.registered.length, 1);
  assert.equal(ctx.registered[0].manual_send_hotkey, 'f9');
  assert.equal(ctx.dialogs.length, 0);
});

test('Enter, Space, digits and Shift-letter are refused the same way', async (t) => {
  const ctx = setup(t);
  for (const key of ['enter', 'space', '5', 'shift+a', 'tab']) ctx.send({ hotkey: 'f8', manual_send_hotkey: key });
  await ctx.settle();
  assert.ok(ctx.registered.every((c) => c.manual_send_hotkey === 'f9'));
  assert.equal(ctx.dialogs.length, 0);
});

test('a new chord is registered as the OLD key first, and applied only after the native dialog says yes', async (t) => {
  const ctx = setup(t, { answers: [0] });
  ctx.send({ hotkey: 'f8', manual_send_hotkey: 'Ctrl+Alt+S' });
  assert.equal(ctx.registered[0].manual_send_hotkey, 'f9', 'not applied before the dialog');
  await ctx.settle();
  assert.equal(ctx.dialogs.length, 1);
  assert.equal(ctx.dialogs[0].defaultId, 1);
  assert.equal(ctx.registered.at(-1).manual_send_hotkey, 'ctrl+alt+s');
  assert.equal(JSON.parse(fs.readFileSync(path.join(ctx.userData, 'send-hotkey.json'), 'utf8')).key, 'ctrl+alt+s');
});

test('a declined change leaves the old key, and the same request is not asked again', async (t) => {
  const ctx = setup(t, { answers: [1, 0] });
  ctx.send({ hotkey: 'f8', manual_send_hotkey: 'ctrl+alt+s' });
  await ctx.settle();
  ctx.send({ hotkey: 'f8', manual_send_hotkey: 'ctrl+alt+s' });
  await ctx.settle();
  assert.equal(ctx.dialogs.length, 1);
  assert.ok(ctx.registered.every((c) => c.manual_send_hotkey === 'f9'));
});

test('the default and a disabled shortcut never open a dialog; other settings pass through untouched', async (t) => {
  const ctx = setup(t);
  ctx.send({ hotkey: 'ctrl+space', force_stop_key: 'escape', manual_send_hotkey: 'f9' });
  ctx.send({ hotkey: 'f8', manual_send_hotkey: '' });
  await ctx.settle();
  assert.equal(ctx.dialogs.length, 0);
  assert.equal(ctx.registered[0].hotkey, 'ctrl+space');
  assert.equal(ctx.registered[0].force_stop_key, 'escape');
  assert.equal(ctx.registered[1].manual_send_hotkey, '');
});
