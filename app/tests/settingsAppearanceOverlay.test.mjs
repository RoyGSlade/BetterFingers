// Settings -> Appearance: the five client-local look controls and the
// Floating Overlay group, driven through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md section 7.11 (parity rows UI-07-151 … UI-07-156,
// UI-07-159, UI-07-160, UI-07-161, UI-07-163). settingsWorkspace.test.mjs
// covers computeAppearanceClasses/normalizeAppearancePrefs as pure functions;
// what had never been executed is the part that makes them a feature -- the
// change listeners, the localStorage persistence, the live class application
// and the overlay bridge push. Those only exist inside
// createSettingsWorkspaceFeature(), and reaching them needs a document.
//
// The overlay group talks to the Electron main process through
// window.betterFingers.{get,set}OverlayAppearance, so it is stubbed at that
// bridge and every push is recorded -- the same shape the preload exposes.
//
// Run with: node --test app/tests/settingsAppearanceOverlay.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SETTINGS_ELEMENT_IDS,
  collectSettingsElements,
  createSettingsWorkspaceFeature,
} from '../src/renderer/features/settingsWorkspace.js';
import { makeDocument, makeLocalStorage, installDomGlobals } from './helpers/rendererDom.mjs';

const APPEARANCE_IDS = {
  theme: 'sdSetTheme',
  accentColor: 'sdSetAccentColor',
  density: 'sdSetDensity',
  fontSize: 'sdSetFontSize',
  highContrast: 'sdSetHighContrast',
};

const OVERLAY_IDS = {
  overlayGroup: 'sdSetOverlayAppearanceGroup',
  overlaySize: 'sdSetOverlaySize',
  overlayPlacement: 'sdSetOverlayPlacement',
  overlayOpacity: 'sdSetOverlayOpacity',
  overlayOpacityValue: 'sdSetOverlayOpacityValue',
  overlayVibrancy: 'sdSetOverlayVibrancy',
  overlayVibrancyValue: 'sdSetOverlayVibrancyValue',
  overlayLabelPos: 'sdSetOverlayLabelPos',
  overlayAlwaysOn: 'sdSetOverlayAlwaysOn',
};

test('the appearance and overlay ids this file drives are the ids the module ships', () => {
  for (const [key, id] of Object.entries({ ...APPEARANCE_IDS, ...OVERLAY_IDS })) {
    assert.equal(SETTINGS_ELEMENT_IDS[key], id, `${key} is not ${id} any more`);
  }
});

function mount({ prefs = {}, appearance, prefersDark = false } = {}) {
  const doc = makeDocument([...Object.values(APPEARANCE_IDS), ...Object.values(OVERLAY_IDS)], {
    sdSetTheme: { tagName: 'select' },
    sdSetAccentColor: { tagName: 'select' },
    sdSetDensity: { tagName: 'select' },
    sdSetFontSize: { tagName: 'select' },
    sdSetHighContrast: { tagName: 'input', type: 'checkbox' },
    sdSetOverlaySize: { tagName: 'select' },
    sdSetOverlayPlacement: { tagName: 'select' },
    sdSetOverlayOpacity: { tagName: 'input', type: 'range' },
    sdSetOverlayVibrancy: { tagName: 'input', type: 'range' },
    sdSetOverlayLabelPos: { tagName: 'select' },
    sdSetOverlayAlwaysOn: { tagName: 'input', type: 'checkbox' },
  });
  const storage = makeLocalStorage(prefs);
  const pushes = [];
  const overlayBridge = appearance === null ? {} : {
    getOverlayAppearance: async () => appearance,
    setOverlayAppearance: async (patch) => { pushes.push(patch); return { ok: true }; },
  };
  const restore = installDomGlobals({ document: doc, betterFingers: overlayBridge, prefersDark, storage });
  const feature = createSettingsWorkspaceFeature({
    elements: collectSettingsElements(doc),
    hooks: { overlayBridge },
  });
  return { doc, feature, restore, storage, pushes, el: (id) => doc.getElementById(id) };
}

// --- UI-07-151 … UI-07-156: the five look controls ---------------------------

