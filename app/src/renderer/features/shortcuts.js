// In-app keyboard shortcuts (SPEC 5d) — the hybrid map.
//
// Split by CONSEQUENCE, not by convenience:
//
//   * Irreversible actions (send, accept, decline, retry) always require a
//     modifier and stay active even while typing. This app's characteristic
//     failure is text landing somewhere the user did not intend, so the actions
//     that place or destroy text must never fire from a stray keystroke.
//   * Navigation and non-destructive actions are single-key for speed, and go
//     inert the moment focus is in a text field. The audience includes RSI
//     users; making the common moves one key is the point.
//
// These are IN-APP shortcuts: they need the window focused. They are distinct
// from the user-configurable GLOBAL hotkeys (F8 record, F9 manual send,
// Ctrl+Shift+Space read-aloud) which fire system-wide from hotkeys.js. The map
// below deliberately avoids all three, so a single press can never be handled
// twice.
//
// Chromium/Electron reserved combinations (Ctrl+A/C/V/X/Z/Y editing,
// Ctrl+R/W/Q/F/P, Ctrl+Shift+I) are avoided too — the editing ones especially,
// because Talk gets a real <textarea> and Ctrl+C must keep meaning "copy the
// selection".

/** Actions a surface can implement. A surface binds only what it supports. */
export const ACTIONS = {
  SEND: 'send',
  ACCEPT: 'accept',
  DECLINE: 'decline',
  RETRY: 'retry',
  COPY: 'copy',
  LISTEN: 'listen',
  REVISE: 'revise',
  TOGGLE_CONTEXT: 'toggleContext',
  FOCUS_SEARCH: 'focusSearch',
  SHOW_HELP: 'showHelp',
  CANCEL: 'cancel',
  GO_TALK: 'goTalk',
  GO_LIBRARY: 'goLibrary',
  GO_STUDIO: 'goStudio',
  GO_UTILITIES: 'goUtilities',
  GO_SETTINGS: 'goSettings',
};

/**
 * The map, as data — one source of truth for both the key handler and the
 * shortcut sheet, so a documented binding can never drift from a real one.
 *
 * `whileTyping: true` means the binding still fires inside a text field. Only
 * modifier-guarded entries may set it.
 */
export const KEYMAP = [
  // --- irreversible: modifier-guarded, active everywhere ---
  { action: ACTIONS.SEND, key: 'Enter', ctrl: true, whileTyping: true, label: 'Send / insert', group: 'Draft' },
  { action: ACTIONS.ACCEPT, key: 'Enter', ctrl: true, shift: true, whileTyping: true, label: 'Accept without sending', group: 'Draft' },
  { action: ACTIONS.DECLINE, key: 'D', ctrl: true, shift: true, whileTyping: true, label: 'Decline draft', group: 'Draft' },
  { action: ACTIONS.RETRY, key: 'R', ctrl: true, shift: true, whileTyping: true, label: 'Retry cleanup', group: 'Draft' },

  // --- non-destructive: single key, inert while typing ---
  { action: ACTIONS.COPY, key: 'c', label: 'Copy cleaned output', group: 'Draft' },
  { action: ACTIONS.LISTEN, key: 'l', label: 'Listen', group: 'Draft' },
  { action: ACTIONS.REVISE, key: 'e', label: 'Revise', group: 'Draft' },
  { action: ACTIONS.TOGGLE_CONTEXT, key: 'b', label: 'Toggle context panel', group: 'View' },
  { action: ACTIONS.FOCUS_SEARCH, key: '/', label: 'Focus search', group: 'View' },
  { action: ACTIONS.SHOW_HELP, key: '?', label: 'Keyboard shortcuts', group: 'View' },

  { action: ACTIONS.GO_TALK, key: '1', label: 'Talk', group: 'Go to' },
  { action: ACTIONS.GO_LIBRARY, key: '2', label: 'Library', group: 'Go to' },
  { action: ACTIONS.GO_STUDIO, key: '3', label: 'Studio', group: 'Go to' },
  { action: ACTIONS.GO_UTILITIES, key: '4', label: 'Utilities', group: 'Go to' },
  { action: ACTIONS.GO_SETTINGS, key: '5', label: 'Settings', group: 'Go to' },

  // Escape is its own case: always available, never modifier-guarded, and the
  // surface decides what "narrowest thing" it closes.
  { action: ACTIONS.CANCEL, key: 'Escape', whileTyping: true, label: 'Close / cancel', group: 'View' },
];

// --- pure helpers -------------------------------------------------------------

const TEXT_INPUT_TYPES = new Set([
  'text', 'search', 'url', 'tel', 'email', 'password', 'number', 'date',
  'datetime-local', 'month', 'time', 'week',
]);

