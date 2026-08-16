// P2 information architecture contract. This intentionally reads the source
// renderer: the browser QA harness consumes the built copy, while this test
// keeps the navigation vocabulary reviewable in the cheap Node suite.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const SIGNAL_DESK = new URL('../src/renderer/signal-desk.html', import.meta.url);
const markup = readFileSync(SIGNAL_DESK, 'utf8').replace(/\r\n/g, '\n');

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
  assert.match(primary, /data-nav="scribe"/, 'Scribe must route through the scribe workspace id');
  assert.doesNotMatch(primary, /data-nav="library"/, 'Library must not remain a primary route');
});

test('Scribe has one dedicated workspace and one functional text playground surface', () => {
  assert.equal((markup.match(/id="workspace-scribe"/g) || []).length, 1);
  assert.match(markup, /<section class="sd-workspace" id="workspace-scribe" data-workspace="scribe"/);
  assert.equal((markup.match(/id="textPlaygroundSection"/g) || []).length, 1);
  const scribe = regionBetween(markup, 'id="workspace-scribe"', '<!-- ---------- LIBRARY workspace');
  assert.match(scribe, /id="textPlaygroundSection"/);
  const utilities = regionBetween(markup, 'id="workspace-utilities"', '<section class="sd-workspace" id="workspace-settings"');
  assert.doesNotMatch(utilities, /id="textPlaygroundSection"/);
});

test('Scribe markup exposes exactly three normal output choices', () => {
  const scribe = regionBetween(markup, 'id="workspace-scribe"', '<!-- ---------- LIBRARY workspace');
  assert.equal((scribe.match(/class="sd-message-rescue-column"/g) || []).length, 3);
  assert.match(scribe, />Base</);
  assert.match(scribe, />Alternative one</);
  assert.match(scribe, />Alternative two</);
  assert.doesNotMatch(scribe, /textPlaygroundColumnRaw/);
});

test('Utilities exposes the retained-material and runtime destinations', () => {
  const utilitiesNav = regionBetween(markup, '<nav class="sd-util-nav"', '</nav>');
  for (const label of ['Library', 'History', 'Runtime Diagnostics', 'Game Mode']) {
    assert.match(utilitiesNav, new RegExp(`>${label}<`), `${label} must be reachable under Utilities`);
  }
  assert.match(markup, /id="sdUtilHotkeySelectionRewriteInput"[^>]+value="Ctrl\+Alt\+R"/);
  assert.match(markup, /id="sdUtilHotkeySelectionRewriteClear"/);
  assert.match(markup, /id="sdUtilHotkeySelectionRewriteError"/);
  assert.match(markup, /Select text in another app[\s\S]*never auto-replaces or sends text/);
});

test('the renamed surface has no orphaned visible Text Playground label', () => {
  assert.doesNotMatch(markup, />Text\s*(?:&amp;\s*Persona\s*)?Playground</i);
  assert.match(markup, /id="textPlaygroundSection"[\s\S]*sd-util-group__title">Scribe</, 'the text playground surface must be labelled Scribe');
});
