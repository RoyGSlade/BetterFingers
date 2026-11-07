'use strict';

// Which keys may be the "send" shortcut, and who may change it (round 2, item 2).
//
// The send hotkey used to SIGN an approval on its own: a press placed the displayed
// draft with no dialog. A compromised renderer could set manual_send_hotkey to a bare
// letter ("a") through the settings bridge and then wait for the person to type, and
// the next matching keystroke would place attacker-edited text. Two things close that:
//   1. the hotkey no longer signs anything. A press opens the native approval dialog
//      for the text MAIN fetched from the backend (approvalBroker.placeFromHotkey);
//   2. only shortcuts a person does not type by accident can be the send key, and
//      changing it to anything but the shipped default needs a native confirmation.
//
// Pure: no Electron, no filesystem (load/save are injected), so it is unit-tested.

const DEFAULT_SEND_HOTKEY = 'f9';

const MODIFIER_ORDER = ['ctrl', 'alt', 'shift', 'meta'];
const MODIFIER_ALIASES = {
  ctrl: 'ctrl', control: 'ctrl', alt: 'alt', option: 'alt', shift: 'shift',
  super: 'meta', cmd: 'meta', command: 'meta', win: 'meta', windows: 'meta', meta: 'meta',
};
const FUNCTION_KEY = /^f([1-9]|1[0-9]|2[0-4])$/;

// "Ctrl + Alt+S" -> { modifiers: ['ctrl','alt'], key: 's' }, or null when it has no main key
// or repeats a key.
function parseChord(value) {
  if (typeof value !== 'string') return null;
  const parts = value.split('+').map((part) => part.trim().toLowerCase()).filter(Boolean);
  if (!parts.length || parts.length > 5) return null;
  const modifiers = new Set();
  let key = null;
  for (const part of parts) {
    if (MODIFIER_ALIASES[part]) {
      modifiers.add(MODIFIER_ALIASES[part]);
    } else {
      if (key !== null) return null; // two main keys
      key = part;
    }
  }
  if (key === null) return null;
  return { modifiers: MODIFIER_ORDER.filter((m) => modifiers.has(m)), key };
}

function normalizeHotkey(value) {
  const chord = parseChord(value);
  return chord ? [...chord.modifiers, chord.key].join('+') : '';
}

// A send shortcut must be something typing does not produce: a chord with Ctrl, Alt or
// Meta held (Shift alone is just a capital letter), or a function key on its own. Bare
// letters, digits, Enter, Space, Tab and the like are refused. (F1-F24 on their own stay
// valid because they are the shipped default and nobody types them into a draft.)
function isAllowedSendHotkey(value) {
  const chord = parseChord(value);
  if (!chord) return false;
  if (chord.modifiers.some((m) => m === 'ctrl' || m === 'alt' || m === 'meta')) return true;
  return FUNCTION_KEY.test(chord.key) && chord.modifiers.length === 0;
}

function createSendHotkeyGate({ load = () => null, save = () => {}, defaultKey = DEFAULT_SEND_HOTKEY } = {}) {
  const fallback = normalizeHotkey(defaultKey);
  let confirmed = null;
  try { confirmed = normalizeHotkey(load()); } catch { confirmed = ''; }
  if (!confirmed || !isAllowedSendHotkey(confirmed)) confirmed = fallback;
  let declined = null;

  // Decide what the send hotkey should be right now for a requested value.
  //   effective          what to register now
  //   needsConfirmation  a normalised key the person must confirm in a native dialog, or null
  //   rejected           the request was not an allowed shortcut at all
  function evaluate(requested) {
    const raw = typeof requested === 'string' ? requested.trim() : '';
    if (raw === '') return { effective: '', needsConfirmation: null, rejected: false }; // disabled
    const key = normalizeHotkey(raw);
    if (!key || !isAllowedSendHotkey(key)) return { effective: confirmed, needsConfirmation: null, rejected: true };
    if (key === confirmed || key === fallback) return { effective: key, needsConfirmation: null, rejected: false };
    if (key === declined) return { effective: confirmed, needsConfirmation: null, rejected: false };
    return { effective: confirmed, needsConfirmation: key, rejected: false };
  }

  return {
    evaluate,
    confirm(key) {
      confirmed = normalizeHotkey(key);
      declined = null;
      try { save(confirmed); } catch { /* the choice still holds for this session */ }
    },
    decline(key) { declined = normalizeHotkey(key); },
    current: () => confirmed,
  };
}

module.exports = {
  DEFAULT_SEND_HOTKEY,
  parseChord,
  normalizeHotkey,
  isAllowedSendHotkey,
  createSendHotkeyGate,
};
