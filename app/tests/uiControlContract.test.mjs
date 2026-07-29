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

// ==========================================================================
// worker-ui-sweep pass: native control accent-color, WCAG contrast, and
// small-window overflow guards. Same source-text idiom as above -- no jsdom,
// no browser. The contrast math mirrors app/tests/qa/scenarios/ui-controls-prod.mjs's
// "compute the real ratio" approach rather than eyeballing colors.
// ==========================================================================

function hexToRgb(hex) {
  let h = hex.replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function relativeLuminance([r, g, b]) {
  const f = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [R, G, B] = [f(r), f(g), f(b)];
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

function contrastRatio(hex1, hex2) {
  const L1 = relativeLuminance(hexToRgb(hex1));
  const L2 = relativeLuminance(hexToRgb(hex2));
  const [lighter, darker] = L1 >= L2 ? [L1, L2] : [L2, L1];
  return (lighter + 0.05) / (darker + 0.05);
}

function compositeOver(fgHex, alpha, bgHex) {
  const [fr, fg, fb] = hexToRgb(fgHex);
  const [br, bg, bb] = hexToRgb(bgHex);
  const mix = (f, b) => Math.round(f * alpha + b * (1 - alpha));
  return `#${[mix(fr, br), mix(fg, bg), mix(fb, bb)].map((x) => x.toString(16).padStart(2, '0')).join('')}`;
}

/** Pull a `--token: #hex;` value out of the :root block, so these tests break
 * if the token's own definition drifts away from the value they were proven
 * against, instead of silently testing a stale literal. */
function tokenHex(name) {
  const m = css.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{3,6})`));
  assert.ok(m, `expected --${name} to be defined in :root as a hex color`);
  return m[1];
}

test('accent-color is set on every checkbox/radio group this wave touched', () => {
  // Chromium honours `accent-color` for native checkbox/radio fill even under
  // GTK, and the app already uses --sd-cyan for every OTHER checkbox/radio on
  // the page (.sd-check, .sd-util-checkbox, .sd-set-checkbox, .sd-trait-slider,
  // .sd-flow__consent). These three groups had a real <input> with no rule at
  // all, so they rendered the UA/GTK blue accent instead of the app's own.
  for (const selector of [
    '.sd-teach-panel__checkbox-row input',
    '.sd-message-rescue-variant-option input',
    '.sd-voice-studio__consent input',
  ]) {
    const escaped = selector.replace(/[.]/g, '\\.');
    const pattern = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`);
    const block = css.match(pattern);
    assert.ok(block, `expected a rule for \`${selector}\``);
    assert.match(block[1], /accent-color:\s*var\(--sd-cyan\)/, `\`${selector}\` must set accent-color`);
  }
});

test('the Voice Studio modulation sliders (pitch/energy/warmth/brightness) get the app accent color', () => {
  const block = css.match(/\.sd-voice-studio__slider input\[type="range"\]\s*\{([^}]*)\}/);
  assert.ok(block, 'expected a rule for `.sd-voice-studio__slider input[type="range"]`');
  assert.match(
    block[1],
    /accent-color:\s*var\(--sd-cyan\)/,
    'these four range inputs (#voicePitch/#voiceEnergy/#voiceWarmth/#voiceBrightness) carry no class of ' +
      "their own -- only this selector reaches them -- and every other slider family in the app uses the " +
      'cyan accent; these were left on the UA/GTK default blue.',
  );
});

test('--sd-label-color (39x .sd-field__label + first-run labels) no longer hardcodes the failing muted hex', () => {
  // The token used to be a literal `#5B6B7C` (a copy-paste of --sd-text-muted).
  // It is now an alias so the two can be re-tuned independently; assert the
  // alias points at --sd-text-secondary rather than re-introducing a literal.
  const declLine = css.match(/--sd-label-color:\s*([^;]+);/);
  assert.ok(declLine, 'expected --sd-label-color to be declared in :root');
  assert.match(
    declLine[1].trim(),
    /^var\(--sd-text-secondary\)$/,
    `--sd-label-color must alias --sd-text-secondary, not a literal hex (got \`${declLine[1].trim()}\`) -- ` +
      'the old literal (#5B6B7C, --sd-text-muted\'s value) measured 3.20-3.54:1 against every surface token ' +
      'in this palette, below the 4.5:1 AA floor for the field/panel label text it colors.',
  );

  const labelColor = tokenHex('sd-text-secondary');
  for (const [name, bgToken] of [
    ['sd-surface-raised', 'sd-surface-raised'],
    ['sd-surface', 'sd-surface'],
    ['sd-surface-inset', 'sd-surface-inset'],
    ['sd-bg-base', 'sd-bg-base'],
  ]) {
    const bg = tokenHex(bgToken);
    const ratio = contrastRatio(labelColor, bg);
    assert.ok(
      ratio >= 4.5,
      `--sd-text-secondary (${labelColor}), what --sd-label-color now resolves to, on --${name} (${bg}) is ` +
        `${ratio.toFixed(2)}:1, below the 4.5:1 floor for normal-size text.`,
    );
  }
});

