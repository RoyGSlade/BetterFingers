// glitch-ring.js — a small, dependency-free animated status ring.
//
// Distilled from the AI-Studio "BetterFingers Glitch Ring" visualizer into a
// compact, status-driven canvas widget. There is no audio/mic/synth code here:
// motion is driven by the current `state` plus an optional externally-supplied
// `amplitude` (e.g. real mic RMS during recording).
//
// Usage:
//   import { createGlitchRing } from './glitch-ring.js';
//   const ring = createGlitchRing(canvasEl, { state: 'idle', compact: true, theme: 'cobalt' });
//   ring.setState('recording');
//   ring.setAmplitude(0.7);   // optional, 0..1
//   ring.destroy();
//
// The same module also attaches `window.createGlitchRing` for classic-script use.

const TAU = Math.PI * 2;

// Per-state visual vocabulary. Colors follow the overlay spec:
//  idle: dim cobalt · listening: teal · recording: coral/red · processing
//  (transcribing/rewriting/chunking): amber+cobalt arcs · stitching: blue wave
//  ready: green/teal check · error: red/orange fracture.
const STATE_STYLES = {
  idle: {
    primary: '#4c6ef5', highlight: '#8fa2ff', glow: '#4c6ef5',
    amp: 0.05, pulseSpeed: 0.9, pulseDepth: 0.05, glitch: 0.04,
    rotate: 0.05, mode: 'ring', flecks: 0.15,
  },
  listening: {
    primary: '#14b8a6', highlight: '#5eead4', glow: '#2dd4bf',
    amp: 0.24, pulseSpeed: 1.5, pulseDepth: 0.16, glitch: 0.06,
    rotate: 0.10, mode: 'ring', flecks: 0.3,
  },
  recording: {
    primary: '#ff3b30', highlight: '#ffb4ae', glow: '#ff5a4d',
    amp: 0.5, pulseSpeed: 3.4, pulseDepth: 0.2, glitch: 0.34,
    rotate: 0.16, mode: 'ring', flecks: 1.0,
  },
  transcribing: {
    primary: '#fbbf24', highlight: '#4c6ef5', glow: '#fbbf24',
    amp: 0.32, pulseSpeed: 1.2, pulseDepth: 0.08, glitch: 0.24,
    rotate: 0.9, mode: 'arcs', flecks: 0.5,
  },
  stitching: {
    primary: '#3b82f6', highlight: '#93c5fd', glow: '#3b82f6',
    amp: 0.3, pulseSpeed: 1.1, pulseDepth: 0.1, glitch: 0.05,
    rotate: 0.14, mode: 'wave', flecks: 0.2,
  },
  ready: {
    primary: '#34d399', highlight: '#a7f3d0', glow: '#34d399',
    amp: 0.28, pulseSpeed: 1.3, pulseDepth: 0.09, glitch: 0.03,
    rotate: 0.08, mode: 'check', flecks: 0.2,
  },
  error: {
    primary: '#ff7c87', highlight: '#f97316', glow: '#ff7c87',
    amp: 0.42, pulseSpeed: 2.6, pulseDepth: 0.14, glitch: 0.7,
    rotate: 0.2, mode: 'fracture', flecks: 0.7,
  },
  warning: {
    primary: '#fbbf24', highlight: '#fde68a', glow: '#fbbf24',
    amp: 0.3, pulseSpeed: 1.8, pulseDepth: 0.12, glitch: 0.2,
    rotate: 0.12, mode: 'ring', flecks: 0.4,
  },
};

// Aliases so callers can pass the app's IPC/status vocabulary directly.
const STATE_ALIASES = {
  rewriting: 'transcribing',
  processing: 'transcribing',
  chunking: 'transcribing',
  blocked: 'error',
  sent: 'ready',
  success: 'ready',
  danger: 'error',
};

function resolveState(name) {
  if (STATE_STYLES[name]) return name;
  if (STATE_ALIASES[name]) return STATE_ALIASES[name];
  return 'idle';
}

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgba(hex, a) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

