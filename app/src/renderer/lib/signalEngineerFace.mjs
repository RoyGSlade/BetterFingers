// signalEngineerFace.mjs -- the Signal Engineer face as one SVG.
//
// Hybrid build (owner decision, 2026-11-04): the metal parts are the painted
// atlas, cut out pixel-for-pixel by tools/signal_engineer_parts.py; every light
// is a live vector drawn here, so eyes, mouth, brows and accent strips can
// animate and change colour. Geometry comes from one spec
// (assets/signal-engineer/<shell>.parts.json, atlas pixel coordinates) that the
// cutter also reads, so the scrubbed raster lights and the vector lights sit in
// exactly the same place.
//
// renderFaceSvg() is pure (no DOM), which lets the overlay, the unit tests and
// app/scripts/export-signal-engineer-svg.mjs share it. createSignalEngineerFace()
// is the thin DOM controller the overlay window uses.

export const EXPRESSIONS = Object.freeze([
  'neutral', 'listening', 'talking', 'thinking', 'happy', 'love', 'suspicious',
  'shocked', 'rage', 'sleeping', 'glitch',
]);

/** Overlay ring states (lib/overlayStatus.mjs) -> face expression. */
export const RING_STATE_EXPRESSION = Object.freeze({
  idle: 'neutral',
  listening: 'listening',
  recording: 'listening',
  transcribing: 'thinking',
  stitching: 'thinking',
  ready: 'happy',
  warning: 'suspicious',
  error: 'shocked',
});

export const DEFAULT_COLORS = Object.freeze({
  accent: '#2fe3ee',
  amber: '#ffb02e',
  eye: null, // null = follow accent
  mouth: null,
});

/** Per-expression light colour overrides (eye/mouth) and brow pose. */
const MOODS = {
  neutral: { brows: [0, 0, 0, 0] },
  listening: { brows: [-3, -2, 3, -2] },
  talking: { brows: [-2, -1, 2, -1] },
  thinking: { brows: [6, -4, -2, 2] },
  happy: { brows: [-6, -5, 6, -5] },
  love: { brows: [-8, -6, 8, -6], eye: '#ff6fb5', mouth: '#ff6fb5' },
  suspicious: { brows: [10, 4, -4, -3], eye: '#ffb02e' },
  shocked: { brows: [-10, -10, 10, -10] },
  rage: { brows: [16, 6, -16, 6], eye: '#ff3b3b', mouth: '#ff3b3b' },
  sleeping: { brows: [4, 6, -4, 6] },
  glitch: { brows: [0, 0, 0, 0] },
};

const ANIMATED = new Set(['listening', 'talking', 'thinking', 'glitch', 'rage']);

export function isAnimated(expression) {
  return ANIMATED.has(expression);
}

const r1 = (n) => Math.round(n * 10) / 10;

function hash01(n) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function polyline(pts) {
  return 'M' + pts.map(([x, y]) => `${r1(x)},${r1(y)}`).join(' L');
}

function closedPath(pts) {
  return polyline(pts) + ' Z';
}

function arcPath([cx, cy], r, a0, a1) {
  const p = (a) => [cx + r * Math.cos((a * Math.PI) / 180), cy + r * Math.sin((a * Math.PI) / 180)];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  const large = (a1 - a0) % 360 > 180 ? 1 : 0;
  return `M${r1(x0)},${r1(y0)} A${r},${r} 0 ${large} 1 ${r1(x1)},${r1(y1)}`;
}

/** Vertical bars centred on (cx, cy+offset[i]) with the given heights. */
function bars(cx, cy, heights, spacing, offsets) {
  const n = heights.length;
  const x0 = cx - ((n - 1) * spacing) / 2;
  let d = '';
  for (let i = 0; i < n; i += 1) {
    const x = x0 + i * spacing;
    const h = Math.max(1.5, heights[i]); // never zero-length: some renderers drop it
    const yc = cy + (offsets ? offsets[i] : 0);
    d += `M${r1(x)},${r1(yc - h / 2)} V${r1(yc + h / 2)} `;
  }
  return d.trim();
}

