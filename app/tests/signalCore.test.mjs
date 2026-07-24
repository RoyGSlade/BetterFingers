// Unit tests for the Signal Core ring's PURE geometry/mapping helpers
// (docs/ui/SIGNAL_DESK_SPEC.md section 4/7). Canvas drawing itself is not
// exercised here (no jsdom/canvas in this repo's test setup -- see
// signalDeskShell.test.mjs's header note); createSignalCore() itself is only
// smoke-tested for its documented no-op-when-no-canvas fallback.
//
// Run with: node --test app/tests/signalCore.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SIGNAL_CORE_STATES,
  SIGNAL_CORE_STATE_ALIASES,
  SIGNAL_CORE_STATE_TOKENS,
  resolveSignalCoreState,
  stateToColorTokens,
  computeSegmentAngles,
  amplitudeToBarHeight,
  waveformEnvelope,
  computeWaveformBarHeights,
  computeParticlePositions,
  DEFAULT_OPTIONS,
  createSignalCore,
} from '../src/renderer/signalCore.js';

const TAU = Math.PI * 2;

// --- resolveSignalCoreState / stateToColorTokens ----------------------------

test('resolveSignalCoreState: known states resolve to themselves', () => {
  for (const state of SIGNAL_CORE_STATES) {
    assert.equal(resolveSignalCoreState(state), state);
  }
});

test('resolveSignalCoreState: aliases resolve to their canonical state', () => {
  for (const [alias, canonical] of Object.entries(SIGNAL_CORE_STATE_ALIASES)) {
    assert.equal(resolveSignalCoreState(alias), canonical);
  }
});

test('resolveSignalCoreState: unknown/missing input falls back to idle', () => {
  assert.equal(resolveSignalCoreState('totally-unknown'), 'idle');
  assert.equal(resolveSignalCoreState(undefined), 'idle');
  assert.equal(resolveSignalCoreState(null), 'idle');
  assert.equal(resolveSignalCoreState(''), 'idle');
});

test('stateToColorTokens: listening/recording rings stay cyan/teal (green is only the status dot)', () => {
  // Director QA correction vs mockups 01/04: the concentric rings are a cohesive
  // cyan/teal HUD in every capture state; green does NOT belong in the rings.
  const listening = stateToColorTokens('listening');
  assert.equal(listening.state, 'listening');
  assert.equal(listening.primaryToken, 'cyan');
  assert.equal(listening.secondaryToken, 'teal');

  const recording = stateToColorTokens('recording');
  assert.equal(recording.state, 'recording');
  assert.equal(recording.primaryToken, 'cyan');
  assert.equal(recording.secondaryToken, 'teal');

  const error = stateToColorTokens('error');
  assert.equal(error.primaryToken, 'red');

  const ready = stateToColorTokens('sent'); // alias
  assert.equal(ready.state, 'ready');
  assert.equal(ready.primaryToken, 'green');
});

test('stateToColorTokens: every state table entry has a token pair and finite baseAmplitude', () => {
  for (const state of SIGNAL_CORE_STATES) {
    const tokens = SIGNAL_CORE_STATE_TOKENS[state];
    assert.ok(tokens, `missing token entry for ${state}`);
    assert.equal(typeof tokens.primaryToken, 'string');
    assert.equal(typeof tokens.secondaryToken, 'string');
    assert.ok(Number.isFinite(tokens.baseAmplitude));
    assert.ok(tokens.baseAmplitude >= 0 && tokens.baseAmplitude <= 1);
  }
});

// --- computeSegmentAngles ----------------------------------------------------

test('computeSegmentAngles: returns `count` segments, each with positive arc length', () => {
  const segments = computeSegmentAngles(12, 0.4);
  assert.equal(segments.length, 12);
  for (const { start, end } of segments) {
    assert.ok(end > start);
  }
});

test('computeSegmentAngles: segments are evenly spaced and non-overlapping', () => {
  const count = 8;
  const segments = computeSegmentAngles(count, 0.3);
  const slot = TAU / count;
  segments.forEach((seg, i) => {
    const arcLen = seg.end - seg.start;
    assert.ok(Math.abs(arcLen - slot * 0.7) < 1e-9, `segment ${i} arc length`);
    // Each segment must stay within its own slot [i*slot, (i+1)*slot].
    assert.ok(seg.start >= i * slot - 1e-9);
    assert.ok(seg.end <= (i + 1) * slot + 1e-9);
  });
  // No overlap between consecutive segments.
  for (let i = 1; i < segments.length; i++) {
    assert.ok(segments[i].start >= segments[i - 1].end);
  }
});

test('computeSegmentAngles: gapRatio=0 produces contiguous segments covering the full circle', () => {
  const segments = computeSegmentAngles(6, 0);
  assert.equal(segments[0].start, 0);
  for (let i = 1; i < segments.length; i++) {
    assert.ok(Math.abs(segments[i].start - segments[i - 1].end) < 1e-9);
  }
  assert.ok(Math.abs(segments[segments.length - 1].end - TAU) < 1e-9);
});

test('computeSegmentAngles: count <= 0 or non-finite returns an empty array', () => {
  assert.deepEqual(computeSegmentAngles(0), []);
  assert.deepEqual(computeSegmentAngles(-4), []);
  assert.deepEqual(computeSegmentAngles(NaN), []);
});

test('computeSegmentAngles: gapRatio is clamped to [0, 0.95]', () => {
  const overGapped = computeSegmentAngles(4, 5);
  const fullyGapped = computeSegmentAngles(4, 0.95);
  assert.deepEqual(
    overGapped.map((s) => s.end - s.start),
    fullyGapped.map((s) => s.end - s.start),
  );
});

