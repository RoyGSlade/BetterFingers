// Unit tests for W4-COMP-FIX: bootstrap/signalDeskApp.js's auto-start guard.
//
// The guard used to read `document.currentScript !== null` to decide whether
// it was loaded as the page's own entry `<script type="module">` -- but per
// the HTML spec (and MDN's explicit note), document.currentScript is ALWAYS
// null while a *module* script evaluates; that only applies to classic
// scripts. signal-desk.html loads this file as `<script type="module"
// src="./bootstrap/signalDeskApp.js">`, so the old guard's condition was
// always false and startSignalDeskApp() never ran in production. The fix
// replaces it with the same explicit-opt-in contract lib/autowire.mjs already
// established for personaLearning.js/messageRescuePanel.js/textPlayground.js
// (see rendererSelfInit.test.mjs), but with a *different* attribute value
// ('signal-desk', not 'legacy') so this composition root does not also
// trigger those three modules' own self-init -- it wires them itself, with
// its own hooks (see signalDeskApp.js's own comment above its
// initMessageRescuePanel()/initTextPlayground() calls).
//
// Run with: node --test app/tests/signalDeskApp.test.mjs
//
// Fully booting startSignalDeskApp() against a stub document would need every
// workspace's collectXElements(doc) to succeed *and* real network/WebSocket
// calls (api.fetchOutputSettings(), api.connectVoiceStatus(), ...) to resolve
// cleanly with no leaked timers or sockets in a test process -- impractical,
// and not what this guard is actually responsible for verifying. These tests
// instead probe the guard's decision at the smallest honest seam: does
// autowireMode(document) === 'signal-desk' actually reach into the document
// to start wiring, or does it stay inert? makeProbeDoc()'s getElementById/
// querySelector/querySelectorAll throw the instant anything calls them, and
// collectShellElements(doc) (startSignalDeskApp's very first statement, see
// features/signalDeskShell.js) calls straight into them -- so a thrown
// ProbeError proves an attempted start, and its absence proves the guard
// stayed inert, without ever reaching the timers/network calls deeper in the
// function body. This does not cover whether a real boot wires every
// workspace correctly -- only whether the auto-start decision itself is
// correct.
//
// Import-time side effects only run once per resolved module URL (ES module
// instances are cached by specifier -- see rendererSelfInit.test.mjs's own
// comment on this), so each test that needs a fresh top-level evaluation of
// signalDeskApp.js dynamically imports it with a unique cache-busting query
// string. signalDeskApp.js's own *internal* imports (messageRescuePanel.js,
// textPlayground.js, ...) are never cache-busted, so those load once for the
// whole file. messageRescuePanel.js/textPlayground.js each still carry their
// own `if (shouldAutowire()) { init*(); }` self-init check against
// globalThis.document at that one-time load -- deliberately never triggered
// by any probe doc here (none of them carry AUTOWIRE_LEGACY_VALUE), so they
// never call into the probe and never pre-empt the throw this file relies on.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  AUTOWIRE_ATTRIBUTE,
  AUTOWIRE_LEGACY_VALUE,
  AUTOWIRE_SIGNAL_DESK_VALUE,
  autowireMode,
  shouldAutowire,
} from '../src/renderer/lib/autowire.mjs';

const MODULE_URL = new URL('../src/renderer/bootstrap/signalDeskApp.js', import.meta.url).href;

let importCounter = 0;
function importFresh(url) {
  importCounter += 1;
  return import(`${url}?bf-signaldeskapp-test=${importCounter}`);
}

class ProbeError extends Error {}

// autowireValue is whatever a real <html data-bf-autowire="..."> would carry
// -- null for "attribute absent" is the honest default. getElementById/
// querySelector/querySelectorAll never return; they throw the moment
// anything calls them, and record that they were called first so a test can
// assert "never touched" even in the (expected) case where nothing throws.
function makeProbeDoc(autowireValue) {
  const state = { touched: false };
  const throwProbe = () => {
    state.touched = true;
    throw new ProbeError('signalDeskApp reached into the document');
  };
  return {
    _state: state,
    documentElement: {
      getAttribute: (name) => (name === AUTOWIRE_ATTRIBUTE ? autowireValue : null),
    },
    getElementById: throwProbe,
    querySelector: throwProbe,
    querySelectorAll: throwProbe,
  };
}

