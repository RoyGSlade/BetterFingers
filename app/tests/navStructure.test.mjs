// P2 information architecture contract. This intentionally reads the source
// renderer: the browser QA harness consumes the built copy, while this test
// keeps the navigation vocabulary reviewable in the cheap Node suite.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const SIGNAL_DESK = new URL('../src/renderer/signal-desk.html', import.meta.url);
const markup = readFileSync(SIGNAL_DESK, 'utf8');

function regionBetween(source, start, end) {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.notEqual(startIndex, -1, `missing region start: ${start}`);
  assert.notEqual(endIndex, -1, `missing region end: ${end}`);
  return source.slice(startIndex, endIndex);
}

test('primary navigation names the writing surface Scribe, not Library', () => {
  const primary = regionBetween(markup, '<div class="sd-nav__primary"', '</div>\n\n        <button');
  assert.match(primary, />Scribe</, 'Scribe must be a primary navigation label');
  assert.doesNotMatch(primary, />Library</, 'Library must not remain a primary navigation label');
});

test('Utilities exposes the retained-material and runtime destinations', () => {
  const utilitiesNav = regionBetween(markup, '<nav class="sd-util-nav"', '</nav>');
  for (const label of ['Library', 'History', 'Runtime Diagnostics', 'Game Mode']) {
    assert.match(utilitiesNav, new RegExp(`>${label}<`), `${label} must be reachable under Utilities`);
  }
});

test('the renamed surface has no orphaned visible Text Playground label', () => {
  assert.doesNotMatch(markup, />Text\s*(?:&amp;\s*Persona\s*)?Playground</i);
  assert.match(markup, /sd-util-group__title">Scribe</, 'the former text playground surface must be labelled Scribe');
});
