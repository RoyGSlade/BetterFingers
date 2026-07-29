// Wave 12A: static guards on the NATIVE FORM CONTROL CONTRACT.
// Run with: node --test app/tests/uiControlContract.test.mjs
//
// The behavioural evidence for this wave is
// app/tests/qa/scenarios/ui-controls-prod.mjs, which drives the real page in
// Electron and reads real computed styles. This file is the cheap half: it
// catches the two regressions that would otherwise only surface in a full QA
// run, in milliseconds, with no browser.
//
// WHAT THESE GUARD, AND WHY EACH ONE IS A REAL FAILURE MODE THAT ALREADY
// HAPPENED ONCE:
//
//   1. signal-desk.html links exactly ONE stylesheet. Every class a feature
//      module emits onto that page must be defined in that stylesheet. The
//      original bug was not a bad style -- it was voiceStudio.js emitting
//      `secondary-button`/`settings-input`/`setting-row`, which are defined
//      only in styles/base.css, a file this page does not load. That is
//      undetectable by reading either file alone, and it shipped.
//   2. The five per-family select rules must not use the `background`
//      SHORTHAND. A class rule (0-1-0) beats the element rule (0-0-1), and the
//      shorthand resets background-image -- so a well-meaning
//      `background: var(--sd-surface-inset)` in any of them silently deletes
//      the chevron from that whole family again. This is the single easiest
//      way for a future edit to reintroduce finding (1).
//
// No jsdom in this repo (see messageRescuePanel.test.mjs); both guards are
// source-text analyses, which is all they need to be.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const RENDERER = join(HERE, '..', 'src', 'renderer');

const html = readFileSync(join(RENDERER, 'signal-desk.html'), 'utf8');
const css = readFileSync(join(RENDERER, 'styles', 'signal-desk.css'), 'utf8');

/** Class tokens the stylesheet defines anywhere in a selector. */
function definedClasses(source) {
  // Strip comments first: this file's own header quotes class names in prose
  // (".sd-review-select option { color: #000 }"), and counting those as
  // definitions would make the guard pass on documentation alone.
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, '');
  return new Set(Array.from(withoutComments.matchAll(/\.([A-Za-z0-9_-]+)/g), (m) => m[1]));
}

/** Class tokens a JS module hands to className / classList.add / a literal class="...". */
function emittedClasses(source) {
  const found = new Set();
  for (const m of source.matchAll(/className\s*=\s*['"]([^'"]*)['"]/g)) {
    for (const t of m[1].split(/\s+/)) if (t) found.add(t);
  }
  for (const m of source.matchAll(/classList\.add\(([^)]*)\)/g)) {
    for (const q of m[1].matchAll(/['"]([A-Za-z0-9_ -]+)['"]/g)) {
      for (const t of q[1].split(/\s+/)) if (t) found.add(t);
    }
  }
  for (const m of source.matchAll(/class="([^"$`{}]*)"/g)) {
    for (const t of m[1].split(/\s+/)) if (t) found.add(t);
  }
  return found;
}

test('signal-desk.html links exactly one stylesheet (the premise every other guard here rests on)', () => {
  const links = Array.from(html.matchAll(/<link[^>]*rel="stylesheet"[^>]*>/g), (m) => m[0]);
  assert.equal(
    links.length,
    1,
    `expected exactly one stylesheet link, found ${links.length}: ${links.join(' | ')}. ` +
      'If a second one was added deliberately, this guard and the legacy-class reasoning in ' +
      'styles/signal-desk.css both need rewriting -- do not just bump the number.',
  );
  assert.match(links[0], /styles\/signal-desk\.css/);
});

test('every class signal-desk.html itself emits is defined in the one stylesheet it loads', () => {
  const defined = definedClasses(css);
  // Scoped to the classes whose absence produces a RAW BROWSER WIDGET --
  // buttons, selects and inputs. That is the line this wave's contract draws,
  // and it is a property of the element, not a naming convention: an undefined
  // wrapper class renders as an unstyled <div>, which is invisible; an
  // undefined class on a <button> renders as a grey UA slab, which is the bug.
  // A pattern, deliberately, rather than an allowlist of known-missing names:
  // allowlists grow until they mean nothing. Non-control classes that are
  // still undefined on this page (e.g. `.sd-trait-field`, whose five BEM
  // children ARE defined) are reported upward in the Wave 12A handoff instead.
  const controlish = /(btn|button|select|input)/i;
  const missing = Array.from(emittedClasses(html))
    .filter((c) => c.startsWith('sd-') && controlish.test(c) && !defined.has(c))
    .sort();
  assert.deepEqual(
    missing,
    [],
    'these control classes are used in signal-desk.html but defined nowhere in styles/signal-desk.css, ' +
      'so they render as raw browser widgets (this is exactly how `sd-select` and `sd-button--ghost` shipped)',
  );
});

test('features/voiceStudio.js emits no base.css-only class names (the finding-(4) regression guard)', () => {
  const source = readFileSync(join(RENDERER, 'features', 'voiceStudio.js'), 'utf8');
  const defined = definedClasses(css);
  const missing = Array.from(emittedClasses(source))
    .filter((c) => !defined.has(c))
    .sort();
  assert.deepEqual(
    missing,
    [],
    'voiceStudio.js renders into signal-desk.html, which loads only styles/signal-desk.css. ' +
      'Any class not defined there renders unstyled -- that is what made the whole Blend surface ' +
      'look like raw HTML on the default page.',
  );
});

test('no select class family uses the `background` shorthand (it would erase the chevron)', () => {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const families = [
    '.sd-review-select',
    '.sd-util-select',
    '.sd-set-select',
    '.sd-input',
    '.sd-library-filters__control',
    '.sd-select',
    '.settings-input',
  ];
  const offenders = [];
  for (const family of families) {
    // Each rule block that mentions this family in its selector list.
    const pattern = new RegExp(`([^{}]*\\${family}\\b[^{}]*)\\{([^}]*)\\}`, 'g');
    for (const m of withoutComments.matchAll(pattern)) {
      if (/(^|;)\s*background\s*:/.test(m[2])) {
        offenders.push(`${m[1].trim().replace(/\s+/g, ' ')} { ... background: ... }`);
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    'A class rule beats the element-level `select` rule, and the `background` shorthand resets ' +
      'background-image -- so this deletes the chevron and the backplate for that entire family and ' +
      'reintroduces the native GTK arrow. Use `background-color`.',
  );
});

test('the element-level select rule declares both halves of the popup fix', () => {
  const block = css.match(/\nselect \{([\s\S]*?)\n\}/);
  assert.ok(block, 'the element-level `select` rule must exist -- it is the whole contract');
  assert.match(block[1], /appearance:\s*none/, 'select must not render the native arrow');
  assert.match(block[1], /color-scheme:\s*dark/, 'select must request the dark native widget set');

  const optionRule = css.match(/\nselect option,\s*\nselect optgroup \{([\s\S]*?)\n\}/);
  assert.ok(optionRule, '`select option, select optgroup` must set the popup colors');
  assert.match(optionRule[1], /background-color:/);
  assert.match(optionRule[1], /color:/);

  assert.doesNotMatch(
    css.replace(/\/\*[\s\S]*?\*\//g, ''),
    /\.sd-review-select\s+option\s*\{[^}]*color:\s*#000/,
    'this is the exact rule that caused finding (2) -- black option text in a platform-dark popup',
  );
});
