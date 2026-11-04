// Signal Engineer face: the pure SVG builder and the spec it shares with
// tools/signal_engineer_parts.py.
//
// Run with: node --test app/tests/signalEngineerFace.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  EXPRESSIONS,
  RING_STATE_EXPRESSION,
  renderFaceSvg,
  renderLightsSvg,
  eyeGlyph,
  mouthGlyph,
  isAnimated,
} from '../src/renderer/lib/signalEngineerFace.mjs';
import { interpretOverlayStatus } from '../src/renderer/lib/overlayStatus.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const assets = resolve(here, '../src/renderer/assets/signal-engineer');
const spec = JSON.parse(readFileSync(join(assets, 'standard.parts.json'), 'utf8'));
const partUrls = Object.fromEntries(Object.keys(spec.parts).map((n) => [n, `${n}.png`]));

const rust = JSON.parse(readFileSync(join(assets, 'rustbucket.parts.json'), 'utf8'));
const rustUrls = Object.fromEntries(Object.keys(rust.parts).map((n) => [n, `${n}.png`]));
const SHELLS = { standard: spec, rustbucket: rust };

test('every part of every shell has its cut PNG checked in', () => {
  for (const [shell, s] of Object.entries(SHELLS)) {
    for (const name of Object.keys(s.parts)) {
      const file = join(assets, s.partsDir || '.', `${name}.png`);
      assert.ok(existsSync(file), `${shell}/${name}.png missing; run tools/signal_engineer_parts.py`);
    }
  }
});

test('every layout entry resolves to a part, a screen or a light layer', () => {
  for (const [shell, s] of Object.entries(SHELLS)) {
    for (const name of s.layout.order) {
      const ok = ['screens', 'eyes', 'mouth'].includes(name) || s.parts[name] || s.parts[s.layout[name]?.part];
      assert.ok(ok, `${shell}: layout '${name}' points at nothing`);
    }
  }
});

test('rustbucket renders every expression, mirrors reused beard pieces, and bobs them only while talking', () => {
  for (const expression of EXPRESSIONS) {
    const svg = renderFaceSvg(rust, { partUrls: rustUrls, expression, level: 0.8, t: 0.4 });
    assert.doesNotMatch(svg, /NaN|undefined|Infinity/, expression);
    for (const name of ['beardCenter', 'mustacheL', 'mustacheR', 'sideBeardL', 'sideBeardR']) {
      assert.ok(svg.includes(`data-part="${name}"`), `${expression} missing ${name}`);
    }
  }
  const talking = renderFaceSvg(rust, { partUrls: rustUrls, expression: 'talking', level: 1, t: 0.15 });
  assert.match(talking, /data-part="mustacheR" transform="[^"]*scale\(-0\.46 0\.46\)/);
  assert.equal((talking.match(/href="mustache\.png"/g) || []).length, 2, 'one mustache image, placed twice');
  assert.match(talking, /data-bob="6" transform="translate\(0 [1-9]/, 'beard drops while talking loud');
  const neutral = renderFaceSvg(rust, { partUrls: rustUrls, expression: 'neutral', level: 1, t: 0.15 });
  assert.match(neutral, /data-bob="6" transform="translate\(0 0\)"/);
});

test('every LED in the spec sits inside its part box (the cutter scrubs only there)', () => {
  for (const [name, part] of Object.entries(spec.parts)) {
    const [x0, y0, x1, y1] = part.box;
    for (const led of part.leds || []) {
      const pts = led.kind === 'arc' ? [[led.c[0] - led.r, led.c[1] - led.r], [led.c[0] + led.r, led.c[1] + led.r]] : led.pts;
      for (const [x, y] of pts) {
        assert.ok(x >= x0 && x <= x1 && y >= y0 && y <= y1, `${name}/${led.id} point ${x},${y} outside box`);
      }
    }
  }
});

