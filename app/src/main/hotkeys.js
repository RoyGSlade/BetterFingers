const { globalShortcut } = require('electron');
const { net } = require('electron');
const { BACKEND_HOST, BACKEND_PORT } = require('./config');

// Endpoints the hotkeys drive on the backend.
const EP_TOGGLE = '/runtime/recording/toggle';
const EP_START = '/runtime/recording/start';
const EP_STOP = '/runtime/recording/stop';
const EP_FORCE_STOP = '/runtime/emergency-stop';
const EP_PRIMARY = '/runtime/primary-action';
const EP_TTS = '/runtime/tts/toggle';

const TOGGLE_DEBOUNCE_MS = 200;

let authToken = null;
let activeConfig = null;

// uiohook gives us global key-DOWN and key-UP events, which Electron's
// globalShortcut cannot — key-up is what makes push-to-talk possible. It is a
// native (N-API) module; if it can't load or start (e.g. Wayland, missing
// libXtst), we degrade to globalShortcut, which supports toggle mode only.
let uiohook = null; // the loaded module, or null
let uiohookAvailable = false; // module require succeeded
let hookRunning = false; // uIOhook.start() succeeded and listeners attached
let usingFallback = false; // running on globalShortcut instead

// Parsed matchers for the current config.
let matchers = { master: null, forceStop: null, primaryAction: null, tts: null };
let recordingMode = 'toggle';

// Transient key state for the uiohook path.
const downKeycodes = new Set(); // suppress OS auto-repeat
let pttActive = false;
let pttKeycode = null;
let lastToggleAt = 0;

function loadUiohook() {
  if (uiohook !== null || uiohookAvailable) {
    return uiohook;
  }
  try {
    uiohook = require('uiohook-napi');
    uiohookAvailable = Boolean(uiohook && uiohook.uIOhook && uiohook.UiohookKey);
    if (!uiohookAvailable) {
      uiohook = null;
    }
  } catch (error) {
    console.warn('uiohook-napi unavailable; push-to-talk disabled, using globalShortcut fallback:', error.message);
    uiohook = null;
    uiohookAvailable = false;
  }
  return uiohook;
}

function triggerBackendAction(endpoint) {
  if (!authToken) {
    console.error(`Cannot trigger ${endpoint}: authToken is not set.`);
    return;
  }

  const request = net.request({
    method: 'POST',
    protocol: 'http:',
    hostname: BACKEND_HOST,
    port: BACKEND_PORT,
    path: endpoint,
  });

  request.setHeader('Authorization', `Bearer ${authToken}`);

  request.on('response', (response) => {
    if (response.statusCode !== 200) {
      console.warn(`Hotkey triggered ${endpoint} but backend returned ${response.statusCode}`);
    }
    response.on('data', () => {});
  });

  request.on('error', (error) => {
    console.error(`Hotkey trigger failed for ${endpoint}:`, error);
  });

  request.end();
}

// --- Hotkey string parsing (shared between uiohook and globalShortcut paths) ---

const KEY_ALIASES = {
  esc: 'Escape',
  escape: 'Escape',
  enter: 'Enter',
  return: 'Enter',
  space: 'Space',
  spacebar: 'Space',
  tab: 'Tab',
  backspace: 'Backspace',
  delete: 'Delete',
  del: 'Delete',
  insert: 'Insert',
  home: 'Home',
  end: 'End',
  pageup: 'PageUp',
  pagedown: 'PageDown',
  up: 'ArrowUp',
  down: 'ArrowDown',
  left: 'ArrowLeft',
  right: 'ArrowRight',
};

