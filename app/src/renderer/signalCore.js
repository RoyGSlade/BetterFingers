// signalCore.js — the "Signal Core" ring: BetterFingers' Signal Desk hero
// visualization (docs/ui/SIGNAL_DESK_SPEC.md section 4 + 7, mockups
// 01_talk_workspace.png / 04_overlay_review_deck.png).
//
// A canvas-drawn concentric-ring HUD: a faint outer ring, several radii of
// segmented cyan tech arcs (varying brightness, some "active"), a centered
// live waveform, and a subtle particle/dust field. Deliberately distinct
// from glitch-ring.js (the compact overlay status ring) but follows the same
// approach: a pure `state` + optional external `amplitude` drive the motion,
// resize is DPR-aware and observer-driven, and the whole thing tears down
// cleanly via destroy().
//
// Usage:
//   import { createSignalCore } from './signalCore.js';
//   const ring = createSignalCore({ container: mountEl, state: 'listening' });
//   // -- or, if the caller already owns a <canvas>:
//   const ring = createSignalCore({ canvas: canvasEl });
//   ring.setState('recording');
//   ring.setAmplitude(0.6);        // optional, 0..1
//   ring.setOptions({ waveform: { barCount: 48 } }); // live geometry tuning
//   ring.destroy();
//
// Every geometry number below is a *default* the director can override via
// `options` / `setOptions()` -- see DEFAULT_OPTIONS. Where SIGNAL_DESK_SPEC.md
// didn't give an exact figure (segment counts, particle density, exact
// radii ratios, etc.) a reasoned default was chosen from the mockups; these
// are the first things to tune from director screenshot feedback.

const TAU = Math.PI * 2;

// --- Pure geometry / mapping helpers (no DOM, no canvas -- unit tested in
// app/tests/signalCore.test.mjs) -----------------------------------------

/** The Signal Core's known states (mirrors glitch-ring's vocabulary). */
export const SIGNAL_CORE_STATES = ['idle', 'listening', 'recording', 'transcribing', 'ready', 'error'];

// Aliases so callers can pass the app's IPC/voice-status vocabulary directly
// (same alias set glitch-ring.js / overlay.html's interpret() use).
export const SIGNAL_CORE_STATE_ALIASES = {
  rewriting: 'transcribing',
  processing: 'transcribing',
  chunking: 'transcribing',
  stitching: 'transcribing',
  blocked: 'error',
  sent: 'ready',
  success: 'ready',
  danger: 'error',
  warning: 'error',
};

// Per-state color tokens (token NAMES, not hex -- resolved against the
// signal-desk.css --sd-* custom properties at draw time so no raw hex lives
// in this module's state table). `baseAmplitude` is the synthetic
// "breathing" level used when no external amplitude is supplied;
// `activeBoost` raises the fraction of "active" (bright) tech-ring segments.
// Per SPEC 4/7: listening & recording read as "cyan-green active".
export const SIGNAL_CORE_STATE_TOKENS = {
  idle: { primaryToken: 'cyan', secondaryToken: 'teal', baseAmplitude: 0.05, activeBoost: 0 },
  listening: { primaryToken: 'cyan', secondaryToken: 'green', baseAmplitude: 0.18, activeBoost: 0.15 },
  recording: { primaryToken: 'green', secondaryToken: 'cyan', baseAmplitude: 0.32, activeBoost: 0.3 },
  transcribing: { primaryToken: 'amber', secondaryToken: 'cyan', baseAmplitude: 0.24, activeBoost: 0.1 },
  ready: { primaryToken: 'green', secondaryToken: 'teal', baseAmplitude: 0.2, activeBoost: 0.05 },
  error: { primaryToken: 'red', secondaryToken: 'amber', baseAmplitude: 0.28, activeBoost: 0.2 },
};

/** Resolve an arbitrary status/state name to one of SIGNAL_CORE_STATES. Unknown names fall back to 'idle'. */
export function resolveSignalCoreState(name) {
  if (SIGNAL_CORE_STATE_TOKENS[name]) return name;
  if (SIGNAL_CORE_STATE_ALIASES[name]) return SIGNAL_CORE_STATE_ALIASES[name];
  return 'idle';
}