// Linear-ish interpolation between two style objects for smooth state changes.
function lerp(a, b, t) { return a + (b - a) * t; }
function lerpColor(c1, c2, t) {
  const a = hexToRgb(c1), b = hexToRgb(c2);
  return `rgb(${Math.round(lerp(a[0], b[0], t))}, ${Math.round(lerp(a[1], b[1], t))}, ${Math.round(lerp(a[2], b[2], t))})`;
}

export function createGlitchRing(canvas, options = {}) {
  if (!canvas || !canvas.getContext) {
    return { setState() {}, setAmplitude() {}, setTheme() {}, setCompact() {}, pause() {}, resume() {}, destroy() {} };
  }
  const ctx = canvas.getContext('2d');
  const reduceMotion = typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches;

  let compact = options.compact !== false; // default compact (overlay use)
  // Vibrancy scales glow/brightness/fleck density: 1 = normal, <1 dimmer, >1 hotter.
  let vibrancy = Math.max(0.3, Math.min(2, Number(options.vibrancy ?? 1) || 1));
  // A soft circular disc behind the ring — the "background of the circle" (a
  // circle, not a box). Defaults on; the window opacity setting controls how
  // see-through the whole thing is.
  let backdrop = options.backdrop !== false;
  let stateName = resolveState(options.state || 'idle');
  let target = STATE_STYLES[stateName];
  let cur = { ...target }; // animated (eased) style
  let curPrimary = target.primary, curHighlight = target.highlight, curGlow = target.glow;
  let extAmp = null;               // external amplitude override (0..1), or null
  let flash = 0;                   // transient brightness burst on state change
  let colorMix = 1;                // 0..1 progress of color crossfade
  let fromPrimary = curPrimary, fromHighlight = curHighlight, fromGlow = curGlow;

  let dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
  let W = 0, H = 0, CX = 0, CY = 0, baseR = 1;
  let t = 0;              // time in seconds
  let last = 0;
  let rafId = 0;
  let running = false;
  let flecks = [];        // transient glitch flecks {x,y,vx,vy,life,max,size,color}

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const cssW = Math.max(1, Math.round(rect.width || canvas.width || 24));
    const cssH = Math.max(1, Math.round(rect.height || canvas.height || 24));
    dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    W = canvas.width; H = canvas.height;
    CX = W / 2; CY = H / 2;
    // Smaller ring radius leaves room for the circular backdrop + glow + flecks.
    baseR = Math.min(W, H) * (compact ? 0.26 : 0.28);
  }

  function setState(name) {
    const next = resolveState(name);
    if (next === stateName) return;
    stateName = next;
    target = STATE_STYLES[next];
    // Start a color crossfade and a brightness flash from the current values.
    fromPrimary = curPrimary; fromHighlight = curHighlight; fromGlow = curGlow;
    colorMix = 0;
    flash = (next === 'ready' || next === 'recording' || next === 'error') ? 1 : 0.5;
  }

  function amplitudeNow() {
    if (extAmp != null) return extAmp;
    // Synthetic "breathing" when no external amplitude is supplied.
    const breath = (Math.sin(t * cur.pulseSpeed) * 0.5 + 0.5) * cur.pulseDepth;
    return Math.min(1, cur.amp + breath);
  }

  function spawnFleck(radius, amp) {
    const ang = Math.random() * TAU;
    const r = radius + (Math.random() * 6 - 3) * dpr;
    flecks.push({
      x: CX + Math.cos(ang) * r,
      y: CY + Math.sin(ang) * r,
      vx: Math.cos(ang) * (0.3 + Math.random() * 1.2) * dpr,
      vy: Math.sin(ang) * (0.3 + Math.random() * 1.2) * dpr,
      life: 0,
      max: 0.4 + Math.random() * 0.5,
      size: (0.6 + Math.random() * 1.6) * dpr,
      color: Math.random() > 0.5 ? curPrimary : curHighlight,
    });
  }

  // Broken-arc ring: many short arc chunks at random angles with radius jitter,
  // variable alpha/width, and occasional glitch over-saturation. This is the
  // signature of the original visualizer, distilled.
  function drawRing(radius, amp, glitch, rotate) {
    const segs = Math.round((compact ? 46 : 120) * (0.7 + amp * 0.6));
    const jitter = (compact ? 3 : 7) * dpr * (0.5 + glitch);
    const rot = t * rotate;
    for (let i = 0; i < segs; i++) {
      const base = Math.random() * TAU + rot;
      const arcLen = 0.02 + Math.random() * (compact ? 0.14 : 0.09);
      const rr = radius + (Math.random() * 2 - 1) * jitter;
      let alpha = 0.08 + Math.random() * 0.4 + amp * 0.25;
      if (Math.random() < glitch * 0.18) alpha += Math.random() * 0.5;
      alpha = Math.min(1, alpha * vibrancy) * (0.6 + flash * 0.5);
      const special = Math.random() > 0.72;
      ctx.beginPath();
      const steps = 3;
      for (let s = 0; s <= steps; s++) {
        const a = base + arcLen * (s / steps);
        const x = CX + Math.cos(a) * rr;
        const y = CY + Math.sin(a) * rr;
        if (s === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = special ? curPrimary : curHighlight;
      ctx.lineWidth = (0.6 + Math.random() * (compact ? 2.0 : 3.5)) * dpr;
      ctx.lineCap = 'round';
      ctx.globalAlpha = Math.max(0.03, alpha);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // Processing mode: a few rotating broken arcs with clear gaps.
  function drawArcs(radius, amp, rotate) {
    const groups = 3;
    const rot = t * rotate;
    for (let g = 0; g < groups; g++) {
      const start = rot + (g / groups) * TAU;
      const sweep = 0.9 + Math.sin(t * 1.7 + g) * 0.15;
      ctx.beginPath();
      ctx.arc(CX, CY, radius, start, start + sweep);
      ctx.strokeStyle = g % 2 === 0 ? curPrimary : curHighlight;
      ctx.lineWidth = (compact ? 2.2 : 3.4) * dpr;
      ctx.lineCap = 'round';
      ctx.globalAlpha = 0.85;
      ctx.shadowBlur = 6 * dpr;
      ctx.shadowColor = curGlow;
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    ctx.globalAlpha = 1;
    // A faint full base ring under the arcs.
    ctx.beginPath();
    ctx.arc(CX, CY, radius, 0, TAU);
    ctx.strokeStyle = rgba(curPrimary, 0.12);
    ctx.lineWidth = 1 * dpr;
    ctx.stroke();
  }

  // Stitching mode: a smooth calm ring. The centre motion comes from the shared
  // voice-wave, so this just draws the clean outer ring.
  function drawWave(radius) {
    ctx.beginPath();
    ctx.arc(CX, CY, radius, 0, TAU);
    ctx.strokeStyle = rgba(curPrimary, 0.85);
    ctx.lineWidth = (compact ? 1.8 : 2.6) * dpr;
    ctx.stroke();
  }

  // Fracture mode: ring split into jagged, radially displaced chunks.
  function drawFracture(radius, amp, glitch) {
    const chunks = compact ? 7 : 12;
    for (let i = 0; i < chunks; i++) {
      const gap = 0.12 + Math.random() * 0.1;
      const start = (i / chunks) * TAU + Math.random() * 0.05;
      const off = (Math.random() * 2 - 1) * (compact ? 3 : 6) * dpr * glitch;
      ctx.beginPath();
      ctx.arc(CX, CY, radius + off, start, start + (TAU / chunks) - gap);
      ctx.strokeStyle = Math.random() > 0.5 ? curPrimary : curHighlight;
      ctx.lineWidth = (0.8 + Math.random() * 2.4) * dpr;
      ctx.lineCap = 'round';
      ctx.globalAlpha = 0.5 + Math.random() * 0.5;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // A settling check mark for the "ready" state (drawn once the flash calms).
  function drawCheck(radius) {
    const reveal = 1 - Math.min(1, flash * 1.4); // appears as flash decays
    if (reveal <= 0.02) return;
    const r = radius * 0.62;
    ctx.beginPath();
    ctx.moveTo(CX - r * 0.55, CY + r * 0.02);
    ctx.lineTo(CX - r * 0.12, CY + r * 0.45 * reveal);
    ctx.lineTo(CX + r * 0.6, CY - r * 0.5 * reveal);
    ctx.strokeStyle = curHighlight;
    ctx.lineWidth = Math.max(1.5, radius * 0.14);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.globalAlpha = reveal;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Live, electric voice-wave across the centre — an oscilloscope-style line that
  // reacts to amplitude and jitters a little for that "type-beat" energy. Two
  // colour-matched passes (bright core + softer echo) with a glow.
  function drawVoiceWave(radius, amp) {
    const span = radius * 1.05;
    const n = compact ? 26 : 44;
    const height = radius * (0.12 + amp * 0.5);
    const jitter = reduceMotion ? 0 : (0.12 + amp * 0.45);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.shadowBlur = radius * 0.22 * vibrancy;
    ctx.shadowColor = curGlow;
    for (let pass = 0; pass < 2; pass++) {
      ctx.beginPath();
      for (let i = 0; i <= n; i++) {
        const fx = i / n;                       // 0..1 across the wave
        const x = CX - span + fx * span * 2;
        const env = Math.sin(fx * Math.PI);     // taper toward the edges
        const wobble =
          Math.sin(fx * 11 + t * (7 + pass * 2)) * 0.6 +
          Math.sin(fx * 23 - t * 10) * 0.3 +
          (Math.random() - 0.5) * jitter;       // electric flicker
        const y = CY + wobble * height * env * (pass ? 0.55 : 1);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = pass ? curPrimary : curHighlight;
      ctx.lineWidth = Math.max(1, radius * (pass ? 0.03 : 0.05)) * dpr;
      ctx.globalAlpha = Math.min(1, (pass ? 0.4 : 0.92) * vibrancy);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  }

  function frame(now) {
    if (!running) return;
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
    last = now;
    t += dt * (reduceMotion ? 0.35 : 1);

    // Ease animated style + colors toward the target for smooth transitions.
    const e = Math.min(1, dt * 6);
    for (const k of ['amp', 'pulseSpeed', 'pulseDepth', 'glitch', 'rotate', 'flecks']) {
      cur[k] = lerp(cur[k], target[k], e);
    }
    colorMix = Math.min(1, colorMix + dt * 3);
    curPrimary = lerpColor(fromPrimary, target.primary, colorMix);
    curHighlight = lerpColor(fromHighlight, target.highlight, colorMix);
    curGlow = lerpColor(fromGlow, target.glow, colorMix);
    if (flash > 0) flash = Math.max(0, flash - dt * 1.6);

    const amp = amplitudeNow();
    const glitch = reduceMotion ? Math.min(0.05, cur.glitch) : cur.glitch;
    const radius = baseR * (1 + amp * (compact ? 0.18 : 0.22));

    // Clear (transparent — the overlay/panel provides its own background).
    ctx.clearRect(0, 0, W, H);

    // Circular backdrop disc behind everything (a circle, not a box). Soft edge
    // so it reads as a round chip. Window opacity governs overall transparency.
    if (backdrop) {
      const bR = radius * 1.55;
      const disc = ctx.createRadialGradient(CX, CY, bR * 0.2, CX, CY, bR);
      disc.addColorStop(0, 'rgba(9, 12, 20, 0.62)');
      disc.addColorStop(0.82, 'rgba(9, 12, 20, 0.55)');
      disc.addColorStop(0.97, 'rgba(9, 12, 20, 0.16)');
      disc.addColorStop(1, 'rgba(9, 12, 20, 0)');
      ctx.fillStyle = disc;
      ctx.beginPath();
      ctx.arc(CX, CY, bR, 0, TAU);
      ctx.fill();
    }

    // Soft glow halo behind the ring.
    const haloR = radius * 2.0;
    const halo = ctx.createRadialGradient(CX, CY, radius * 0.2, CX, CY, haloR);
    halo.addColorStop(0, rgba(curGlow, Math.min(0.95, (0.28 + amp * 0.25 + flash * 0.2) * vibrancy)));
    halo.addColorStop(0.6, rgba(curGlow, Math.min(0.4, 0.06 * vibrancy)));
    halo.addColorStop(1, rgba(curGlow, 0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(CX, CY, haloR, 0, TAU);
    ctx.fill();

    // Ring body per mode.
    const mode = reduceMotion && (cur.mode === 'fracture' || cur.mode === 'arcs') ? 'ring' : cur.mode;
    if (mode === 'arcs') drawArcs(radius, amp, cur.rotate);
    else if (mode === 'wave') drawWave(radius, amp);
    else if (mode === 'fracture') drawFracture(radius, amp, glitch);
    else drawRing(radius, amp, glitch, cur.rotate);
    if (cur.mode === 'check') drawCheck(radius);

    // Inner void core so the center reads as depth, not fill.
    const voidR = radius * 0.72;
    // Kept subtle: on a transparent overlay a heavy core reads as a dark disc.
    // A light center just gives the ring a hint of depth over any background.
    const core = ctx.createRadialGradient(CX, CY, 0, CX, CY, voidR);
    core.addColorStop(0, 'rgba(4, 6, 12, 0.3)');
    core.addColorStop(0.7, 'rgba(4, 6, 12, 0.12)');
    core.addColorStop(1, 'rgba(4, 6, 12, 0)');
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(CX, CY, voidR, 0, TAU);
    ctx.fill();

    // Live electric voice-wave across the centre (skipped when the ready check
    // owns the centre). Reacts to amplitude, colour-matched to the state.
    if (cur.mode !== 'check') drawVoiceWave(radius, amp);

    // Glitch flecks (spawn rate scales with state + amplitude).
    if (!reduceMotion) {
      const rate = cur.flecks * (0.4 + amp) * (compact ? 0.6 : 1.4) * vibrancy;
      if (Math.random() < rate) spawnFleck(radius, amp);
    }
    for (let i = flecks.length - 1; i >= 0; i--) {
      const f = flecks[i];
      f.life += dt;
      f.x += f.vx; f.y += f.vy;
      const lp = f.life / f.max;
      if (lp >= 1) { flecks.splice(i, 1); continue; }
      ctx.globalAlpha = (1 - lp) * 0.9;
      ctx.fillStyle = f.color;
      ctx.fillRect(f.x, f.y, f.size, f.size);
    }
    ctx.globalAlpha = 1;

    rafId = requestAnimationFrame(frame);
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

  // Pause when the window/tab is hidden to save CPU.
  const onVisibility = () => { if (document.hidden) stop(); else start(); };
  document.addEventListener('visibilitychange', onVisibility);

  let ro = null;
  if (typeof ResizeObserver === 'function') {
    ro = new ResizeObserver(() => resize());
    ro.observe(canvas);
  } else {
    window.addEventListener('resize', resize);
  }

  resize();
  if (extAmp == null && typeof options.amplitude === 'number') extAmp = options.amplitude;
  start();

  return {
    setState,
    setAmplitude(a) { extAmp = (a == null ? null : Math.max(0, Math.min(1, a))); },
    setTheme(/* theme */) { /* reserved: alternate base palettes */ },
    setVibrancy(v) { vibrancy = Math.max(0.3, Math.min(2, Number(v) || 1)); },
    setCompact(v) { compact = !!v; resize(); },
    pause: stop,
    resume: start,
    destroy() {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
      if (ro) ro.disconnect(); else window.removeEventListener('resize', resize);
      flecks = [];
    },
  };
}

if (typeof window !== 'undefined') {
  window.createGlitchRing = createGlitchRing;
}
