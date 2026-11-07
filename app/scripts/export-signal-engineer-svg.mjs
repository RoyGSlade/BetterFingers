#!/usr/bin/env node
// Write standalone Signal Engineer SVGs (parts embedded as data: URIs) using the
// same renderer the overlay uses.
//
//   node scripts/export-signal-engineer-svg.mjs [--shell standard] [--out dir] [--expression neutral|all]
//
// Output: <out>/signal-engineer-<shell>-<expression>.svg (default out: ./signal-engineer-export).
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderFaceSvg, EXPRESSIONS } from '../src/renderer/lib/signalEngineerFace.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const assets = resolve(here, '../src/renderer/assets/signal-engineer');

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const shell = arg('shell', 'standard');
const out = resolve(arg('out', 'signal-engineer-export'));
const which = arg('expression', 'all');

const spec = JSON.parse(readFileSync(join(assets, `${shell}.parts.json`), 'utf8'));
const partUrls = {};
for (const name of Object.keys(spec.parts)) {
  const png = readFileSync(join(assets, spec.partsDir || '.', `${name}.png`));
  partUrls[name] = `data:image/png;base64,${png.toString('base64')}`;
}

mkdirSync(out, { recursive: true });
const list = which === 'all' ? EXPRESSIONS : [which];
for (const expression of list) {
  // A mid-level, mid-animation frame so animated expressions export a lively still.
  const svg = renderFaceSvg(spec, { partUrls, expression, level: 0.7, t: 1.37 });
  const file = join(out, `signal-engineer-${shell}-${expression}.svg`);
  writeFileSync(file, svg);
  console.log(`${file}  ${Math.round(svg.length / 1024)} KB`);
}
