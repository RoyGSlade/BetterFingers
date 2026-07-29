// Static contract tests for the two parity rows that assert a NEGATIVE property.
//
// Wave 12 director ruling: UI-12-008 ("no backend calls -- pure IPC-driven
// presentation layer") and UI-15-007 ("donation prompt -- none found anywhere")
// were stuck `blocked (evidence)` for a structural reason, not a product one:
// the strict D-0015 chain wants a production ANCHOR, and an absence has no
// anchor by construction. You cannot point at the element that isn't there.
//
// The handle they lacked is this file. A property of the form "X appears
// nowhere in the shipping closure" is exactly the kind of thing a static check
// over source CAN evidence, and it evidences it more strongly than a QA
// scenario could -- a scenario proves the prompt did not appear on the screens
// it visited, whereas this proves the string is not in the code at all.
//
// Pattern follows app/tests/mainScopeLint.test.mjs: read the real shipping
// source, assert a property over it, no DOM and no app launch.
//
// Run with: node --test app/tests/negativeProperties.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const RENDERER = join(HERE, '..', 'src', 'renderer');

// --- UI-12-008: the overlay windows make no backend calls of their own -------
//
// SCOPE, stated precisely so this is not read as more than it is.
//
// The row describes the two floating overlay WINDOWS as a "pure IPC-driven
// presentation layer". What is asserted here is that their own inline scripts
// contain no network-initiating browser API: every backend interaction leaves
// through `window.betterFingers.backendRequest` / `sendDraft`, which are
// contextBridge methods handled in the main process (see review-overlay.html's
// proxyReq()).
//
// What this deliberately does NOT assert: review-overlay.html imports pure
// helpers from features/talkWorkspace.js (the confidence band/percent mapping,
// reused rather than re-derived). That module is part of the DASHBOARD's
// closure and does talk to the backend on its own behalf; importing a pure
// function out of it is not the overlay making a call. Extending this check
// transitively through imports would therefore fail on a file that is not the
// subject of the row. The row is about the overlay renderers, and so is this.
const OVERLAY_PAGES = ['overlay.html', 'review-overlay.html'];

// Network-initiating APIs. `backendRequest`/`sendDraft` are absent from this
// list on purpose -- routing through them is the contract, not a violation.
const NETWORK_APIS = [
  { token: 'fetch(', why: 'direct fetch() bypasses the main-process proxy' },
  { token: 'XMLHttpRequest', why: 'direct XHR bypasses the main-process proxy' },
  { token: 'new WebSocket', why: 'the overlays consume IPC pushes, never their own socket' },
  { token: 'EventSource', why: 'the overlays consume IPC pushes, never their own stream' },
  { token: 'sendBeacon', why: 'a beacon is an unreviewable outbound request' },
];

// Read RAW -- comments are not stripped, and that is a deliberate choice.
//
// docs/release/DECISIONS.md records a comment-stripper in this repo that got
// regex literals wrong and silently swallowed real code, which let a lane
// claim an id shipped when it existed only inside a comment. A stripper that
// is subtly wrong fails OPEN here (it would hide a real call), so this check
// does without one. The cost is that a future comment writing `fetch(` in
// prose trips the test; the fix is to reword the comment, and that is a much
// better failure than a false green.
test('UI-12-008: neither overlay window makes a backend call of its own', () => {
  for (const page of OVERLAY_PAGES) {
    const source = readFileSync(join(RENDERER, page), 'utf8');
    const found = networkHits(source);
    const why = NETWORK_APIS.filter((a) => found.includes(a.token)).map((a) => a.why).join('; ');
    assert.deepEqual(
      found,
      [],
      `${page} contains ${found.join(', ')} -- ${why}. The overlays must reach the backend only `
        + 'through window.betterFingers.backendRequest / sendDraft (main-process proxy).',
    );
  }
});