/** state name -> color-token descriptor (see SIGNAL_CORE_STATE_TOKENS). Never throws on unknown input. */
export function stateToColorTokens(name) {
  const resolved = resolveSignalCoreState(name);
  return { state: resolved, ...SIGNAL_CORE_STATE_TOKENS[resolved] };
}

/**
 * Evenly divide a circle into `count` segments with a gap between each,
 * for the segmented "tech ring" HUD look. Pure angle math: no randomness,
 * no canvas. Angles are radians, 0 = +X axis, increasing clockwise (canvas
 * convention). `gapRatio` (0..~0.95) is the fraction of each segment's
 * angular slot left empty as a gap.
 *
 * @returns {{start:number, end:number}[]} length `count` (or [] if count <= 0)
 */
export function computeSegmentAngles(count, gapRatio = 0.4) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (n <= 0) return [];
  const g = Math.min(0.95, Math.max(0, Number(gapRatio) || 0));
  const slot = TAU / n;
  const arc = slot * (1 - g);
  const pad = (slot - arc) / 2;
  const segments = [];
  for (let i = 0; i < n; i++) {
    const slotStart = i * slot;
    segments.push({ start: slotStart + pad, end: slotStart + pad + arc });
  }
  return segments;
}

/** Clamp `amplitude` to 0..1 (NaN/undefined treated as 0) and map it onto [minHeight, maxHeight]. */
export function amplitudeToBarHeight(amplitude, minHeight = 0, maxHeight = 1) {
  const a = Number.isFinite(amplitude) ? amplitude : 0;
  const clamped = Math.max(0, Math.min(1, a));
  return minHeight + clamped * (maxHeight - minHeight);
}

/** Symmetric taper envelope for the centered waveform: 0 at the edges (fx=0/1), 1 at the center (fx=0.5). */
export function waveformEnvelope(fx) {
  const x = Math.max(0, Math.min(1, Number(fx) || 0));
  return Math.sin(x * Math.PI);
}

/**
 * Normalized (0..~1) bar heights for the centered live waveform. Deterministic
 * given (count, amplitude, phase) -- no Math.random -- so a fixed phase is
 * reproducible in tests. `phase` is intended to be the animation clock (seconds).
 */
export function computeWaveformBarHeights(count, amplitude, phase = 0, { minHeight = 0.04, maxHeight = 1 } = {}) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (n <= 0) return [];
  const amp = amplitudeToBarHeight(amplitude, minHeight, maxHeight);
  const p = Number(phase) || 0;
  const heights = new Array(n);
  for (let i = 0; i < n; i++) {
    const fx = n === 1 ? 0.5 : i / (n - 1);
    const env = waveformEnvelope(fx);
    // Deterministic per-bar "wobble" from index + phase (electric/organic look
    // without relying on randomness), kept in [0.7, 1.0] so it never zeroes a bar.
    const wobble = 0.85 + 0.15 * Math.sin(i * 12.9898 + p * 3.1);
    heights[i] = Math.max(0, env * amp * wobble);
  }
  return heights;
}

/**
 * Deterministic scatter of `count` points in the annulus between
 * innerRadiusRatio and outerRadiusRatio (fractions of the ring's outer
 * radius), used for the faint particle/dust field. Uses the golden angle for
 * an even, non-clumpy spread with no RNG (reproducible in tests).
 */
export function computeParticlePositions(count, innerRadiusRatio = 0.3, outerRadiusRatio = 0.92) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (n <= 0) return [];
  const goldenAngle = Math.PI * (3 - Math.sqrt(5)); // ~2.39996 rad
  const points = new Array(n);
  for (let i = 0; i < n; i++) {
    const frac = n <= 1 ? 0.5 : i / (n - 1);
    const radiusRatio = innerRadiusRatio + frac * (outerRadiusRatio - innerRadiusRatio);
    const angle = (i * goldenAngle) % TAU;
    points[i] = { angle, radiusRatio, seed: i };
  }
  return points;
}

// --- Geometry defaults (director-tunable via `options`/`setOptions()`) ----

// Suggested CSS pixel diameter for the Talk hero mount (SPEC 4: "~520px").
// Actual on-screen radius is always measured from the canvas's rendered box
// (see resize()), so this is a fallback/documentation value only, not a
// hard constraint -- the ring is fully responsive to whatever size the
// container/CSS gives it.
export const DEFAULT_SIZE_PX = 520;

