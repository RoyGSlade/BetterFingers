// The Voice Studio modulation sliders' RANGES are a contract, not styling.
//
// Found during the Wave 12 anchor audit (docs/release/DECISIONS.md D-0034):
// signal-desk.html declared energy/warmth/brightness as `min=0 max=100 step=1
// value=50` while every other layer of the stack treats them as 0..1 floats.
// That broke the production page in both directions:
//
//   * LOADING  -- setModulationControls() sets `el.value = 0.5` on an integer
//     0..100 range, so the browser snaps the thumb to the bottom and the user
//     sees a saved setting as "off".
//   * SAVING   -- gatherVoiceStudioSettingsFromInputs() reads the raw slider
//     value back, persisting `review_tts_energy: 50` -- fifty times its
//     maximum legal value, straight into the profile.
//
// The legacy page always had these right (index.html: min=0 max=1 step=0.05),
// so this was a transcription error when the control was rebuilt for Signal
// Desk, not a deliberate change. It is pinned here because it is invisible to
// every other kind of test: the markup renders perfectly, the JS runs without
// error, and the corruption only shows up in the persisted value.
//
// Run with: node --test app/tests/voiceStudioModulationContract.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  gatherVoiceStudioSettingsFromInputs,
  buildPersistableVoiceStudioSettings,
} from '../src/renderer/features/voiceStudio.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = readFileSync(join(HERE, '..', 'src', 'renderer', 'signal-desk.html'), 'utf8');

/** The `<input …>` tag declaring `id`, as written on the shipping page. */
function inputTag(id) {
  const match = PAGE.match(new RegExp(`<input[^>]*id="${id}"[^>]*>`));
  assert.ok(match, `signal-desk.html must declare an input#${id}`);
  return match[0];
}

function attr(tag, name) {
  const match = tag.match(new RegExp(`${name}="([^"]*)"`));
  return match ? match[1] : null;
}

// energy/warmth/brightness are the three that were wrong. Pitch is separate:
// it is a semitone offset, legitimately -12..12.
const UNIT_INTERVAL_SLIDERS = ['voiceEnergy', 'voiceWarmth', 'voiceBrightness'];

test('the 0..1 modulation sliders declare a 0..1 range, not 0..100', () => {
  for (const id of UNIT_INTERVAL_SLIDERS) {
    const tag = inputTag(id);
    assert.equal(attr(tag, 'min'), '0', `${id} min`);
    assert.equal(attr(tag, 'max'), '1', `${id} max -- a 0..100 range persists values 100x out of contract`);
    // A step of 1 on a 0..1 range would collapse the control to a two-position
    // switch, which is the same class of bug in a different disguise.
    assert.ok(Number(attr(tag, 'step')) <= 0.05, `${id} step must be fine-grained, saw ${attr(tag, 'step')}`);
  }
});

test('every modulation slider default is inside its own declared range', () => {
  for (const id of [...UNIT_INTERVAL_SLIDERS, 'voicePitch']) {
    const tag = inputTag(id);
    const value = Number(attr(tag, 'value'));
    const min = Number(attr(tag, 'min'));
    const max = Number(attr(tag, 'max'));
    assert.ok(value >= min && value <= max, `${id} default ${value} is outside [${min}, ${max}]`);
  }
});

test('the page defaults match what the JS falls back to, so an untouched form saves what it displays', () => {
  // gatherVoiceStudioSettingsFromInputs()'s documented fallbacks: energy 0.5,
  // warmth 0, brightness 0, pitch 0. If the markup disagreed, merely opening
  // Voice Studio and pressing save would silently change the user's settings.
  const fallback = gatherVoiceStudioSettingsFromInputs({});
  const shown = {
    pitch: Number(attr(inputTag('voicePitch'), 'value')),
    energy: Number(attr(inputTag('voiceEnergy'), 'value')),
    warmth: Number(attr(inputTag('voiceWarmth'), 'value')),
    brightness: Number(attr(inputTag('voiceBrightness'), 'value')),
  };
  for (const key of Object.keys(shown)) {
    assert.equal(shown[key], fallback[key], `${key}: the page shows ${shown[key]} but the JS default is ${fallback[key]}`);
  }
});

test('a round trip through the persistence helpers stays inside the contract', () => {
  // The concrete corruption: a slider reading "50" persisted as review_tts_energy.
  const fromBrokenSlider = buildPersistableVoiceStudioSettings({
    blendLayers: [], pitch: 0, energy: 50, warmth: 50, brightness: 50, pauseStyle: 'natural',
  });
  assert.equal(fromBrokenSlider.review_tts_energy, 50);
  assert.ok(
    fromBrokenSlider.review_tts_energy > 1,
    'sanity: this is the out-of-contract value the old 0..100 markup produced, '
      + 'recorded so the range assertions above are understood as the thing preventing it',
  );

  // What the corrected markup produces instead.
  const fromFixedSlider = buildPersistableVoiceStudioSettings({
    blendLayers: [], pitch: 0, energy: 0.5, warmth: 0, brightness: 0, pauseStyle: 'natural',
  });
  for (const key of ['review_tts_energy', 'review_tts_warmth', 'review_tts_brightness']) {
    assert.ok(fromFixedSlider[key] >= 0 && fromFixedSlider[key] <= 1, `${key} = ${fromFixedSlider[key]} is outside 0..1`);
  }
});

test('every modulation slider has the live value read-out its label updater needs', () => {
  // voiceStudio.js's updateModulationLabels() pairs each input with a label id
  // and no-ops when the label is absent -- so a missing span is not a cosmetic
  // gap, it silently disables the numeric feedback for that control. All four
  // were missing from this page.
  for (const id of ['voicePitchValue', 'voiceEnergyValue', 'voiceWarmthValue', 'voiceBrightnessValue']) {
    assert.match(PAGE, new RegExp(`id="${id}"`), `signal-desk.html must carry #${id} for updateModulationLabels()`);
  }
});