test('UI-12-008: the overlays DO route through the main-process bridge', () => {
  // The negative above is only meaningful alongside this positive: a file that
  // made no calls at all would pass the absence check trivially. review-overlay
  // is the one that talks to the backend, so it must show the approved route.
  const review = readFileSync(join(RENDERER, 'review-overlay.html'), 'utf8');
  assert.ok(
    review.includes('window.betterFingers.backendRequest')
      || review.includes('betterFingers && window.betterFingers.backendRequest'),
    'review-overlay.html must reach the backend through the contextBridge proxy',
  );
});

// --- UI-15-007: no donation prompt anywhere in the shipping renderer ---------
//
// The source row reads "none found anywhere in the scoped files (index.html,
// main.js, features/*, overlays). If one exists it must live outside this
// scope." This widens the search to the WHOLE renderer tree rather than that
// hand-listed subset, so the evidence is stronger than the claim it settles.
const MONETISATION_TERMS = [
  'donate',
  'donation',
  'patreon',
  'ko-fi',
  'kofi',
  'paypal',
  'buymeacoffee',
  'buy me a coffee',
  'tip jar',
  'gofundme',
  'opencollective',
  'open collective',
];

/** True when `source` violates the no-monetisation property. */
function monetisationHits(source) {
  const haystack = source.toLowerCase();
  return MONETISATION_TERMS.filter((term) => haystack.includes(term));
}

/** True when `source` violates the no-own-network-calls property. */
function networkHits(source) {
  return NETWORK_APIS.filter(({ token }) => source.includes(token)).map(({ token }) => token);
}

// A test that asserts an ABSENCE passes for two very different reasons: the
// property holds, or the detector is broken. Those are indistinguishable from
// a green run, which is the standing failure mode of every "we found none"
// check. So the detectors are made to catch known violations here. If someone
// later narrows a term list or fat-fingers a regex, this goes red immediately
// instead of the absence checks going quietly, permanently green.
test('the detectors above actually catch violations (guards the guards)', () => {
  assert.deepEqual(
    monetisationHits('<a href="https://www.patreon.com/x">Support us</a>'),
    ['patreon'],
    'a donation link must be caught',
  );
  assert.deepEqual(
    monetisationHits('<button>Buy Me A Coffee</button>'),
    ['buy me a coffee'],
    'matching must be case-insensitive',
  );
  assert.deepEqual(
    networkHits('const res = await fetch(`${BACKEND_ORIGIN}/drafts`);'),
    ['fetch('],
    'a direct fetch must be caught',
  );
  assert.deepEqual(networkHits('const s = new WebSocket(url);'), ['new WebSocket']);
  // ...and stay quiet on the approved route, or the checks would forbid the
  // very thing the overlays are supposed to do.
  assert.deepEqual(networkHits('await window.betterFingers.backendRequest("POST", path);'), []);
  assert.deepEqual(monetisationHits('renderConfidenceBadge(draft);'), []);
});

function everyRendererFile(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      everyRendererFile(full, out);
    } else if (/\.(js|mjs|html|css)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

test('UI-15-007: no donation or monetisation prompt exists anywhere in the renderer', () => {
  const files = everyRendererFile(RENDERER);

  // Guard the guard: a search that silently matched nothing because it walked
  // an empty tree would "pass" while proving nothing at all.
  assert.ok(files.length > 20, `expected the renderer tree to be walked, saw ${files.length} files`);

  const hits = [];
  for (const file of files) {
    for (const term of monetisationHits(readFileSync(file, 'utf8'))) {
      hits.push(`${relative(RENDERER, file)}: ${term}`);
    }
  }

  assert.deepEqual(
    hits,
    [],
    'BetterFingers ships no donation prompt. If one is being added deliberately, this row '
      + '(UI-15-007) is the release record that says it did not exist, and it must be updated in '
      + `docs/release/PARITY_INVENTORY.md rather than this test loosened. Found: ${hits.join(', ')}`,
  );
});