// --- amplitudeToBarHeight -----------------------------------------------------

test('amplitudeToBarHeight: maps 0..1 onto [minHeight, maxHeight]', () => {
  assert.equal(amplitudeToBarHeight(0, 2, 10), 2);
  assert.equal(amplitudeToBarHeight(1, 2, 10), 10);
  assert.equal(amplitudeToBarHeight(0.5, 0, 1), 0.5);
});

test('amplitudeToBarHeight: clamps out-of-range amplitude', () => {
  assert.equal(amplitudeToBarHeight(-3, 0, 1), 0);
  assert.equal(amplitudeToBarHeight(4, 0, 1), 1);
});

test('amplitudeToBarHeight: treats non-finite amplitude as 0', () => {
  assert.equal(amplitudeToBarHeight(NaN, 1, 5), 1);
  assert.equal(amplitudeToBarHeight(undefined, 1, 5), 1);
});

test('amplitudeToBarHeight: default range is 0..1', () => {
  assert.equal(amplitudeToBarHeight(0.25), 0.25);
});

// --- waveformEnvelope / computeWaveformBarHeights -----------------------------

test('waveformEnvelope: 0 at both edges, 1 at the exact center', () => {
  assert.ok(Math.abs(waveformEnvelope(0) - 0) < 1e-9);
  assert.ok(Math.abs(waveformEnvelope(1) - 0) < 1e-9);
  assert.ok(Math.abs(waveformEnvelope(0.5) - 1) < 1e-9);
});

test('waveformEnvelope: symmetric around the center', () => {
  assert.ok(Math.abs(waveformEnvelope(0.25) - waveformEnvelope(0.75)) < 1e-9);
  assert.ok(Math.abs(waveformEnvelope(0.1) - waveformEnvelope(0.9)) < 1e-9);
});

test('computeWaveformBarHeights: returns `count` heights, tapering to ~0 at the edges', () => {
  const heights = computeWaveformBarHeights(9, 1, 0);
  assert.equal(heights.length, 9);
  assert.ok(heights[0] < 1e-9);
  assert.ok(heights[heights.length - 1] < 1e-9);
  // The middle bar should be far larger than the edge bars.
  const mid = heights[Math.floor(heights.length / 2)];
  assert.ok(mid > heights[0]);
  assert.ok(mid > heights[heights.length - 1]);
});

test('computeWaveformBarHeights: every height is non-negative and bounded by maxHeight', () => {
  const heights = computeWaveformBarHeights(32, 1, 2.7, { minHeight: 0.04, maxHeight: 1 });
  for (const h of heights) {
    assert.ok(h >= 0);
    assert.ok(h <= 1.0001);
  }
});

test('computeWaveformBarHeights: deterministic for a fixed phase (reproducible in tests)', () => {
  const a = computeWaveformBarHeights(16, 0.6, 1.23);
  const b = computeWaveformBarHeights(16, 0.6, 1.23);
  assert.deepEqual(a, b);
});

test('computeWaveformBarHeights: count <= 0 returns an empty array', () => {
  assert.deepEqual(computeWaveformBarHeights(0, 1, 0), []);
});

// --- computeParticlePositions -------------------------------------------------

test('computeParticlePositions: returns `count` points within the given radius annulus', () => {
  const points = computeParticlePositions(30, 0.3, 0.9);
  assert.equal(points.length, 30);
  for (const p of points) {
    assert.ok(p.radiusRatio >= 0.3 - 1e-9 && p.radiusRatio <= 0.9 + 1e-9);
    assert.ok(p.angle >= 0 && p.angle < TAU);
  }
});

test('computeParticlePositions: count <= 0 returns an empty array', () => {
  assert.deepEqual(computeParticlePositions(0), []);
});

// --- DEFAULT_OPTIONS shape (director-tunable geometry) ------------------------

test('DEFAULT_OPTIONS: exposes the documented geometry knobs', () => {
  assert.ok(Number.isFinite(DEFAULT_OPTIONS.sizePx));
  assert.ok(Array.isArray(DEFAULT_OPTIONS.segmentedRings));
  assert.ok(DEFAULT_OPTIONS.segmentedRings.length >= 2);
  for (const ring of DEFAULT_OPTIONS.segmentedRings) {
    assert.ok(Number.isFinite(ring.radiusRatio));
    assert.ok(Number.isFinite(ring.segmentCount));
    assert.ok(Number.isFinite(ring.gapRatio));
  }
  assert.ok(Number.isFinite(DEFAULT_OPTIONS.waveform.barCount));
  assert.ok(Number.isFinite(DEFAULT_OPTIONS.particles.count));
});

// --- createSignalCore: no-op fallback when there's no usable canvas ----------

test('createSignalCore: returns a safe no-op API when given neither canvas nor container', () => {
  const ring = createSignalCore({});
  assert.equal(typeof ring.setState, 'function');
  assert.equal(typeof ring.setAmplitude, 'function');
  assert.equal(typeof ring.destroy, 'function');
  assert.doesNotThrow(() => {
    ring.setState('recording');
    ring.setAmplitude(0.5);
    ring.setOptions({ waveform: { barCount: 10 } });
    ring.destroy();
  });
  assert.equal(ring.getOptions(), null);
  assert.equal(ring.getState(), 'idle');
});

test('createSignalCore: returns a safe no-op API when the canvas has no getContext', () => {
  const ring = createSignalCore({ canvas: {} });
  assert.equal(typeof ring.destroy, 'function');
  assert.doesNotThrow(() => ring.destroy());
});