function profile(n, fn) {
  return Array.from({ length: n }, (_, i) => fn(i, n, (i + 0.5) / n));
}

/** LED eye glyph for one eye. side: -1 left, +1 right. Returns {d, w}. */
export function eyeGlyph(expression, { cx, cy, w, h, side, level = 0, t = 0, blink = false }) {
  const n = 9;
  const sp = w / n;
  const bw = sp * 0.52;
  if (blink || expression === 'sleeping') {
    return { d: bars(cx, cy + h * 0.18, profile(n, () => 0.01), sp), w: bw };
  }
  switch (expression) {
    case 'listening': {
      const lv = Math.max(0, Math.min(1, level));
      const hs = profile(n, (i, _n, u) => {
        const dome = Math.sin(Math.PI * u);
        const wobble = 0.55 + 0.45 * Math.sin(t * 9 + i * 1.3 + side);
        return h * (0.18 + 0.82 * dome * (0.25 + 0.75 * lv) * wobble);
      });
      return { d: bars(cx, cy, hs, sp), w: bw };
    }
    case 'happy': {
      const offs = profile(n, (_i, _n, u) => h * 0.55 * (2 * u - 1) ** 2 - h * 0.12);
      return { d: bars(cx, cy, profile(n, () => h * 0.16), sp, offs), w: bw };
    }
    case 'love': {
      const hs = [];
      const offs = [];
      for (let i = 0; i < n; i += 1) {
        const x = ((i + 0.5) / n) * 2 - 1;
        const ax = Math.abs(x);
        const top = -0.42 - 0.42 * Math.sqrt(Math.max(0, 1 - ((ax - 0.5) / 0.5) ** 2));
        const bottom = 0.95 - 0.95 * ax;
        hs.push(((bottom - top) * h) / 2);
        offs.push(((bottom + top) * h) / 4);
      }
      return { d: bars(cx, cy, hs, sp, offs), w: bw };
    }
    case 'suspicious': {
      const hs = profile(n, (_i, _n, u) => h * (0.22 + 0.4 * (side < 0 ? u : 1 - u)));
      return { d: bars(cx, cy + h * 0.12, hs, sp), w: bw };
    }
    case 'shocked': {
      const m = 7;
      const hs = profile(m, (_i, _n, u) => h * 1.12 * Math.sqrt(Math.max(0.05, 1 - (2 * u - 1) ** 2)));
      return { d: bars(cx, cy, hs, (w * 0.8) / m), w: bw };
    }
    case 'rage': {
      const hs = profile(n, (_i, _n, u) => h * (0.25 + 0.75 * (side < 0 ? 1 - u : u)));
      const offs = hs.map((hh) => (h - hh) / 2 - h * 0.08);
      return { d: bars(cx, cy, hs, sp, offs), w: bw };
    }
    case 'thinking': {
      const lit = Math.floor((t * 6) % n);
      const hs = profile(n, (i) => (i === (side < 0 ? lit : n - 1 - lit) ? h * 0.42 : h * 0.06));
      return { d: bars(cx, cy, hs, sp), w: bw };
    }
    case 'glitch': {
      const f = Math.floor(t * 14);
      const hs = profile(n, (i) => h * (0.1 + 0.9 * hash01(f * 31 + i * 7 + side * 3)));
      return { d: bars(cx + (hash01(f) - 0.5) * 6, cy, hs, sp), w: bw };
    }
    case 'talking':
    case 'neutral':
    default: {
      const hs = profile(n, (_i, _n, u) => h * (0.3 + 0.7 * Math.sin(Math.PI * u) ** 0.8));
      return { d: bars(cx, cy, hs, sp), w: bw };
    }
  }
}