test('every expression renders a complete SVG with no NaN/undefined', () => {
  for (const expression of EXPRESSIONS) {
    for (const t of [0, 0.73, 12.5]) {
      const svg = renderFaceSvg(spec, { partUrls, expression, level: 0.6, t });
      assert.match(svg, /^<svg [^>]*viewBox="-36 0 566 356"/);
      assert.ok(svg.endsWith('</svg>'));
      assert.doesNotMatch(svg, /NaN|undefined|Infinity/, `${expression} @ t=${t}`);
      for (const part of ['screens', 'eyes', 'mouth', ...Object.keys(spec.parts)]) {
        assert.ok(svg.includes(`data-part="${part}"`), `${expression} is missing ${part}`);
      }
      assert.ok(svg.includes(`data-expression="${expression}"`));
    }
  }
});

test('an unknown expression falls back to neutral', () => {
  assert.ok(renderFaceSvg(spec, { partUrls, expression: 'smug' }).includes('data-expression="neutral"'));
});

test('the glow filter is user-space, so flat lines (neutral mouth, sleeping eyes) are not clipped away', () => {
  const svg = renderFaceSvg(spec, { partUrls });
  assert.match(svg, /<filter id="se-glow" filterUnits="userSpaceOnUse"/);
});

test('no bar is zero-length (some renderers drop zero-length round caps)', () => {
  const g = eyeGlyph('sleeping', { cx: 0, cy: 0, w: 74, h: 52, side: -1 });
  for (const [, a, b] of g.d.matchAll(/M[\d.-]+,([\d.-]+) V([\d.-]+)/g)) {
    assert.ok(Math.abs(Number(b) - Number(a)) >= 1.4);
  }
});

test('every ring state the overlay can produce maps to a real expression', () => {
  const statuses = ['recording', 'listening', 'transcribing', 'chunking_stitching', 'preview_ready',
    'emergency_stop', 'draft_error', 'idle', 'something_new'];
  for (const s of statuses) {
    const { ring } = interpretOverlayStatus(s, {});
    const expr = RING_STATE_EXPRESSION[ring] || 'neutral';
    assert.ok(EXPRESSIONS.includes(expr), `${s} -> ${ring} -> ${expr}`);
  }
});

test('listening reacts to the mic level; silence is visibly smaller than speech', () => {
  const quiet = eyeGlyph('listening', { cx: 0, cy: 0, w: 74, h: 52, side: -1, level: 0, t: 1 });
  const loud = eyeGlyph('listening', { cx: 0, cy: 0, w: 74, h: 52, side: -1, level: 1, t: 1 });
  const span = (d) => [...d.matchAll(/M[\d.-]+,([\d.-]+) V([\d.-]+)/g)].reduce((s, [, a, b]) => s + Math.abs(b - a), 0);
  assert.ok(span(loud.d) > span(quiet.d) * 1.8);
  const talkQuiet = mouthGlyph('talking', { cx: 0, cy: 0, w: 170, h: 36, level: 0, t: 2 });
  const talkLoud = mouthGlyph('talking', { cx: 0, cy: 0, w: 170, h: 36, level: 1, t: 2 });
  assert.ok(span(talkLoud.d) > span(talkQuiet.d));
});

test('expression colours: rage is red, love is pink, the rest follow the accent', () => {
  assert.ok(renderLightsSvg(spec, { expression: 'rage' }).eyes.includes('#ff3b3b'));
  assert.ok(renderLightsSvg(spec, { expression: 'love' }).mouth.includes('#ff6fb5'));
  assert.ok(renderLightsSvg(spec, { expression: 'neutral', colors: { accent: '#123456' } }).eyes.includes('#123456'));
});

test('only moving expressions request animation frames', () => {
  assert.deepEqual(EXPRESSIONS.filter(isAnimated).sort(), ['glitch', 'listening', 'rage', 'talking', 'thinking']);
});

test('ids are prefixed so two faces on one page do not share filters', () => {
  const a = renderFaceSvg(spec, { partUrls, idPrefix: 'a' });
  assert.ok(a.includes('id="a-glow"') && a.includes('url(#a-glow)') && !a.includes('se-glow'));
});

