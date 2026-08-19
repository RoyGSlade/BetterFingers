import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function loadHotkeysWithStubs({ hookStarts = true } = {}) {
  const Module = require('node:module');
  const originalLoad = Module._load;
  const registeredShortcuts = [];
  const requests = [];
  const listeners = new Map();
  const globalShortcut = {
    register(accelerator, callback) {
      registeredShortcuts.push({ accelerator, callback });
      return true;
    },
    unregisterAll() {
      registeredShortcuts.length = 0;
    },
  };
  const net = {
    request(options) {
      requests.push(options);
      const handlers = {};
      return {
        setHeader() {},
        on(name, callback) {
          handlers[name] = callback;
          return this;
        },
        end() {},
      };
    },
  };
  const uiohook = {
    uIOhook: {
      on(name, callback) {
        listeners.set(name, callback);
      },
      removeAllListeners(name) {
        listeners.delete(name);
      },
      start() {
        if (!hookStarts) throw new Error('stubbed hook failure');
      },
      stop() {},
    },
    UiohookKey: { F8: 66, R: 19 },
  };

  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === 'electron') return { globalShortcut, net };
    if (request === 'uiohook-napi') return uiohook;
    return originalLoad.call(this, request, parent, isMain);
  };

  const modulePath = require.resolve('../src/main/hotkeys.js');
  delete require.cache[modulePath];
  const hotkeys = require(modulePath);
  return {
    hotkeys,
    registeredShortcuts,
    requests,
    listeners,
    restore() {
      Module._load = originalLoad;
    },
  };
}

const CONFIG = {
  hotkey: 'f8',
  force_stop_key: '',
  manual_send_hotkey: '',
  review_tts_hotkey: '',
  selection_rewrite_hotkey: 'ctrl+alt+r',
  recording_mode: 'toggle',
};

test('selection rewrite uiohook dispatch is exact-modifier and repeat suppressed', () => {
  const ctx = loadHotkeysWithStubs();
  try {
    ctx.hotkeys.registerHotkeys(CONFIG, 'test-token');
    const keydown = ctx.listeners.get('keydown');
    const keyup = ctx.listeners.get('keyup');
    assert.equal(typeof keydown, 'function');

    keydown({ keycode: 19, ctrlKey: true, altKey: true, shiftKey: false, metaKey: false });
    keydown({ keycode: 19, ctrlKey: true, altKey: true, shiftKey: false, metaKey: false });
    keydown({ keycode: 19, ctrlKey: true, altKey: true, shiftKey: true, metaKey: false });
    assert.deepEqual(ctx.requests.map((request) => request.path), ['/runtime/rewrite-selection']);

    keyup({ keycode: 19 });
    keydown({ keycode: 19, ctrlKey: true, altKey: true, shiftKey: false, metaKey: false });
    assert.deepEqual(ctx.requests.map((request) => request.path), [
      '/runtime/rewrite-selection',
      '/runtime/rewrite-selection',
    ]);
  } finally {
    ctx.hotkeys.unregisterAllHotkeys();
    ctx.restore();
  }
});

test('selection rewrite is included in globalShortcut fallback registration', () => {
  const ctx = loadHotkeysWithStubs({ hookStarts: false });
  try {
    ctx.hotkeys.registerHotkeys(CONFIG, 'test-token');
    assert.ok(ctx.registeredShortcuts.some(({ accelerator }) => accelerator === 'CommandOrControl+Alt+R'));
  } finally {
    ctx.hotkeys.unregisterAllHotkeys();
    ctx.restore();
  }
});

test('selection rewrite defaults to Ctrl+Alt+R when an older config omits the field', () => {
  const ctx = loadHotkeysWithStubs();
  try {
    const legacyConfig = { ...CONFIG };
    delete legacyConfig.selection_rewrite_hotkey;
    ctx.hotkeys.registerHotkeys(legacyConfig, 'test-token');
    const keydown = ctx.listeners.get('keydown');
    keydown({ keycode: 19, ctrlKey: true, altKey: true, shiftKey: false, metaKey: false });
    assert.deepEqual(ctx.requests.map((request) => request.path), ['/runtime/rewrite-selection']);
  } finally {
    ctx.hotkeys.unregisterAllHotkeys();
    ctx.restore();
  }
});

test('restoreActiveHotkeys restores the retained configuration after unregistering', () => {
  const ctx = loadHotkeysWithStubs({ hookStarts: false });
  try {
    ctx.hotkeys.registerHotkeys(CONFIG, 'test-token');
    ctx.hotkeys.unregisterAllHotkeys();
    assert.equal(ctx.registeredShortcuts.length, 0);
    assert.equal(ctx.hotkeys.restoreActiveHotkeys(), true);
    assert.ok(ctx.registeredShortcuts.some(({ accelerator }) => accelerator === 'CommandOrControl+Alt+R'));
  } finally {
    ctx.hotkeys.unregisterAllHotkeys();
    ctx.restore();
  }
});

test('restoreActiveHotkeys safely no-ops when no configuration was registered', () => {
  const ctx = loadHotkeysWithStubs();
  try {
    assert.equal(ctx.hotkeys.restoreActiveHotkeys(), false);
    assert.equal(ctx.registeredShortcuts.length, 0);
  } finally {
    ctx.hotkeys.unregisterAllHotkeys();
    ctx.restore();
  }
});