/** LED mouth glyph. Returns {d, w}. */
export function mouthGlyph(expression, { cx, cy, w, h, level = 0, t = 0 }) {
  const lw = 3.6;
  switch (expression) {
    case 'talking':
    case 'listening': {
      const n = 21;
      const sp = w / n;
      const lv = Math.max(0, Math.min(1, level));
      const amp = expression === 'talking' ? 0.35 + 0.65 * lv : 0.12 + 0.6 * lv;
      const hs = profile(n, (i, _n, u) => {
        const env = Math.sin(Math.PI * u) ** 1.5;
        const osc = 0.5 + 0.5 * Math.sin(t * 13 + i * 0.9) * Math.sin(t * 5.3 + i * 0.37);
        return Math.max(2, h * amp * env * (0.35 + 0.65 * osc));
      });
      return { d: bars(cx, cy, hs, sp), w: sp * 0.5 };
    }
    case 'thinking': {
      const n = 13;
      const sp = w / n;
      const lit = Math.floor((t * 8) % n);
      return { d: bars(cx, cy, profile(n, (i) => (Math.abs(i - lit) <= 0 ? 7 : 0.01)), sp), w: lw };
    }
    case 'happy':
    case 'love':
      return { d: `M${r1(cx - w * 0.32)},${r1(cy - h * 0.18)} Q${r1(cx)},${r1(cy + h * 0.55)} ${r1(cx + w * 0.32)},${r1(cy - h * 0.18)}`, w: lw };
    case 'suspicious':
      return { d: `M${r1(cx - w * 0.28)},${r1(cy + 3)} L${r1(cx + w * 0.2)},${r1(cy - 2)}`, w: lw };
    case 'shocked':
      return { d: `M${r1(cx)},${r1(cy - h * 0.34)} a${r1(h * 0.34)},${r1(h * 0.34)} 0 1 0 0.01,0 Z`, w: lw };
    case 'rage': {
      const pts = [];
      const n = 8;
      for (let i = 0; i <= n; i += 1) {
        pts.push([cx - w * 0.34 + (i * w * 0.68) / n, cy + (i % 2 ? -h * 0.22 : h * 0.22)]);
      }
      return { d: polyline(pts), w: lw };
    }
    case 'sleeping': {
      const n = 9;
      return { d: bars(cx, cy, profile(n, () => 0.01), (w * 0.5) / n), w: lw };
    }
    case 'glitch': {
      const f = Math.floor(t * 14);
      const pts = [];
      for (let i = 0; i <= 10; i += 1) pts.push([cx - w * 0.36 + i * w * 0.072, cy + (hash01(f * 13 + i) - 0.5) * h * 0.6]);
      return { d: polyline(pts), w: lw };
    }
    case 'neutral':
    default:
      return { d: `M${r1(cx - w * 0.26)},${r1(cy)} L${r1(cx + w * 0.26)},${r1(cy)}`, w: lw };
  }
}

function pivotOf(part) {
  if (part.mask?.circle) return [part.mask.circle[0], part.mask.circle[1]];
  const [x0, y0, x1, y1] = part.box;
  return [(x0 + x1) / 2, (y0 + y1) / 2];
}

function led(d, color, width, glowId, extra = '') {
  return (
    `<g filter="url(#${glowId})"${extra}>` +
    `<path d="${d}" fill="none" stroke="${color}" stroke-width="${r1(width)}" stroke-linecap="round" stroke-linejoin="round"/>` +
    `<path d="${d}" fill="none" stroke="#ffffff" stroke-opacity=".55" stroke-width="${r1(width * 0.38)}" stroke-linecap="round" stroke-linejoin="round"/>` +
    `</g>`
  );
}

function partLeds(part, colors, glowId, surge = 0) {
  const k = 1 + surge * 0.7;
  return (part.leds || [])
    .map((l0) => {
      const l = surge ? { ...l0, w: l0.w * k } : l0;
      const color = l.role === 'amber' ? colors.amber : colors.accent;
      if (l.kind === 'arc') {
        if ((l.a1 - l.a0) % 360 === 0) {
          return (
            `<g filter="url(#${glowId})"><circle cx="${l.c[0]}" cy="${l.c[1]}" r="${l.r}" fill="none" stroke="${color}" stroke-width="${l.w}"/>` +
            `<circle cx="${l.c[0]}" cy="${l.c[1]}" r="${l.r}" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="${r1(l.w * 0.38)}"/></g>`
          );
        }
        return led(arcPath(l.c, l.r, l.a0, l.a1), color, l.w, glowId);
      }
      return led(polyline(l.pts), color, l.w, glowId);
    })
    .join('');
}

