// Runtime-truth regressions for OR-03 / OR-04.
// These tests intentionally use the pure mappers: a saved preference or a
// delayed/empty response must never be promoted to a runtime success claim.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  getHotkeyRuntimeState,
  getLlmRuntimeState,
  getTranscriberRuntimeState,
} from '../src/renderer/features/runtime.js';
import { mapLlm } from '../src/renderer/features/statusBar.js';

test('LLM readiness follows the runtime probe, not residency intent', () => {
  assert.equal(getLlmRuntimeState({ llm_initialized: true, llm_ready: false }).text, 'not ready');
  assert.equal(getLlmRuntimeState({ llm_initialized: true, llm_ready: false }).tone, 'warning');
  assert.equal(mapLlm({ llm_engine: true }, { llm_initialized: true, llm_ready: false }).text, 'Not ready');
});

test('LLM initialization alone is reported as starting, never ready', () => {
  assert.equal(getLlmRuntimeState({ llm_initialized: true }).text, 'initialized');
  assert.equal(mapLlm({ llm_engine: true }, { llm_initialized: true }).text, 'Starting');
  assert.equal(mapLlm({ llm_engine: true }, { llm_initialized: false }).text, 'Not ready');
});

test('LLM startup reason is retained for the user', () => {
  const state = getLlmRuntimeState({
    llm_initialized: true,
    llm_ready: false,
    llm_runtime_message: 'llama-server binary is missing.',
  });
  assert.equal(state.detail, 'llama-server binary is missing.');
  assert.equal(mapLlm(null, {
    llm_initialized: true,
    llm_ready: false,
    llm_error: 'selected model is missing',
  }).detail, 'selected model is missing');
});

test('missing runtime data is checking, not offline', () => {
  assert.equal(getLlmRuntimeState(null).text, 'checking…');
  assert.equal(getTranscriberRuntimeState(null).text, 'checking…');
  assert.equal(getHotkeyRuntimeState(null).text, 'checking…');
});

test('an empty valid hotkey response is checking, not a failure', () => {
  const state = getHotkeyRuntimeState({});
  assert.equal(state.text, 'checking…');
  assert.equal(state.tone, 'warning');
  assert.equal(getLlmRuntimeState({}).text, 'checking…');
  assert.equal(getTranscriberRuntimeState({}).text, 'checking…');
});

test('hotkey readiness requires an affirmative manager and hook state', () => {
  const state = getHotkeyRuntimeState({
    hotkey_manager_started: true,
    hotkey_keyboard_hooks_ok: true,
    hotkey_keyboard_hook_errors: [],
  });
  assert.deepEqual(state, { text: 'ready', tone: 'success' });
});

test('hotkey failures show only a genuine manager or hook failure', () => {
  assert.equal(getHotkeyRuntimeState({ hotkey_manager_started: false }).text, 'unavailable');
  assert.equal(getHotkeyRuntimeState({
    hotkey_manager_started: true,
    hotkey_keyboard_hooks_ok: false,
    hotkey_keyboard_hook_errors: ['uiohook could not start'],
  }).detail, 'uiohook could not start');
});