async function withGlobalDocument(doc, fn) {
  const hadDocument = 'document' in globalThis;
  const previousDocument = globalThis.document;
  globalThis.document = doc;
  try {
    return await fn();
  } finally {
    if (hadDocument) globalThis.document = previousDocument;
    else delete globalThis.document;
  }
}

// --- lib/autowire.mjs: autowireMode() + the legacy/signal-desk contract ----

test('autowireMode: returns the raw attribute value, not a boolean', () => {
  const doc = { documentElement: { getAttribute: () => AUTOWIRE_SIGNAL_DESK_VALUE } };
  assert.equal(autowireMode(doc), AUTOWIRE_SIGNAL_DESK_VALUE);
});

test('autowireMode: null when the marker attribute is absent', () => {
  const doc = { documentElement: { getAttribute: () => null } };
  assert.equal(autowireMode(doc), null);
});

test('autowireMode: null with no document / no documentElement', () => {
  assert.equal(autowireMode(null), null);
  assert.equal(autowireMode(undefined), null);
  assert.equal(autowireMode({}), null);
});

test('shouldAutowire: true for "legacy", false for "signal-desk" -- the two contracts stay distinct', () => {
  const legacyDoc = { documentElement: { getAttribute: () => AUTOWIRE_LEGACY_VALUE } };
  const signalDeskDoc = { documentElement: { getAttribute: () => AUTOWIRE_SIGNAL_DESK_VALUE } };
  assert.equal(shouldAutowire(legacyDoc), true);
  assert.equal(shouldAutowire(signalDeskDoc), false);
});

// --- bootstrap/signalDeskApp.js auto-start guard ----------------------------
//
// IMPORTANT: none of these tests use AUTOWIRE_LEGACY_VALUE in a probe doc
// passed through withGlobalDocument()/importFresh(). messageRescuePanel.js
// and textPlayground.js are transitively imported by signalDeskApp.js and
// each read globalThis.document at their own one-time load to decide whether
// to self-init; if that ever saw 'legacy' here they'd wire against (and
// throw via) the probe themselves, for a reason unrelated to what these
// tests check. Using null / an unrelated string keeps the probe throw
// attributable only to signalDeskApp.js's own guard.

test('signalDeskApp: import against a document without the marker does not auto-start', async () => {
  const doc = makeProbeDoc(null);
  await assert.doesNotReject(() => withGlobalDocument(doc, () => importFresh(MODULE_URL)));
  assert.equal(doc._state.touched, false);
});

test('signalDeskApp: import against a document with an unrelated marker value does not auto-start', async () => {
  const doc = makeProbeDoc('some-other-page');
  await assert.doesNotReject(() => withGlobalDocument(doc, () => importFresh(MODULE_URL)));
  assert.equal(doc._state.touched, false);
});

test('signalDeskApp: import against a document with data-bf-autowire="signal-desk" DOES auto-start', async () => {
  const doc = makeProbeDoc(AUTOWIRE_SIGNAL_DESK_VALUE);
  await assert.rejects(
    () => withGlobalDocument(doc, () => importFresh(MODULE_URL)),
    ProbeError,
  );
  assert.equal(doc._state.touched, true);
});

test('signalDeskApp: startSignalDeskApp is exported and callable explicitly, independent of the guard', async () => {
  // Import against a non-opted-in document so the module's own auto-start
  // guard stays inert; the module namespace is still fully populated.
  const mod = await withGlobalDocument(makeProbeDoc(null), () => importFresh(MODULE_URL));
  assert.equal(typeof mod.startSignalDeskApp, 'function');

  // Calling it directly, with its own fresh probe doc argument (not via
  // globalThis.document), proves it is a real, invocable implementation --
  // it reaches into the *passed* doc the same way the auto-start path
  // reaches into the global one.
  const explicitDoc = makeProbeDoc(null);
  assert.throws(() => mod.startSignalDeskApp(explicitDoc), ProbeError);
  assert.equal(explicitDoc._state.touched, true);
});