// NOTE on values without an exact spec number: segment counts, gap ratios,
// particle density, and rotate speeds are the director's-best-guess-from-
// mockup defaults (flagged in the phase report) -- everything here is meant
// to be tuned via setOptions() rather than requiring a code change.
export const DEFAULT_OPTIONS = {
  sizePx: DEFAULT_SIZE_PX,

  outerRing: {
    radiusRatio: 0.98,   // fraction of measured outer radius
    opacity: 0.14,
    lineWidthPx: 1,
  },

  // Concentric SEGMENTED tech rings, outer -> inner. 3 radii per SPEC 4.
  segmentedRings: [
    { radiusRatio: 0.86, segmentCount: 72, lineWidthRatio: 0.006, gapRatio: 0.45, baseOpacity: 0.32, activeOpacity: 0.95, activeFraction: 0.16, rotateSpeed: 0.03 },
    { radiusRatio: 0.68, segmentCount: 54, lineWidthRatio: 0.009, gapRatio: 0.4, baseOpacity: 0.38, activeOpacity: 1.0, activeFraction: 0.2, rotateSpeed: -0.02 },
    { radiusRatio: 0.5, segmentCount: 40, lineWidthRatio: 0.012, gapRatio: 0.35, baseOpacity: 0.42, activeOpacity: 1.0, activeFraction: 0.22, rotateSpeed: 0.045 },
  ],

  waveform: {
    barCount: 64,
    widthRatio: 0.74,       // span of the waveform as a fraction of the diameter
    barGapRatio: 0.35,
    minHeightRatio: 0.03,   // idle sliver height, fraction of outer radius
    maxHeightRatio: 0.3,    // amplitude=1 height, fraction of outer radius
  },

  particles: {
    count: 46,
    innerRadiusRatio: 0.3,
    outerRadiusRatio: 0.92,
    minSizePx: 0.6,
    maxSizePx: 1.8,
    baseOpacity: 0.16,
    driftSpeed: 0.015, // rad/sec, slow independent drift
  },

  voidCore: {
    radiusRatio: 0.32,
    opacity: 0.22,
  },
};

function mergeDeep(base, patch) {
  if (!patch || typeof patch !== 'object') return base;
  const out = Array.isArray(base) ? base.slice() : { ...base };
  for (const key of Object.keys(patch)) {
    const patchVal = patch[key];
    const baseVal = out[key];
    if (patchVal && typeof patchVal === 'object' && !Array.isArray(patchVal) && baseVal && typeof baseVal === 'object' && !Array.isArray(baseVal)) {
      out[key] = mergeDeep(baseVal, patchVal);
    } else {
      out[key] = patchVal;
    }
  }
  return out;
}

// --- Color token resolution (reads --sd-* CSS custom properties so no raw
// hex lives outside signal-desk.css; falls back to the same literal values
// signal-desk.css defines, for non-DOM/test environments). --------------

const TOKEN_CSS_VAR = {
  cyan: '--sd-cyan',
  teal: '--sd-teal',
  green: '--sd-green',
  greenBright: '--sd-green-bright',
  amber: '--sd-amber',
  red: '--sd-red',
  blue: '--sd-blue',
};

const TOKEN_HEX_FALLBACK = {
  cyan: '#22D3EE',
  teal: '#2DD4BF',
  green: '#22C55E',
  greenBright: '#34D399',
  amber: '#F59E0B',
  red: '#EF4444',
  blue: '#3B82F6',
};

