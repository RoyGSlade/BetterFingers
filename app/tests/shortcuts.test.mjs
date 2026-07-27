// In-app keyboard shortcuts (features/shortcuts.js), the hybrid map.
//
// The contract worth protecting: irreversible actions need a modifier and work
// everywhere; single-key actions are fast but stand down while typing. Getting
// the second half wrong means a user typing a draft silently declines it.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ACTIONS,
  KEYMAP,
  createShortcutsFeature,
  describeShortcuts,
  formatBinding,
  isTypingTarget,
  matchShortcut,
} from '../src/renderer/features/shortcuts.js';

const ev = (key, mods = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  shiftKey: false,
  altKey: false,
  ...mods,
});

// --- typing-target detection --------------------------------------------------

test('textarea, text input, select and contenteditable are typing targets', () => {
  assert.equal(isTypingTarget({ tagName: 'TEXTAREA' }), true);
  assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'text' }), true);
  assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'search' }), true);
  assert.equal(isTypingTarget({ tagName: 'SELECT' }), true);
  assert.equal(isTypingTarget({ isContentEditable: true }), true);
});

test('checkboxes, radios and buttons are NOT typing targets', () => {
  // They are <input> too. Treating them as typing targets would silently kill
  // single-key shortcuts across whole panels of toggles.
  assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'checkbox' }), false);
  assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'radio' }), false);
  assert.equal(isTypingTarget({ tagName: 'BUTTON' }), false);
  assert.equal(isTypingTarget({ tagName: 'DIV' }), false);
  assert.equal(isTypingTarget(null), false);
});

test('an input with no type attribute defaults to text', () => {
  assert.equal(isTypingTarget({ tagName: 'INPUT' }), true);
});

// --- the safety property ------------------------------------------------------

test('single-key actions do not fire while typing', () => {
  // The whole point of the hybrid map: typing "e" in a draft must not open
  // Revise, and "1" must not jump to Talk.
  for (const key of ['c', 'l', 'e', 'b', '/', '1', '5']) {
    assert.equal(matchShortcut(ev(key), { typing: true }), null, `"${key}" fired while typing`);
    assert.notEqual(matchShortcut(ev(key), { typing: false }), null, `"${key}" dead when not typing`);
  }
});

test('irreversible actions still fire while typing', () => {
  assert.equal(matchShortcut(ev('Enter', { ctrlKey: true }), { typing: true }), ACTIONS.SEND);
  assert.equal(
    matchShortcut(ev('D', { ctrlKey: true, shiftKey: true }), { typing: true }),
    ACTIONS.DECLINE,
  );
});

test('a bare letter never triggers a destructive action', () => {
  // Decline is Ctrl+Shift+D precisely so that pressing "d" cannot lose a draft.
  assert.notEqual(matchShortcut(ev('d'), { typing: false }), ACTIONS.DECLINE);
  assert.notEqual(matchShortcut(ev('r'), { typing: false }), ACTIONS.RETRY);
  assert.notEqual(matchShortcut(ev('Enter'), { typing: false }), ACTIONS.SEND);
});

// --- exact modifier matching --------------------------------------------------

test('Ctrl+Enter and Ctrl+Shift+Enter are different actions', () => {
  // "send it" vs "do not send it" -- a loose match here would make one shadow
  // the other, in the one place that is least forgiving.
  assert.equal(matchShortcut(ev('Enter', { ctrlKey: true })), ACTIONS.SEND);
  assert.equal(matchShortcut(ev('Enter', { ctrlKey: true, shiftKey: true })), ACTIONS.ACCEPT);
});

test('a bare Enter is not Send', () => {
  assert.equal(matchShortcut(ev('Enter')), null);
});

test('Alt is never a wildcard', () => {
  // Alt+1 is a window-manager gesture on many desktops; it must not navigate.
  assert.equal(matchShortcut(ev('1', { altKey: true })), null);
  assert.equal(matchShortcut(ev('Enter', { ctrlKey: true, altKey: true })), null);
});

test('Cmd is accepted as Ctrl for macOS', () => {
  assert.equal(matchShortcut(ev('Enter', { metaKey: true })), ACTIONS.SEND);
});

test('Caps Lock does not disable letter shortcuts', () => {
  assert.equal(matchShortcut(ev('C'), { typing: false }), ACTIONS.COPY);
});

test('shifted punctuation reaches its shortcut', () => {
  // "?" is Shift+/ on most layouts, so the browser reports key "?" WITH
  // shiftKey true. Demanding an exact shift match on bare keys made the
  // shortcut sheet -- the thing that makes every other binding discoverable --
  // permanently unreachable.
  assert.equal(matchShortcut(ev('?', { shiftKey: true }), { typing: false }), ACTIONS.SHOW_HELP);
});