/** Vertical jaw-bob offset in px for a part with talkBob = `bob`. */
export function bobOffset(expression, level, t, bob) {
  if (!bob || expression !== 'talking') return 0;
  const lv = Math.max(0, Math.min(1, level || 0));
  return r1(bob * lv * Math.abs(Math.sin(t * 9.5)));
}

function placePart(name, partName, part, place, { partUrls, mood, colors, glowId, expression, level, t, speaking = false, surge = 0 }) {
  const [x0, y0, x1, y1] = part.box;
  const [px, py] = pivotOf(part);
  let transform = '';
  if (place) {
    const s = place.scale ?? 1;
    const sx = place.flip ? -s : s;
    let pose = '';
    if (name === 'browLeft' || name === 'browRight') {
      const [lr, ly, rr, ry] = mood.brows;
      const [rot, dy] = name === 'browLeft' ? [lr, ly] : [rr, ry];
      pose = ` translate(0 ${dy}) rotate(${rot})`;
    }
    transform = ` transform="translate(${place.at[0]} ${place.at[1]})${pose} scale(${sx} ${s}) translate(${-px} ${-py})"`;
  }
  const href = partUrls[partName] || '';
  const inner =
    `<g data-part="${name}"${transform}>` +
    (href ? `<image href="${href}" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}"/>` : '') +
    partLeds(part, colors, `${glowId}-part`, surge) +
    `</g>`;
  const bob = place?.talkBob;
  if (!bob) return inner;
  return `<g data-bob="${bob}" transform="translate(0 ${bobOffset(speaking ? 'talking' : expression, level, t, bob)})">${inner}</g>`;
}

function resolveColors(colors, expression) {
  const c = { ...DEFAULT_COLORS, ...(colors || {}) };
  const mood = MOODS[expression] || MOODS.neutral;
  return {
    accent: c.accent,
    amber: c.amber,
    eye: c.eye || mood.eye || c.accent,
    mouth: c.mouth || mood.mouth || c.accent,
  };
}

/**
 * Just the animated light layers (eyes + mouth), for cheap per-frame updates.
 * `speaking` lip-syncs the mouth on top of any expression (a suspicious face
 * that is talking keeps its suspicious eyes); `look` = [-1..1, -1..1] shifts
 * the eyes toward where he is looking.
 */
export function renderLightsSvg(spec, { expression = 'neutral', level = 0, t = 0, blink = false, speaking = false, look = [0, 0], colors, idPrefix = 'se' } = {}) {
  const c = resolveColors(colors, expression);
  const L = spec.layout;
  const glowId = `${idPrefix}-glow`;
  const [ew, eh] = L.eyes.size;
  const lx = clamp1(look?.[0]) * ew * 0.16;
  const ly = clamp1(look?.[1]) * eh * 0.14;
  const left = eyeGlyph(expression, { cx: L.eyes.left[0] + lx, cy: L.eyes.left[1] + ly, w: ew, h: eh, side: -1, level, t, blink });
  const right = eyeGlyph(expression, { cx: L.eyes.right[0] + lx, cy: L.eyes.right[1] + ly, w: ew, h: eh, side: 1, level, t, blink });
  const [mw, mh] = L.mouth.size;
  const mouthExpr = speaking && expression !== 'listening' && expression !== 'sleeping' ? 'talking' : expression;
  const mouth = mouthGlyph(mouthExpr, { cx: L.mouth.at[0], cy: L.mouth.at[1], w: mw, h: mh, level, t });
  return {
    eyes: led(left.d, c.eye, left.w, glowId) + led(right.d, c.eye, right.w, glowId),
    mouth: led(mouth.d, c.mouth, mouth.w, glowId),
  };
}

function clamp1(v) {
  return typeof v === 'number' && Number.isFinite(v) ? Math.max(-1, Math.min(1, v)) : 0;
}