test('the per-selector label blocks this wave touched no longer use --sd-text-muted', () => {
  // --sd-text-muted itself computes to 3.20-3.54:1 against every surface
  // token in this palette -- below AA for the normal-size uppercase label
  // text these selectors render. Fixed to --sd-text-secondary (6.82-7.53:1
  // against the same surfaces). This guards the specific selectors fixed;
  // it is not a blanket ban on --sd-text-muted (still valid for decorative
  // glyphs/chevrons/dots, which WCAG 1.4.3 does not cover).
  const mutedTextSecondaryTarget = tokenHex('sd-text-secondary');
  const surfaceRaised = tokenHex('sd-surface-raised');
  const secondaryRatio = contrastRatio(mutedTextSecondaryTarget, surfaceRaised);
  assert.ok(secondaryRatio >= 4.5, `--sd-text-secondary itself must clear AA (got ${secondaryRatio.toFixed(2)}:1)`);

  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const selector of [
    '.sd-nav__kicker',
    '.sd-context__header-label',
    '.sd-context__section-label',
    '.sd-statusbar__label',
    '.sd-refined-card__eyebrow',
    '.sd-meta-cell__label',
    '.sd-timeline__day-label',
    '.sd-message-card__confidence-label',
    '.sd-panel-label',
    '.sd-studio-personas__title',
    '.sd-example-column__label',
    '.sd-stress-result__category',
    '.sd-message-rescue-column__label',
    '.sd-review-meta-cell__label',
  ]) {
    const escaped = selector.replace(/[.]/g, '\\.');
    const pattern = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`);
    const block = withoutComments.match(pattern);
    assert.ok(block, `expected a rule for \`${selector}\` (used ${selector === '.sd-panel-label' ? '27' : selector === '.sd-field__label' ? '39' : 'multiple'} times on signal-desk.html)`);
    assert.doesNotMatch(block[1], /color:\s*var\(--sd-text-muted\)/, `\`${selector}\` must not use --sd-text-muted for its label text`);
    assert.match(block[1], /color:\s*var\(--sd-text-secondary\)/, `\`${selector}\` should use --sd-text-secondary`);
  }
});

test('.sd-badge--error (reachable via talkWorkspace.js) meets WCAG AA on its own chip background', () => {
  const block = css.match(/\.sd-badge--error\s*\{([^}]*)\}/);
  assert.ok(block, 'expected a rule for `.sd-badge--error`');
  assert.match(
    block[1],
    /color:\s*var\(--sd-red-bright\)/,
    '--sd-red measures ~4.07:1 on this badge\'s own 14%-alpha chip background over --sd-surface-raised -- ' +
      'below AA for its 12px bold text (not "large text" under WCAG). --sd-red-bright was added for this.',
  );
  const redBright = tokenHex('sd-red-bright');
  const red = tokenHex('sd-red');
  const surfaceRaised = tokenHex('sd-surface-raised');
  const chipBg = compositeOver(red, 0.14, surfaceRaised);
  const ratio = contrastRatio(redBright, chipBg);
  assert.ok(
    ratio >= 4.5,
    `--sd-red-bright (${redBright}) on the composited chip background (${chipBg}) is ${ratio.toFixed(2)}:1, ` +
      'below 4.5:1',
  );
});

test('the two search-input placeholders fixed this wave no longer use --sd-text-muted', () => {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const selector of ['.sd-library-search__input::placeholder', '.sd-set-search__input::placeholder']) {
    const escaped = selector.replace(/[.:]/g, (c) => `\\${c}`);
    const pattern = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`);
    const block = withoutComments.match(pattern);
    assert.ok(block, `expected a rule for \`${selector}\``);
    assert.doesNotMatch(block[1], /color:\s*var\(--sd-text-muted\)/, `\`${selector}\` must not use --sd-text-muted`);
  }
});