test('Shift still distinguishes chorded bindings', () => {
  // The bare-key relaxation must not leak into chords: send vs do-not-send.
  assert.equal(matchShortcut(ev('Enter', { ctrlKey: true, shiftKey: false })), ACTIONS.SEND);
  assert.equal(matchShortcut(ev('Enter', { ctrlKey: true, shiftKey: true })), ACTIONS.ACCEPT);
});

// --- no collisions with reserved keys -----------------------------------------

test('the map avoids the global hotkeys', () => {
  // F8 record / F9 manual send / Ctrl+Shift+Space read-aloud fire system-wide.
  // A duplicate here would handle one press twice.
  assert.equal(matchShortcut(ev('F8')), null);
  assert.equal(matchShortcut(ev('F9')), null);
  assert.equal(matchShortcut(ev(' ', { ctrlKey: true, shiftKey: true })), null);
});

test('the map leaves Chromium editing shortcuts alone', () => {
  // Ctrl+C must keep meaning "copy the selection" once Talk has a textarea.
  for (const key of ['a', 'c', 'v', 'x', 'z', 'y', 'r', 'w', 'f', 'p']) {
    assert.equal(
      matchShortcut(ev(key, { ctrlKey: true })),
      null,
      `Ctrl+${key.toUpperCase()} should be left to the browser`,
    );
  }
});

test('every binding is unique', () => {
  const seen = new Set();
  for (const b of KEYMAP) {
    const sig = `${String(b.key).toLowerCase()}|${Boolean(b.ctrl)}|${Boolean(b.shift)}`;
    assert.equal(seen.has(sig), false, `duplicate binding: ${formatBinding(b)}`);
    seen.add(sig);
  }
});

test('only modifier-guarded bindings may act while typing', () => {
  // Escape is the one deliberate exception: it cancels, it never destroys.
  for (const b of KEYMAP) {
    if (!b.whileTyping) continue;
    const guarded = b.ctrl || b.key === 'Escape';
    assert.ok(guarded, `${formatBinding(b)} acts while typing without a modifier`);
  }
});

// --- feature wiring -----------------------------------------------------------

function makeDoc() {
  const listeners = {};
  return {
    activeElement: null,
    addEventListener: (evt, fn) => {
      listeners[evt] = fn;
    },
    removeEventListener: (evt) => {
      delete listeners[evt];
    },
    fire: (event) => listeners.keydown?.(event),
    hasListener: () => Boolean(listeners.keydown),
  };
}

test('dispatches to the handler and consumes the key', () => {
  const doc = makeDoc();
  const calls = [];
  const feature = createShortcutsFeature({
    handlers: { [ACTIONS.SEND]: () => calls.push('send') },
    doc,
  });
  feature.init();

  let prevented = false;
  doc.fire({ ...ev('Enter', { ctrlKey: true }), target: null, preventDefault: () => { prevented = true; } });

  assert.deepEqual(calls, ['send']);
  assert.equal(prevented, true);
});

test('an unimplemented action falls through instead of being eaten', () => {
  // The overlay implements a subset. Swallowing keys it does not handle would
  // break the browser's own behaviour for no reason.
  const doc = makeDoc();
  const feature = createShortcutsFeature({ handlers: {}, doc });
  feature.init();

  let prevented = false;
  doc.fire({ ...ev('Enter', { ctrlKey: true }), target: null, preventDefault: () => { prevented = true; } });
  assert.equal(prevented, false);
});

test('uses the event target to decide whether the user is typing', () => {
  const doc = makeDoc();
  const calls = [];
  const feature = createShortcutsFeature({
    handlers: { [ACTIONS.COPY]: () => calls.push('copy') },
    doc,
  });
  feature.init();

  doc.fire({ ...ev('c'), target: { tagName: 'TEXTAREA' }, preventDefault() {} });
  assert.deepEqual(calls, [], 'single-key action fired from inside a textarea');

  doc.fire({ ...ev('c'), target: { tagName: 'DIV' }, preventDefault() {} });
  assert.deepEqual(calls, ['copy']);
});

test('destroy unbinds, and init is idempotent', () => {
  const doc = makeDoc();
  const feature = createShortcutsFeature({ handlers: {}, doc });
  feature.init();
  feature.init();
  assert.equal(doc.hasListener(), true);
  feature.destroy();
  assert.equal(doc.hasListener(), false);
});

// --- shortcut sheet -----------------------------------------------------------

test('describeShortcuts lists only what a surface implements', () => {
  const groups = describeShortcuts([ACTIONS.SEND, ACTIONS.DECLINE]);
  const actions = groups.flatMap((g) => g.items.map((i) => i.action));
  assert.deepEqual(actions.sort(), [ACTIONS.DECLINE, ACTIONS.SEND].sort());
});

test('accelerators render the way users read them', () => {
  assert.equal(formatBinding({ key: 'Enter', ctrl: true }), 'Ctrl+Enter');
  assert.equal(formatBinding({ key: 'D', ctrl: true, shift: true }), 'Ctrl+Shift+D');
  assert.equal(formatBinding({ key: '/' }), '/');
});