/**
 * True when the element edits text, so single-key shortcuts must stand down.
 *
 * Checkboxes, radios and buttons are `<input>` too but are NOT typing targets —
 * treating them as such would silently kill single-key shortcuts across whole
 * panels of toggles.
 */
export function isTypingTarget(el) {
  if (!el) return false;
  if (el.isContentEditable) return true;

  const tag = String(el.tagName || '').toLowerCase();
  if (tag === 'textarea' || tag === 'select') return true;
  if (tag === 'input') {
    const type = String(el.type || 'text').toLowerCase();
    return TEXT_INPUT_TYPES.has(type);
  }
  return false;
}

function eventKeyMatches(binding, event) {
  const bindingKey = binding.key;
  const eventKey = event.key;
  if (bindingKey === eventKey) return true;
  // Letter bindings are written in the case they are typed in: 'D' for
  // Ctrl+Shift+D (the browser reports the shifted character), 'c' for a bare c.
  // Compare case-insensitively so Caps Lock does not disable a shortcut.
  if (typeof bindingKey === 'string' && typeof eventKey === 'string' && bindingKey.length === 1) {
    return bindingKey.toLowerCase() === eventKey.toLowerCase();
  }
  return false;
}

/**
 * Resolve a keydown to an action id, or null.
 *
 * Modifier matching is EXACT: Ctrl+Enter and Ctrl+Shift+Enter are different
 * actions (send vs accept-without-sending), so a loose match would make one
 * shadow the other — and the shadowed pair here is "send it" vs "don't".
 */
export function matchShortcut(event, { typing = false } = {}) {
  if (!event) return null;
  const ctrl = Boolean(event.ctrlKey || event.metaKey);
  const shift = Boolean(event.shiftKey);
  const alt = Boolean(event.altKey);

  // Alt is not used by any binding; treating it as a wildcard would make
  // Alt+1 silently navigate while the user is reaching for a window-manager
  // shortcut.
  if (alt) return null;

  for (const binding of KEYMAP) {
    if (!eventKeyMatches(binding, event)) continue;
    if (Boolean(binding.ctrl) !== ctrl) continue;
    // Shift is only a distinguishing modifier for chorded bindings. For a bare
    // printable key the character ALREADY encodes it -- "?" is Shift+/ on most
    // layouts, so demanding shift===false here made the shortcut sheet
    // unreachable. Requiring an exact shift match still matters for chords,
    // where Ctrl+Enter (send) and Ctrl+Shift+Enter (accept, don't send) are
    // deliberately different actions.
    if (binding.ctrl && Boolean(binding.shift) !== shift) continue;
    if (typing && !binding.whileTyping) continue;
    return binding.action;
  }
  return null;
}

/** Human-readable accelerator, e.g. "Ctrl+Shift+D" — used by the shortcut sheet. */
export function formatBinding(binding) {
  const parts = [];
  if (binding.ctrl) parts.push('Ctrl');
  if (binding.shift) parts.push('Shift');
  const key = binding.key === ' ' ? 'Space' : binding.key;
  parts.push(key.length === 1 ? key.toUpperCase() : key);
  return parts.join('+');
}

/** Bindings a given surface actually implements, grouped for display. */
export function describeShortcuts(supportedActions) {
  const supported = supportedActions ? new Set(supportedActions) : null;
  const groups = new Map();
  for (const binding of KEYMAP) {
    if (supported && !supported.has(binding.action)) continue;
    if (!groups.has(binding.group)) groups.set(binding.group, []);
    groups.get(binding.group).push({ ...binding, accelerator: formatBinding(binding) });
  }
  return [...groups.entries()].map(([group, items]) => ({ group, items }));
}

// --- DOM wiring ---------------------------------------------------------------

/**
 * @param {object} opts
 * @param {object} opts.handlers  action id -> function. Only the actions a
 *   surface implements need be present; anything else is simply not bound, so
 *   the same map serves the main window and the Review Deck overlay.
 * @param {Document} [opts.doc]
 */
export function createShortcutsFeature({ handlers = {}, doc = globalThis.document } = {}) {
  let bound = null;

  function handleKeydown(event) {
    const typing = isTypingTarget(event?.target ?? doc?.activeElement ?? null);
    const action = matchShortcut(event, { typing });
    if (!action) return;

    const handler = handlers[action];
    if (typeof handler !== 'function') return; // surface doesn't implement it

    // Only claim the key once we know we will act on it, so unimplemented
    // actions fall through to the browser instead of being silently eaten.
    event.preventDefault?.();
    handler(event);
  }

  function init() {
    if (bound) return;
    bound = handleKeydown;
    doc?.addEventListener?.('keydown', bound);
  }

  function destroy() {
    if (!bound) return;
    doc?.removeEventListener?.('keydown', bound);
    bound = null;
  }

  return { init, destroy, handleKeydown, supportedActions: () => Object.keys(handlers) };
}