// --- character: acting while talking, gaze, head motion, effects -------------

test('speaking lip-syncs the mouth without replacing the expression', () => {
  const sus = renderLightsSvg(spec, { expression: 'suspicious', speaking: true, level: 0.8, t: 1 });
  const plain = renderLightsSvg(spec, { expression: 'suspicious', level: 0.8, t: 1 });
  assert.notEqual(sus.mouth, plain.mouth, 'mouth should be the talking waveform');
  assert.equal(sus.eyes, plain.eyes, 'eyes keep the suspicious glyph');
  assert.ok(sus.eyes.includes('#ffb02e'), 'and its amber colour');
});

test('look moves the eyes; head motion only sways while speaking', () => {
  const ahead = renderLightsSvg(spec, { look: [0, 0] }).eyes;
  const right = renderLightsSvg(spec, { look: [1, 0] }).eyes;
  assert.notEqual(ahead, right);
  const still = renderFaceSvg(spec, { partUrls, t: 1.3 });
  assert.match(still, /data-head="1" transform="translate\([\d.]+ [\d.]+\) rotate\(0\) scale\(1\)/);
  const talking = renderFaceSvg(spec, { partUrls, t: 1.3, speaking: true, level: 0.9 });
  assert.doesNotMatch(talking, /data-head="1" transform="[^"]*rotate\(0\)/);
});

test('rage vents steam and glitch throws sparks by default; explicit fx wins', () => {
  assert.ok(renderFaceSvg(rust, { partUrls: rustUrls, expression: 'rage', t: 1 }).includes('data-fx="steam"'));
  assert.ok(renderFaceSvg(rust, { partUrls: rustUrls, expression: 'glitch', t: 1 }).includes('data-fx="sparks"'));
  assert.ok(!renderFaceSvg(rust, { partUrls: rustUrls, expression: 'happy', t: 1 }).includes('data-fx='));
  assert.ok(renderFaceSvg(rust, { partUrls: rustUrls, expression: 'happy', t: 1, fx: { steam: 0.5 } }).includes('data-fx="steam"'));
});

test('the SVG is valid XML: no valueless attributes (standalone exports must parse)', () => {
  for (const [s, urls] of [[spec, partUrls], [rust, rustUrls]]) {
    for (const expression of EXPRESSIONS) {
      const svg = renderFaceSvg(s, { partUrls: urls, expression, speaking: true, level: 0.5, t: 2 });
      for (const tag of svg.match(/<[a-zA-Z][^>]*>/g)) {
        const attrs = tag.replace(/^<[a-zA-Z]+/, '').replace(/\/?>$/, '').replace(/\s[\w:-]+="[^"]*"/g, '');
        assert.equal(attrs.trim(), '', `bad attributes in ${tag.slice(0, 80)}`);
      }
    }
  }
});

// --- read-aloud ---------------------------------------------------------------

import { syntheticSpeechLevel } from '../src/renderer/lib/signalEngineerFace.mjs';

test('read-aloud statuses get readable labels and leave the ring idle', () => {
  assert.deepEqual(interpretOverlayStatus('draft_tts_started'), { ring: 'idle', text: 'Reading aloud...' });
  assert.deepEqual(interpretOverlayStatus('draft_tts_stopped'), { ring: 'idle', text: 'Done reading' });
});

test('synthetic speech level is bounded, varies like syllables, and breathes', () => {
  const xs = Array.from({ length: 600 }, (_, i) => syntheticSpeechLevel(i / 60));
  assert.ok(xs.every((x) => x >= 0 && x <= 1));
  const loud = xs.filter((x) => x > 0.5).length;
  const quiet = xs.filter((x) => x < 0.1).length;
  assert.ok(loud > 60 && quiet > 60, `needs both open and closed mouth frames (${loud} loud, ${quiet} quiet)`);
  assert.equal(syntheticSpeechLevel(1.234), syntheticSpeechLevel(1.234), 'deterministic');
});