/**
 * Whole-head motion: explicit `head` = {tilt (deg), dy (px), scale} plus, while
 * speaking, a voice-driven sway and bounce. Returns an SVG transform string.
 */
export function headTransform(spec, { head = {}, speaking = false, level = 0, t = 0 } = {}) {
  const [vx, vy, vw, vh] = spec.viewBox;
  const cx = vx + vw / 2;
  const cy = vy + vh * 0.55;
  const lv = Math.max(0, Math.min(1, level || 0));
  let tilt = Number(head.tilt) || 0;
  let dy = Number(head.dy) || 0;
  const scale = Number(head.scale) || 1;
  if (speaking) {
    tilt += Math.sin(t * 2.3) * 2.2 * (0.4 + lv);
    dy -= lv * 5 * Math.abs(Math.sin(t * 6.8));
  }
  return `translate(${r1(cx)} ${r1(cy + dy)}) rotate(${r1(tilt)}) scale(${r1(scale * 1000) / 1000}) translate(${r1(-cx)} ${r1(-cy)})`;
}

/** Effects an expression brings by itself when no explicit `fx` is given. */
export function defaultFx(expression) {
  if (expression === 'rage') return { steam: 1 };
  if (expression === 'glitch') return { sparks: 1 };
  return {};
}

/**
 * Particle effects, deterministic in t: steam out of the top vent and sparks
 * around the visor. Each intensity is 0..1.
 */
export function renderFxSvg(spec, { fx = {}, t = 0, idPrefix = 'se' } = {}) {
  const [vx, vy, vw] = spec.viewBox;
  const [ventX, ventY] = spec.layout.vent || [vx + vw / 2, vy + 30];
  let out = '';
  const steam = Math.max(0, Math.min(1, Number(fx.steam) || 0));
  if (steam > 0) {
    const n = 14;
    for (let k = 0; k < n; k += 1) {
      const phase = (t * 0.9 + k / n) % 1;
      const side = k % 2 ? 1 : -1;
      const x = ventX + side * (8 + phase * 46) + Math.sin(k * 2.7 + t * 3) * 8 * phase;
      const y = ventY - phase * 110;
      const r = 7 + phase * 26;
      const op = steam * (1 - phase) * 0.55;
      out += `<circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(r)}" fill="#d9e0e6" fill-opacity="${r1(op * 100) / 100}"/>`;
    }
    out = `<g data-fx="steam" filter="url(#${idPrefix}-soft)">${out}</g>`;
  }
  const sparks = Math.max(0, Math.min(1, Number(fx.sparks) || 0));
  if (sparks > 0) {
    const L = spec.layout;
    const anchors = [L.eyes.left, L.eyes.right, L.mouth.at];
    const frame = Math.floor(t * 18);
    let s = '';
    const count = Math.round(4 + sparks * 10);
    for (let k = 0; k < count; k += 1) {
      const a = anchors[Math.floor(hash01(frame * 7 + k) * anchors.length)];
      const ang = hash01(frame * 13 + k * 3) * Math.PI * 2;
      const dist = 30 + hash01(frame * 17 + k) * 50;
      const len = 6 + hash01(frame * 5 + k * 11) * 12;
      const x0 = a[0] + Math.cos(ang) * dist;
      const y0 = a[1] + Math.sin(ang) * dist;
      s += `<path d="M${r1(x0)},${r1(y0)} l${r1(Math.cos(ang) * len)},${r1(Math.sin(ang) * len)}" stroke="${k % 3 ? '#ffd27a' : '#ffffff'}" stroke-width="2" stroke-linecap="round"/>`;
    }
    out += `<g data-fx="sparks" filter="url(#${idPrefix}-glow)">${s}</g>`;
  }
  return out;
}

/**
 * The whole face as an SVG string.
 * @param {object} spec      parsed <shell>.parts.json
 * @param {object} opts
 * @param {Record<string,string>} opts.partUrls  part name -> image URL (or data: URI)
 */
