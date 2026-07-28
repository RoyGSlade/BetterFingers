// Shared opt-in gate for renderer feature modules that self-initialize at
// import time (personaLearning.js, messageRescuePanel.js, textPlayground.js).
//
// Each of those modules is loaded via its own <script type="module"> tag and
// wires its DOM the moment it's imported -- there is no explicit "boot" call
// a host page makes. That's fine for a page that owns those ids and expects
// them wired, but it's a landmine for anything else that imports the module:
// a test file, a bundler doing tree-shaking analysis, or another page (e.g.
// Signal Desk's studioWorkspace.js) that happens to reuse a matching id for
// an unrelated purpose. See studioWorkspace.js's "ID-COLLISION NOTE" for the
// double-binding bug this caused before ids were deliberately renamed to
// dodge it.
//
// shouldAutowire() makes that opt-in explicit and structural instead of
// implicit-and-hope: a document only autowires if its <html> element
// declares `data-bf-autowire="legacy"`. index.html (the legacy shipping UI)
// carries that marker so its behaviour is unchanged; any other document --
// including a bare test DOM or a future composition root that imports these
// modules for their pure logic without wanting the auto-wiring -- gets
// nothing bound until it either adds the marker or calls the module's
// exported init*() function itself.
//
// "legacy" (rather than a bare boolean-ish flag) names what's opting in, in
// case a future non-legacy autowire contract needs a different value here.
export const AUTOWIRE_ATTRIBUTE = 'data-bf-autowire';
export const AUTOWIRE_LEGACY_VALUE = 'legacy';

// A second, distinct value for the Signal Desk composition root
// (bootstrap/signalDeskApp.js): that page must NOT self-wire
// personaLearning.js/messageRescuePanel.js/textPlayground.js via
// shouldAutowire() (it calls their explicit init*() itself, with its own
// hooks), so it carries this value instead of 'legacy'. shouldAutowire()
// only ever returns true for 'legacy' -- see its own comment.
export const AUTOWIRE_SIGNAL_DESK_VALUE = 'signal-desk';

export function shouldAutowire(doc = globalThis.document) {
  const activeDoc = doc || null;
  const root = activeDoc && activeDoc.documentElement;
  if (!root || typeof root.getAttribute !== 'function') return false;
  return root.getAttribute(AUTOWIRE_ATTRIBUTE) === AUTOWIRE_LEGACY_VALUE;
}

// General accessor: returns the raw data-bf-autowire value on doc's <html>
// element (whatever it is -- 'legacy', 'signal-desk', some future value, or
// null if absent/unparsable), instead of collapsing it to a boolean the way
// shouldAutowire() deliberately does for its one specific contract. Callers
// that need to opt in to a *different* autowire contract (e.g. the Signal
// Desk composition root auto-starting itself) compare this against their own
// expected value rather than overloading shouldAutowire().
export function autowireMode(doc = globalThis.document) {
  const activeDoc = doc || null;
  const root = activeDoc && activeDoc.documentElement;
  if (!root || typeof root.getAttribute !== 'function') return null;
  return root.getAttribute(AUTOWIRE_ATTRIBUTE);
}