test('init() runs applyAppearance(), which paints the body/html classes and back-fills the five controls', async (t) => {
  const ctx = mount({ prefs: { pref_theme: 'dark', pref_accent: 'purple', pref_density: 'compact', pref_font_size: 'large', pref_high_contrast: 'true' } });
  t.after(ctx.restore);

  ctx.feature.init();

  assert.equal(ctx.doc.body.classList.contains('theme-dark'), true);
  assert.equal(ctx.doc.body.classList.contains('accent-purple'), true);
  assert.equal(ctx.doc.body.classList.contains('density-compact'), true);
  assert.equal(ctx.doc.body.classList.contains('high-contrast'), true);
  assert.equal(ctx.doc.documentElement.className, 'font-large');

  assert.equal(ctx.el('sdSetTheme').value, 'dark');
  assert.equal(ctx.el('sdSetAccentColor').value, 'purple');
  assert.equal(ctx.el('sdSetDensity').value, 'compact');
  assert.equal(ctx.el('sdSetFontSize').value, 'large');
  assert.equal(ctx.el('sdSetHighContrast').checked, true);
});

test('#sdSetTheme persists to pref_theme and re-applies live, without any profile save', async (t) => {
  const ctx = mount({ prefs: { pref_theme: 'light' } });
  t.after(ctx.restore);
  ctx.feature.init();
  assert.equal(ctx.doc.body.classList.contains('theme-light'), true);

  const theme = ctx.el('sdSetTheme');
  assert.ok(theme.listenerCount('change') > 0, 'the theme select was never bound');
  theme.value = 'dark';
  theme.emit('change');

  assert.equal(ctx.storage.getItem('pref_theme'), 'dark');
  assert.equal(ctx.doc.body.classList.contains('theme-dark'), true);
  assert.equal(ctx.doc.body.classList.contains('theme-light'), false, 'the stale theme class must be removed, not just overlaid');
});

test('#sdSetAccentColor, #sdSetDensity and #sdSetFontSize each persist their own key and repaint', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  const accent = ctx.el('sdSetAccentColor');
  accent.value = 'gold';
  accent.emit('change');
  assert.equal(ctx.storage.getItem('pref_accent'), 'gold');
  assert.equal(ctx.doc.body.classList.contains('accent-gold'), true);

  const density = ctx.el('sdSetDensity');
  density.value = 'compact';
  density.emit('change');
  assert.equal(ctx.storage.getItem('pref_density'), 'compact');
  assert.equal(ctx.doc.body.classList.contains('density-compact'), true);

  const fontSize = ctx.el('sdSetFontSize');
  fontSize.value = 'huge';
  fontSize.emit('change');
  assert.equal(ctx.storage.getItem('pref_font_size'), 'huge');
  assert.equal(ctx.doc.documentElement.className, 'font-huge');
});

test('#sdSetHighContrast writes the string "true"/"false" the reader expects, both ways', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  const highContrast = ctx.el('sdSetHighContrast');
  highContrast.checked = true;
  highContrast.emit('change');
  assert.equal(ctx.storage.getItem('pref_high_contrast'), 'true');
  assert.equal(ctx.doc.body.classList.contains('high-contrast'), true);

  highContrast.checked = false;
  highContrast.emit('change');
  assert.equal(ctx.storage.getItem('pref_high_contrast'), 'false');
  assert.equal(ctx.doc.body.classList.contains('high-contrast'), false);
});

test('an unset or invalid stored preference falls back to a documented default rather than an empty class', async (t) => {
  const ctx = mount({ prefs: { pref_theme: 'neon', pref_accent: 'chartreuse' } });
  t.after(ctx.restore);
  ctx.feature.init();

  assert.equal(ctx.el('sdSetTheme').value, 'system');
  assert.equal(ctx.el('sdSetAccentColor').value, 'teal');
  // applyAppearance() normalises on the way out too, so the bad value cannot
  // survive in storage to be re-read next launch.
  assert.equal(ctx.storage.getItem('pref_theme'), 'system');
  assert.equal(ctx.storage.getItem('pref_accent'), 'teal');
});

test('theme "system" resolves from the OS preference at apply time', async (t) => {
  const ctx = mount({ prefs: { pref_theme: 'system' }, prefersDark: true });
  t.after(ctx.restore);
  ctx.feature.init();
  assert.equal(ctx.doc.body.classList.contains('theme-dark'), true);
  ctx.restore();

  const light = mount({ prefs: { pref_theme: 'system' }, prefersDark: false });
  t.after(light.restore);
  light.feature.init();
  assert.equal(light.doc.body.classList.contains('theme-light'), true);
});