test('a classless <textarea> gets the same "nobody styled this" floor as a classless <button>', () => {
  // #sdTestSampleInput (Studio's persona test panel, signal-desk.html) is the
  // only <textarea> on the page with no class at all -- everywhere else uses
  // .sd-input/.sd-input--area or a .sd-util-input/.sd-set-input family. Without
  // this rule it fell back to the UA's white textarea widget on this dark page,
  // the same failure mode `button:not([class])` already guards against.
  assert.match(
    html,
    /<textarea id="sdTestSampleInput"(?:(?!class=)[^>])*>/,
    'expected #sdTestSampleInput to still exist and remain classless on signal-desk.html -- if it now ' +
      'carries a class, this test (and the textarea:not([class]) rule it guards) can be deleted',
  );
  const block = css.match(/textarea:not\(\[class\]\)\s*\{([^}]*)\}/);
  assert.ok(block, 'expected a `textarea:not([class])` rule mirroring `button:not([class])`');
  assert.match(block[1], /background-color:\s*var\(--sd-surface-inset\)/);
  assert.match(block[1], /border:\s*1px solid var\(--sd-border\)/);
  assert.match(block[1], /color:\s*var\(--sd-text-primary\)/);
});

test('the shell\'s center and context grid tracks guard against forcing the page to overflow horizontally', () => {
  // CSS Grid items default to min-width: auto (their content's min-content
  // size), so unbreakable content deep inside .sd-center (1fr) or .sd-context
  // (320px, fixed) can force those tracks past the viewport and put a
  // horizontal scrollbar on the whole page at narrow window widths, instead
  // of the content wrapping or scrolling locally. This file already uses
  // `min-width: 0` for exactly this reason in ~15 other spots; the shell's
  // own two variable-content tracks were missing it.
  for (const selector of ['.sd-center', '.sd-context']) {
    const escaped = selector.replace(/[.]/g, '\\.');
    const pattern = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`);
    const block = css.match(pattern);
    assert.ok(block, `expected a rule for \`${selector}\``);
    assert.match(block[1], /min-width:\s*0/, `\`${selector}\` must set min-width: 0 to prevent forcing page-level horizontal overflow`);
  }
});

// --- the theme control must not offer what does not exist --------------------
//
// `settingsWorkspace.js`'s computeAppearanceClasses() puts a `theme-light`
// class on <body> for Light (and for System when the OS prefers light), but no
// stylesheet in the renderer defines a single `theme-light` rule. Selecting
// either option applied a class that styled nothing and left the app dark, so
// the control silently did nothing — the user's reasonable read is that their
// click did not register.
//
// This is the Linux-honesty rule of this wave applied to a theme: an
// affordance may not be presented as available when it is not. Pinned in both
// directions so it stays true whichever way the situation changes — build the
// light theme and the first assertion tells you to re-enable the options.

test('no light theme actually exists in the shipping stylesheet', () => {
  assert.equal(
    /\.theme-light\b/.test(css),
    false,
    'a `theme-light` rule now exists — if the light theme has been built, re-enable the '
      + '#sdSetTheme options and delete the honesty test below',
  );
});

test('#sdSetTheme does not offer themes that are not built', () => {
  const select = html.match(/<select[^>]*id="sdSetTheme"[^>]*>([\s\S]*?)<\/select>/);
  assert.ok(select, 'expected a #sdSetTheme select on the production page');
  const options = [...select[1].matchAll(/<option\s+value="([^"]+)"([^>]*)>([^<]*)</g)]
    .map(([, value, attrs, label]) => ({ value, disabled: /\bdisabled\b/.test(attrs), label: label.trim() }));

  const byValue = Object.fromEntries(options.map((o) => [o.value, o]));
  assert.ok(byValue.dark && !byValue.dark.disabled, 'Dark is the theme that ships and must stay selectable');

  for (const value of ['light', 'system']) {
    assert.ok(byValue[value], `expected the ${value} option to remain present rather than be hidden`);
    assert.equal(
      byValue[value].disabled,
      true,
      `#sdSetTheme's "${value}" option must be disabled while no light theme exists — `
        + 'a control that silently does nothing is worse than one that says it cannot',
    );
    assert.match(
      byValue[value].label,
      /not built yet/i,
      `the ${value} option must say WHY it is unavailable, not just be greyed out`,
    );
  }
});

test('the theme row explains what is available rather than leaving a dead control unexplained', () => {
  assert.match(html, /id="sdSetThemeNote"/, 'expected an availability note beside #sdSetTheme');
  const note = css.match(/\.sd-set-row__note\s*\{([^}]*)\}/);
  assert.ok(note, 'expected a `.sd-set-row__note` rule so the note is styled rather than raw text');
  // --sd-text-muted measures 3.20:1 against these surfaces, below the 4.5:1
  // body-text bar; the note must not be written in it.
  assert.equal(
    /--sd-text-muted/.test(note[1]),
    false,
    'the note must not use --sd-text-muted, which fails AA contrast on these surfaces',
  );
});