function readToken(el, token) {
  const fallback = TOKEN_HEX_FALLBACK[token] || TOKEN_HEX_FALLBACK.cyan;
  const varName = TOKEN_CSS_VAR[token];
  if (!varName || !el || typeof getComputedStyle !== 'function') return fallback;
  try {
    const value = getComputedStyle(el).getPropertyValue(varName).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
}

function hexToRgb(hex) {
  const h = String(hex).replace('#', '').trim();
  if (!/^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$/.test(h)) return [34, 211, 238];
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const n = parseInt(full, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgba(hex, a) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function lerpColor(c1, c2, t) {
  const a = hexToRgb(c1);
  const b = hexToRgb(c2);
  return `rgb(${Math.round(lerp(a[0], b[0], t))}, ${Math.round(lerp(a[1], b[1], t))}, ${Math.round(lerp(a[2], b[2], t))})`;
}

// Deterministic per-segment "is this one lit up brighter" flag -- a fixed
// hash of the index plus a slowly-advancing time bucket, so segments light
// up and settle rather than flickering every single frame.
function segmentActive(index, ringIndex, timeBucket, activeFraction) {
  const h = Math.sin(index * 12.9898 + ringIndex * 78.233 + timeBucket * 37.719) * 43758.5453;
  const frac = h - Math.floor(h);
  return frac < Math.max(0, Math.min(1, activeFraction));
}

// --- DOM/canvas wiring ------------------------------------------------------

function noopSignalCore() {
  return {
    setState() {},
    setAmplitude() {},
    setOptions() {},
    getOptions() { return null; },
    getState() { return 'idle'; },
    renderOnce() {},
    pause() {},
    resume() {},
    destroy() {},
  };
}

function resolveCanvas(config) {
  if (config.canvas && typeof config.canvas.getContext === 'function') {
    return config.canvas;
  }
  const container = config.container;
  if (container && typeof container.appendChild === 'function') {
    const doc = container.ownerDocument || (typeof document !== 'undefined' ? document : null);
    if (!doc || typeof doc.createElement !== 'function') return null;
    const el = doc.createElement('canvas');
    el.className = 'sd-signal-core-canvas';
    el.setAttribute('aria-hidden', 'true');
    container.appendChild(el);
    return el;
  }
  return null;
}

/**
 * @param {object} config
 * @param {HTMLCanvasElement} [config.canvas] An existing canvas to draw into.
 * @param {HTMLElement} [config.container] If no `canvas` is given, a canvas is
 *   created and appended into this element (sized by its CSS box, see resize()).
 * @param {string} [config.state='idle'] Initial state (SIGNAL_CORE_STATES, or
 *   an alias -- see SIGNAL_CORE_STATE_ALIASES / resolveSignalCoreState).
 * @param {number} [config.amplitude] Initial external amplitude (0..1).
 * @param {object} [config.options] Deep-merged over DEFAULT_OPTIONS.
 */
export function createSignalCore(config = {}) {
  const canvas = resolveCanvas(config);
  if (!canvas || typeof canvas.getContext !== 'function') {
    return noopSignalCore();
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return noopSignalCore();

  const reduceMotion = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  let options = mergeDeep(DEFAULT_OPTIONS, config.options || {});
  let particlePoints = computeParticlePositions(
    options.particles.count,
    options.particles.innerRadiusRatio,
    options.particles.outerRadiusRatio,
  );

  let stateName = resolveSignalCoreState(config.state || 'idle');
  let tokens = stateToColorTokens(stateName);
  let curPrimary = readToken(canvas, tokens.primaryToken);
  let curSecondary = readToken(canvas, tokens.secondaryToken);
  let fromPrimary = curPrimary;
  let fromSecondary = curSecondary;
  let colorMix = 1;
  let curAmpBase = tokens.baseAmplitude;
  let targetAmpBase = tokens.baseAmplitude;

  let extAmp = typeof config.amplitude === 'number' ? Math.max(0, Math.min(1, config.amplitude)) : null;

  let dpr = Math.max(1, Math.min((typeof window !== 'undefined' && window.devicePixelRatio) || 1, 2));
  let W = 0;
  let H = 0;
  let CX = 0;
  let CY = 0;
  let outerR = 1;
  let t = 0;
  let last = 0;
  let rafId = 0;
  let running = false;

  function resize() {
    const rect = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { width: 0, height: 0 };
    const cssW = Math.max(1, Math.round(rect.width || canvas.width || options.sizePx));
    const cssH = Math.max(1, Math.round(rect.height || canvas.height || options.sizePx));
    dpr = Math.max(1, Math.min((typeof window !== 'undefined' && window.devicePixelRatio) || 1, 2));
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    W = canvas.width;
    H = canvas.height;
    CX = W / 2;
    CY = H / 2;
    // Leave headroom for glow/halo so nothing clips at the canvas edge.
    outerR = Math.min(W, H) * 0.46;
  }

  function setState(name) {
    const next = resolveSignalCoreState(name);
    if (next === stateName) return;
    stateName = next;
    tokens = stateToColorTokens(stateName);
    fromPrimary = curPrimary;
    fromSecondary = curSecondary;
    colorMix = 0;
    targetAmpBase = tokens.baseAmplitude;
  }

  function amplitudeNow() {
    if (extAmp != null) return extAmp;
    const breath = (Math.sin(t * 1.4) * 0.5 + 0.5) * 0.12;
    return Math.min(1, curAmpBase + breath);
  }

  function drawOuterRing(amp) {
    const r = outerR * options.outerRing.radiusRatio;
    ctx.beginPath();
    ctx.arc(CX, CY, r, 0, TAU);
    ctx.strokeStyle = rgba(curPrimary, options.outerRing.opacity * (0.8 + amp * 0.4));
    ctx.lineWidth = options.outerRing.lineWidthPx * dpr;
    ctx.stroke();
  }

  function drawSegmentedRings(amp) {
    const timeBucket = Math.floor(t * 1.2); // segments re-roll ~every 0.8s, not every frame
    options.segmentedRings.forEach((ring, ringIndex) => {
      const segments = computeSegmentAngles(ring.segmentCount, ring.gapRatio);
      if (!segments.length) return;
      const r = outerR * ring.radiusRatio;
      const rot = t * ring.rotateSpeed;
      const lineWidth = Math.max(0.6, outerR * ring.lineWidthRatio) * dpr;
      const activeFraction = Math.min(0.9, ring.activeFraction + tokens.activeBoost * (0.5 + amp));
      segments.forEach((seg, segIndex) => {
        const active = segmentActive(segIndex, ringIndex, timeBucket, activeFraction);
        const alpha = active ? ring.activeOpacity : ring.baseOpacity;
        ctx.beginPath();
        ctx.arc(CX, CY, r, seg.start + rot, seg.end + rot);
        ctx.strokeStyle = active ? curSecondary : curPrimary;
        ctx.lineWidth = lineWidth * (active ? 1.4 : 1);
        ctx.lineCap = 'round';
        ctx.globalAlpha = Math.max(0.02, Math.min(1, alpha * (0.75 + amp * 0.35)));
        if (active) {
          ctx.shadowBlur = outerR * 0.05;
          ctx.shadowColor = curSecondary;
        }
        ctx.stroke();
        ctx.shadowBlur = 0;
      });
    });
    ctx.globalAlpha = 1;
  }

  function drawParticles() {
    const { minSizePx, maxSizePx, baseOpacity, driftSpeed } = options.particles;
    particlePoints.forEach((p) => {
      const angle = p.angle + t * driftSpeed * (p.seed % 2 === 0 ? 1 : -1);
      const r = outerR * p.radiusRatio;
      const x = CX + Math.cos(angle) * r;
      const y = CY + Math.sin(angle) * r;
      const twinkle = 0.5 + 0.5 * Math.sin(t * 0.6 + p.seed * 1.7);
      const size = (minSizePx + (maxSizePx - minSizePx) * ((p.seed % 7) / 6)) * dpr;
      ctx.globalAlpha = baseOpacity * twinkle;
      ctx.fillStyle = curPrimary;
      ctx.beginPath();
      ctx.arc(x, y, size / 2, 0, TAU);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
  }

  function drawWaveform(amp) {
    const { barCount, widthRatio, barGapRatio, minHeightRatio, maxHeightRatio } = options.waveform;
    const heights = computeWaveformBarHeights(barCount, amp, t, {
      minHeight: minHeightRatio,
      maxHeight: maxHeightRatio,
    });
    if (!heights.length) return;
    const span = outerR * 2 * widthRatio;
    const slot = span / barCount;
    const barWidth = Math.max(1, slot * (1 - barGapRatio)) * dpr;
    const startX = CX - span / 2;

    ctx.lineCap = 'round';
    ctx.shadowBlur = outerR * 0.08;
    ctx.shadowColor = curPrimary;
    heights.forEach((hRatio, i) => {
      const halfH = outerR * hRatio;
      const x = startX + slot * (i + 0.5);
      ctx.beginPath();
      ctx.moveTo(x, CY - halfH);
      ctx.lineTo(x, CY + halfH);
      ctx.strokeStyle = curPrimary;
      ctx.lineWidth = barWidth;
      ctx.globalAlpha = 0.55 + Math.min(0.45, hRatio * 1.2);
      ctx.stroke();
    });
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  }

  function drawVoidCore(amp) {
    const r = outerR * options.voidCore.radiusRatio * (1 - amp * 0.05);
    const core = ctx.createRadialGradient(CX, CY, 0, CX, CY, r);
    core.addColorStop(0, 'rgba(4, 6, 12, ' + options.voidCore.opacity + ')');
    core.addColorStop(1, 'rgba(4, 6, 12, 0)');
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(CX, CY, r, 0, TAU);
    ctx.fill();
  }

  // The actual per-tick draw (advance time/color/amp, then paint every
  // layer). Factored out of frame() so a single frame can be rendered
  // on-demand (renderOnce(), in the returned API) without requiring the
  // RAF loop to be running -- e.g. for a "good static frame" QA render, or
  // a host page where requestAnimationFrame doesn't fire (a backgrounded/
  // non-composited tab, headless capture, etc.).
  function stepAndDraw(dt) {
    t += dt * (reduceMotion ? 0.35 : 1);

    const e = Math.min(1, dt * 6);
    curAmpBase = lerp(curAmpBase, targetAmpBase, e);
    colorMix = Math.min(1, colorMix + dt * 3);
    curPrimary = lerpColor(fromPrimary, readTargetPrimary(), colorMix);
    curSecondary = lerpColor(fromSecondary, readTargetSecondary(), colorMix);

    const amp = amplitudeNow();

    ctx.clearRect(0, 0, W, H);
    drawOuterRing(amp);
    drawParticles();
    drawSegmentedRings(amp);
    drawVoidCore(amp);
    if (!reduceMotion || amp > 0) drawWaveform(amp);
  }

  function frame(now) {
    if (!running) return;
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
    last = now;
    stepAndDraw(dt);
    rafId = requestAnimationFrame(frame);
  }

  // Re-reads the live token (so a theme swap picks up new CSS var values)
  // without re-triggering the crossfade every frame.
  function readTargetPrimary() {
    return readToken(canvas, tokens.primaryToken);
  }
  function readTargetSecondary() {
    return readToken(canvas, tokens.secondaryToken);
  }

  function start() {
    if (running) return;
    running = true;
    last = 0;
    rafId = requestAnimationFrame(frame);
  }
  function stop() {
    running = false;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
  }

  const onVisibility = () => {
    if (typeof document === 'undefined') return;
    if (document.hidden) stop();
    else start();
  };
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility);
  }

  let ro = null;
  if (typeof ResizeObserver === 'function') {
    ro = new ResizeObserver(() => resize());
    ro.observe(canvas);
  } else if (typeof window !== 'undefined') {
    window.addEventListener('resize', resize);
  }

  resize();
  start();

  return {
    setState,
    setAmplitude(a) {
      extAmp = a == null ? null : Math.max(0, Math.min(1, Number(a) || 0));
    },
    setOptions(patch) {
      options = mergeDeep(options, patch || {});
      particlePoints = computeParticlePositions(
        options.particles.count,
        options.particles.innerRadiusRatio,
        options.particles.outerRadiusRatio,
      );
      resize();
    },
    getOptions() {
      return mergeDeep(options, {});
    },
    getState() {
      return stateName;
    },
    // Paints exactly one frame immediately, independent of the RAF loop
    // (does not require start()/resume() to have been called, and does not
    // itself schedule another frame). See "a good static frame is fine for
    // QA" -- this is the intended hook for tooling that wants a single
    // deterministic render rather than a live animation.
    renderOnce() {
      stepAndDraw(1 / 60);
    },
    pause: stop,
    resume: start,
    destroy() {
      stop();
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibility);
      }
      if (ro) ro.disconnect();
      else if (typeof window !== 'undefined') window.removeEventListener('resize', resize);
    },
  };
}

if (typeof window !== 'undefined') {
  window.createSignalCore = createSignalCore;
}