function normalizeMainKeyName(token) {
  const t = token.trim();
  if (!t) return null;
  const lower = t.toLowerCase();
  if (KEY_ALIASES[lower]) {
    return KEY_ALIASES[lower];
  }
  // Function keys: f1..f24
  if (/^f\d{1,2}$/.test(lower)) {
    return lower.toUpperCase();
  }
  // Single letter or digit.
  if (/^[a-z0-9]$/.test(lower)) {
    return lower.toUpperCase();
  }
  // Fall back to Capitalized form (matches UiohookKey naming for many keys).
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

// Parse "ctrl+shift+space" / "F8" into a uiohook matcher.
function parseHotkeyToMatcher(hotkey) {
  if (!hotkey || typeof hotkey !== 'string') return null;
  const lib = loadUiohook();
  if (!lib) return null;

  const parts = hotkey.split('+').map((p) => p.trim().toLowerCase()).filter(Boolean);
  if (!parts.length) return null;

  const matcher = { keycode: null, ctrl: false, shift: false, alt: false, meta: false };
  let mainName = null;

  for (const part of parts) {
    if (part === 'ctrl' || part === 'control') matcher.ctrl = true;
    else if (part === 'shift') matcher.shift = true;
    else if (part === 'alt' || part === 'option') matcher.alt = true;
    else if (['super', 'cmd', 'command', 'win', 'windows', 'meta'].includes(part)) matcher.meta = true;
    else mainName = part;
  }

  if (!mainName) return null;
  const keyName = normalizeMainKeyName(mainName);
  const keycode = keyName != null ? lib.UiohookKey[keyName] : undefined;
  if (typeof keycode !== 'number') {
    console.warn(`Hotkey "${hotkey}": unknown key "${mainName}" — skipping.`);
    return null;
  }
  matcher.keycode = keycode;
  return matcher;
}

// keydown requires exact modifier match so a bare "F8" doesn't fire while a
// modifier is held, and a combo only fires when all its modifiers are present.
function matchesDown(matcher, event) {
  if (!matcher) return false;
  return (
    event.keycode === matcher.keycode &&
    Boolean(event.ctrlKey) === matcher.ctrl &&
    Boolean(event.shiftKey) === matcher.shift &&
    Boolean(event.altKey) === matcher.alt &&
    Boolean(event.metaKey) === matcher.meta
  );
}

// --- uiohook event handling ---

function onKeydown(event) {
  // Suppress OS auto-repeat: only act on the up->down transition.
  const alreadyDown = downKeycodes.has(event.keycode);

  if (matchers.master && matchesDown(matchers.master, event)) {
    if (!alreadyDown) {
      downKeycodes.add(event.keycode);
      if (recordingMode === 'push_to_talk') {
        if (!pttActive) {
          pttActive = true;
          pttKeycode = event.keycode;
          triggerBackendAction(EP_START);
        }
      } else {
        const now = Date.now();
        if (now - lastToggleAt >= TOGGLE_DEBOUNCE_MS) {
          lastToggleAt = now;
          triggerBackendAction(EP_TOGGLE);
        }
      }
    }
    return;
  }

  // Non-master hotkeys: fire once per press.
  if (alreadyDown) return;
  if (matchers.forceStop && matchesDown(matchers.forceStop, event)) {
    downKeycodes.add(event.keycode);
    triggerBackendAction(EP_FORCE_STOP);
  } else if (matchers.primaryAction && matchesDown(matchers.primaryAction, event)) {
    downKeycodes.add(event.keycode);
    triggerBackendAction(EP_PRIMARY);
  } else if (matchers.tts && matchesDown(matchers.tts, event)) {
    downKeycodes.add(event.keycode);
    triggerBackendAction(EP_TTS);
  }
}

function onKeyup(event) {
  downKeycodes.delete(event.keycode);
  // Stop push-to-talk when the key that started it is released, regardless of
  // modifier order (releasing Ctrl before Space must not strand the recording).
  if (pttActive && event.keycode === pttKeycode) {
    pttActive = false;
    pttKeycode = null;
    triggerBackendAction(EP_STOP);
  }
}

function ensureHookRunning() {
  const lib = loadUiohook();
  if (!lib) return false;
  if (hookRunning) return true;
  try {
    lib.uIOhook.on('keydown', onKeydown);
    lib.uIOhook.on('keyup', onKeyup);
    lib.uIOhook.start();
    hookRunning = true;
    usingFallback = false;
    return true;
  } catch (error) {
    console.warn('Failed to start uiohook global key hook; falling back to globalShortcut:', error.message);
    try {
      lib.uIOhook.removeAllListeners('keydown');
      lib.uIOhook.removeAllListeners('keyup');
    } catch (e) {
      // ignore
    }
    hookRunning = false;
    return false;
  }
}

// --- globalShortcut fallback (toggle mode only) ---

function normalizeToElectronAccelerator(hotkey) {
  if (!hotkey) return null;
  return hotkey
    .split('+')
    .map((part) => {
      const p = part.trim().toLowerCase();
      if (p === 'ctrl' || p === 'control') return 'CommandOrControl';
      if (p === 'shift') return 'Shift';
      if (p === 'alt') return 'Alt';
      if (['super', 'cmd', 'command', 'win', 'windows', 'meta'].includes(p)) return 'Super';
      if (p.length > 1) return p.charAt(0).toUpperCase() + p.slice(1);
      return p.toUpperCase();
    })
    .join('+');
}

function registerGlobalShortcutFallback(config) {
  globalShortcut.unregisterAll();
  usingFallback = true;
  const mapping = [
    { key: config.hotkey, endpoint: EP_TOGGLE },
    { key: config.force_stop_key, endpoint: EP_FORCE_STOP },
    { key: config.manual_send_hotkey, endpoint: EP_PRIMARY },
    { key: config.review_tts_hotkey, endpoint: EP_TTS },
  ];
  for (const { key, endpoint } of mapping) {
    const accelerator = normalizeToElectronAccelerator(key);
    if (!accelerator) continue;
    try {
      const ok = globalShortcut.register(accelerator, () => triggerBackendAction(endpoint));
      if (!ok) {
        console.warn(`Failed to register global shortcut: ${accelerator}`);
      }
    } catch (err) {
      console.error(`Error registering accelerator ${accelerator}:`, err);
    }
  }
}

// --- Public API ---

function registerHotkeys(config, token) {
  if (token) {
    authToken = token;
  }
  if (!config) return;
  activeConfig = config;
  recordingMode = config.recording_mode === 'push_to_talk' ? 'push_to_talk' : 'toggle';

  if (ensureHookRunning()) {
    // uiohook path: matchers are consulted live by the event handlers.
    matchers = {
      master: parseHotkeyToMatcher(config.hotkey),
      forceStop: parseHotkeyToMatcher(config.force_stop_key),
      primaryAction: parseHotkeyToMatcher(config.manual_send_hotkey),
      tts: parseHotkeyToMatcher(config.review_tts_hotkey),
    };
    // In case we previously registered globalShortcut, clear it.
    globalShortcut.unregisterAll();
    // Reset transient state on reconfigure.
    downKeycodes.clear();
    pttActive = false;
    pttKeycode = null;
  } else {
    registerGlobalShortcutFallback(config);
  }
}

function unregisterAllHotkeys() {
  globalShortcut.unregisterAll();
  if (hookRunning && uiohook && uiohook.uIOhook) {
    try {
      uiohook.uIOhook.removeAllListeners('keydown');
      uiohook.uIOhook.removeAllListeners('keyup');
      uiohook.uIOhook.stop();
    } catch (error) {
      // ignore shutdown errors
    }
    hookRunning = false;
  }
  downKeycodes.clear();
  pttActive = false;
  pttKeycode = null;
}

// Report what the hotkey subsystem can actually do, so the UI can tell the user
// whether push-to-talk is available on this platform/session.
function getHotkeyCapabilities() {
  const available = Boolean(loadUiohook());
  return {
    backend: hookRunning ? 'uiohook' : usingFallback ? 'globalShortcut' : available ? 'uiohook' : 'globalShortcut',
    pttSupported: hookRunning || (available && !usingFallback),
    recordingMode,
  };
}

module.exports = {
  registerHotkeys,
  unregisterAllHotkeys,
  getHotkeyCapabilities,
};