export function renderFaceSvg(spec, { partUrls = {}, expression = 'neutral', level = 0, t = 0, blink = false, speaking = false, look = [0, 0], head = {}, pulse = null, fx = {}, colors, idPrefix = 'se', title = 'Signal Engineer' } = {}) {
  if (!EXPRESSIONS.includes(expression)) expression = 'neutral';
  const c = resolveColors(colors, expression);
  const L = spec.layout;
  const mood = MOODS[expression] || MOODS.neutral;
  const glowId = `${idPrefix}-glow`;
  const glassId = `${idPrefix}-glass`;
  const lights = renderLightsSvg(spec, { expression, level, t, blink, speaking, look, colors, idPrefix });
  // LED surge: follows the voice while speaking unless given explicitly.
  const surge = pulse == null ? (speaking ? Math.max(0, Math.min(1, level)) : 0) : Math.max(0, Math.min(1, pulse));

  const layers = {
    screens:
      `<g data-part="screens">` +
      `<path d="${closedPath(spec.screens.visor)}" fill="url(#${glassId})" stroke="#07090b" stroke-width="5" stroke-linejoin="round"/>` +
      `<path d="${closedPath(spec.screens.mouth)}" fill="url(#${glassId})" stroke="#07090b" stroke-width="5" stroke-linejoin="round"/>` +
      `</g>`,
    eyes: `<g data-part="eyes">${lights.eyes}</g>`,
    mouth: `<g data-part="mouth">${lights.mouth}</g>`,
  };

  // Every other layer is a placed part. A layout entry may reuse another part
  // ("part"), mirror it ("flip"), and bob with the voice ("talkBob" px). A part
  // with no layout entry sits at its atlas position (the chassis).
  const placed = new Set();
  for (const name of L.order) {
    if (layers[name]) continue;
    const place = L[name];
    const partName = place?.part || name;
    const part = spec.parts[partName];
    if (!part) continue;
    placed.add(partName);
    layers[name] = placePart(name, partName, part, place, { partUrls, mood, colors: c, glowId, expression, level, t, speaking, surge });
  }
  for (const [name, part] of Object.entries(spec.parts)) {
    if (!placed.has(name) && !layers[name]) {
      layers[name] = placePart(name, name, part, null, { partUrls, mood, colors: c, glowId, expression, level, t, speaking, surge });
    }
  }

  const [vx, vy, vw, vh] = spec.viewBox;
  const body =
    `<g data-head="1" transform="${headTransform(spec, { head, speaking, level, t })}">` +
    L.order.map((k) => layers[k] || '').join('') +
    `<g data-fx-layer="1">${renderFxSvg(spec, { fx: fx && Object.keys(fx).length ? fx : defaultFx(expression), t, idPrefix })}</g>` +
    `</g>`;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vx} ${vy} ${vw} ${vh}" role="img" aria-label="${title}" data-expression="${expression}">` +
    `<defs>` +
    // Eye/mouth glyphs (face coordinates) can be flat lines with a zero-height
    // bbox, which a bbox-relative filter region clips to nothing: give them a
    // user-space region the size of the face. Part LEDs live in transformed
    // atlas coordinates and are never flat, so they use a bbox region (a huge
    // user-space region there makes renderers allocate huge buffers).
    `<filter id="${glowId}" filterUnits="userSpaceOnUse" x="${vx - 20}" y="${vy - 20}" width="${vw + 40}" height="${vh + 40}"><feGaussianBlur stdDeviation="2.6" result="b"/>` +
    `<feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>` +
    `<filter id="${glowId}-part" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.6" result="b"/>` +
    `<feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>` +
    `<filter id="${idPrefix}-soft" filterUnits="userSpaceOnUse" x="${vx - 60}" y="${vy - 160}" width="${vw + 120}" height="${vh + 220}"><feGaussianBlur stdDeviation="6"/></filter>` +
    `<radialGradient id="${glassId}" cx=".5" cy=".35" r=".8"><stop offset="0" stop-color="#121a20"/><stop offset=".7" stop-color="#070a0d"/><stop offset="1" stop-color="#030405"/></radialGradient>` +
    `</defs>` +
    body +
    `</svg>`
  );
}

