// Round 2, item 2: which keys may be the send shortcut and who may change it.
// Run with: node --test app/tests/sendHotkeyPolicy.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { parseChord, normalizeHotkey, isAllowedSendHotkey, createSendHotkeyGate, DEFAULT_SEND_HOTKEY } =
  require('../src/main/sendHotkeyPolicy.js');

test('bare letters, digits, Enter, Space, Tab, punctuation and Shift-only are refused (the reproduced bypass)', () => {
  for (const key of ['a', 'Z', '7', 'enter', 'space', 'tab', 'backspace', '.', 'shift+a', 'shift+enter', 'up', 'escape', 'delete', 'home']) {
    assert.equal(isAllowedSendHotkey(key), false, key);
  }
});

test('modifier chords and bare function keys are allowed', () => {
  for (const key of ['ctrl+alt+s', 'Ctrl+Shift+Enter', 'alt+f9', 'meta+space', 'cmd+p', 'win+j', 'f9', 'F12', 'f24']) {
    assert.equal(isAllowedSendHotkey(key), true, key);
  }
});

test('malformed values are refused', () => {
  for (const key of ['', ' ', '+', 'ctrl', 'ctrl+alt', 'ctrl+a+b', 'ctrl++', null, undefined, 5, {}, 'f25', 'f0', 'ctrl+'.repeat(9) + 'a']) {
    assert.equal(isAllowedSendHotkey(key), false, String(key));
  }
});

test('normalisation makes spelling and modifier order irrelevant', () => {
  assert.equal(normalizeHotkey('Alt + CTRL+ S'), 'ctrl+alt+s');
  assert.equal(normalizeHotkey('Control+Option+s'), 'ctrl+alt+s');
  assert.equal(normalizeHotkey('F9'), 'f9');
  assert.deepEqual(parseChord('cmd+shift+p'), { modifiers: ['shift', 'meta'], key: 'p' });
});

test('the shipped default is a function key and needs no confirmation', () => {
  assert.equal(DEFAULT_SEND_HOTKEY, 'f9');
  const gate = createSendHotkeyGate();
  assert.deepEqual(gate.evaluate('F9'), { effective: 'f9', needsConfirmation: null, rejected: false });
});

test('a bare letter from the renderer is rejected and the confirmed key stays in force', () => {
  const gate = createSendHotkeyGate();
  assert.deepEqual(gate.evaluate('a'), { effective: 'f9', needsConfirmation: null, rejected: true });
});

test('a new valid chord is not applied until a native confirmation says so', () => {
  const saved = [];
  const gate = createSendHotkeyGate({ save: (key) => saved.push(key) });
  const first = gate.evaluate('Ctrl+Alt+S');
  assert.deepEqual(first, { effective: 'f9', needsConfirmation: 'ctrl+alt+s', rejected: false });
  assert.deepEqual(saved, []);
  gate.confirm('ctrl+alt+s');
  assert.deepEqual(saved, ['ctrl+alt+s']);
  assert.deepEqual(gate.evaluate('ctrl+alt+s'), { effective: 'ctrl+alt+s', needsConfirmation: null, rejected: false });
  assert.equal(gate.evaluate('alt+ctrl+S').needsConfirmation, null, 'the same chord spelled differently');
});

test('a declined chord is not asked again until the request changes', () => {
  const gate = createSendHotkeyGate();
  assert.equal(gate.evaluate('ctrl+alt+s').needsConfirmation, 'ctrl+alt+s');
  gate.decline('ctrl+alt+s');
  assert.deepEqual(gate.evaluate('ctrl+alt+s'), { effective: 'f9', needsConfirmation: null, rejected: false });
  assert.equal(gate.evaluate('ctrl+alt+d').needsConfirmation, 'ctrl+alt+d');
});

test('going back to the default never needs a dialog, and an empty value disables the shortcut', () => {
  const gate = createSendHotkeyGate({ load: () => 'ctrl+alt+s' });
  assert.equal(gate.current(), 'ctrl+alt+s');
  assert.deepEqual(gate.evaluate('f9'), { effective: 'f9', needsConfirmation: null, rejected: false });
  assert.deepEqual(gate.evaluate(''), { effective: '', needsConfirmation: null, rejected: false });
});

test('a tampered saved file cannot install a bare key as the confirmed one', () => {
  for (const stored of ['a', 'enter', '', null, 7, 'shift+x']) {
    const gate = createSendHotkeyGate({ load: () => stored });
    assert.equal(gate.current(), 'f9', String(stored));
  }
  const throwing = createSendHotkeyGate({ load: () => { throw new Error('unreadable'); } });
  assert.equal(throwing.current(), 'f9');
});