// --- UI-07-159 … UI-07-163: the Floating Overlay group -----------------------

const APPEARANCE_PAYLOAD = {
  size: 'large', placement: 'top-left', opacity: 0.5, vibrancy: 1.5, labelPos: 'below', alwaysOn: true,
};

test('the overlay group is populated from the main process, including both live percent readouts', async (t) => {
  const ctx = mount({ appearance: APPEARANCE_PAYLOAD });
  t.after(ctx.restore);
  ctx.feature.init();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('sdSetOverlayPlacement').value, 'top-left');
  assert.equal(ctx.el('sdSetOverlayOpacity').value, '0.5');
  assert.equal(ctx.el('sdSetOverlayOpacityValue').textContent, '50%');
  assert.equal(ctx.el('sdSetOverlayVibrancy').value, '1.5');
  assert.equal(ctx.el('sdSetOverlayVibrancyValue').textContent, '150%');
  assert.equal(ctx.el('sdSetOverlayAlwaysOn').checked, true);
});

test('#sdSetOverlayPlacement pushes the new placement to the overlay window', async (t) => {
  const ctx = mount({ appearance: APPEARANCE_PAYLOAD });
  t.after(ctx.restore);
  ctx.feature.init();
  await new Promise((resolve) => setImmediate(resolve));

  const placement = ctx.el('sdSetOverlayPlacement');
  assert.ok(placement.listenerCount('change') > 0, 'the placement select was never bound');
  placement.value = 'center';
  placement.emit('change');
  assert.deepEqual(ctx.pushes, [{ placement: 'center' }]);
});

test('#sdSetOverlayOpacity updates #sdSetOverlayOpacityValue while dragging and only pushes on commit', async (t) => {
  const ctx = mount({ appearance: APPEARANCE_PAYLOAD });
  t.after(ctx.restore);
  ctx.feature.init();
  await new Promise((resolve) => setImmediate(resolve));

  const opacity = ctx.el('sdSetOverlayOpacity');
  opacity.value = '0.35';
  opacity.emit('input');
  assert.equal(ctx.el('sdSetOverlayOpacityValue').textContent, '35%', 'the readout must track the drag');
  assert.deepEqual(ctx.pushes, [], 'dragging must not spam the main process');

  opacity.emit('change');
  assert.deepEqual(ctx.pushes, [{ opacity: 0.35 }]);
  assert.equal(typeof ctx.pushes[0].opacity, 'number', 'the range value is a string; the bridge must get a number');
});

test('#sdSetOverlayVibrancy behaves the same way, with its own readout', async (t) => {
  const ctx = mount({ appearance: APPEARANCE_PAYLOAD });
  t.after(ctx.restore);
  ctx.feature.init();
  await new Promise((resolve) => setImmediate(resolve));

  const vibrancy = ctx.el('sdSetOverlayVibrancy');
  vibrancy.value = '0.75';
  vibrancy.emit('input');
  assert.equal(ctx.el('sdSetOverlayVibrancyValue').textContent, '75%');
  assert.deepEqual(ctx.pushes, []);

  vibrancy.emit('change');
  assert.deepEqual(ctx.pushes, [{ vibrancy: 0.75 }]);
});

test('#sdSetOverlayAlwaysOn pushes the boolean both ways', async (t) => {
  const ctx = mount({ appearance: APPEARANCE_PAYLOAD });
  t.after(ctx.restore);
  ctx.feature.init();
  await new Promise((resolve) => setImmediate(resolve));

  const alwaysOn = ctx.el('sdSetOverlayAlwaysOn');
  alwaysOn.checked = false;
  alwaysOn.emit('change');
  alwaysOn.checked = true;
  alwaysOn.emit('change');
  assert.deepEqual(ctx.pushes, [{ alwaysOn: false }, { alwaysOn: true }]);
});

test('with no overlay bridge the whole group is hidden rather than left as dead controls', async (t) => {
  const ctx = mount({ appearance: null });
  t.after(ctx.restore);
  ctx.feature.init();

  assert.equal(ctx.el('sdSetOverlayAppearanceGroup').style.display, 'none');
  assert.equal(ctx.el('sdSetOverlayPlacement').listenerCount('change'), 0, 'an unreachable control must not look interactive');
});