/**
 * Live face in a DOM container. Rebuilds only the light layers per frame, and
 * only animates while the expression needs it (plus an occasional blink).
 */
export function createSignalEngineerFace({ container, spec, partUrls, colors, idPrefix = 'se', now = () => performance.now() / 1000 }) {
  let expression = 'neutral';
  let level = 0;
  let current = { ...(colors || {}) };
  let raf = 0;
  let blinkUntil = 0;
  let nextBlink = now() + 3 + Math.random() * 3;
  let eyesEl = null;
  let mouthEl = null;
  let bobEls = [];
  let headEl = null;
  let fxEl = null;
  let speaking = false;
  let look = [0, 0];
  let nextGlance = now() + 2;

  function full() {
    container.innerHTML = renderFaceSvg(spec, { partUrls, expression, level, t: now(), speaking, look, colors: current, idPrefix });
    eyesEl = container.querySelector('[data-part="eyes"]');
    mouthEl = container.querySelector('[data-part="mouth"]');
    bobEls = [...container.querySelectorAll('[data-bob]')];
    headEl = container.querySelector('[data-head]');
    fxEl = container.querySelector('[data-fx-layer]');
  }

  function frame() {
    raf = 0;
    const t = now();
    if (t > nextBlink && expression !== 'sleeping') {
      blinkUntil = t + 0.13;
      nextBlink = t + 2.5 + Math.random() * 4;
    }
    if (t > nextGlance) {
      // Little eye darts so he never looks frozen; a talker glances more.
      look = Math.random() < 0.35 ? [0, 0] : [Math.random() * 2 - 1, (Math.random() * 2 - 1) * 0.6];
      nextGlance = t + (speaking ? 0.8 : 1.6) + Math.random() * 2.5;
    }
    const lights = renderLightsSvg(spec, { expression, level, t, blink: t < blinkUntil, speaking, look, colors: current, idPrefix });
    if (eyesEl) eyesEl.innerHTML = lights.eyes;
    if (mouthEl) mouthEl.innerHTML = lights.mouth;
    for (const el of bobEls) {
      el.setAttribute('transform', `translate(0 ${bobOffset(speaking ? 'talking' : expression, level, t, Number(el.dataset.bob))})`);
    }
    if (headEl) headEl.setAttribute('transform', headTransform(spec, { speaking, level, t }));
    if (fxEl) fxEl.innerHTML = renderFxSvg(spec, { fx: defaultFx(expression), t, idPrefix });
    schedule();
  }

  function schedule() {
    if (raf) return;
    const t = now();
    if (speaking || isAnimated(expression) || t < blinkUntil + 0.05) {
      raf = requestAnimationFrame(frame);
    } else {
      // Idle: wake for the next blink only.
      raf = setTimeout(() => { raf = 0; frame(); }, Math.max(16, (Math.min(nextBlink, nextGlance) - t) * 1000));
      raf = -raf; // mark as timeout
    }
  }

  function cancel() {
    if (raf > 0) cancelAnimationFrame(raf);
    else if (raf < 0) clearTimeout(-raf);
    raf = 0;
  }

  full();
  schedule();

  return {
    get expression() { return expression; },
    setExpression(next) {
      const e = EXPRESSIONS.includes(next) ? next : 'neutral';
      if (e === expression) return;
      expression = e;
      cancel();
      full(); // brows and colours change with the expression
      schedule();
    },
    setRingState(ringState) {
      this.setExpression(RING_STATE_EXPRESSION[ringState] || 'neutral');
    },
    /** Lip-sync on top of the current expression (e.g. while reading aloud). */
    setSpeaking(on) {
      speaking = Boolean(on);
      cancel();
      schedule();
    },
    setLevel(value) {
      level = typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
    },
    setColors(next) {
      current = { ...current, ...(next || {}) };
      cancel();
      full();
      schedule();
    },
    destroy() {
      cancel();
      container.innerHTML = '';
    },
  };
}
