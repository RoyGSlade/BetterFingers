import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// Onboarding delays feature initialization: the shipped HTML itself is visible
// behind consent. A mounted renderer fake would miss this first-run regression.
const html = fs.readFileSync(new URL('../src/renderer/signal-desk.html', import.meta.url), 'utf8');
const initialText = id => html.match(new RegExp(`id="${id}"[^>]*>([^<]*)<`))?.[1];

test('before consent, the microphone status makes no claim of capture', () => {
  assert.equal(initialText('sdSignalCoreStatusLabel'), 'Idle');
  assert.equal(initialText('sdSignalCoreStatusDetail'), 'Waiting for input');
});

test('before a measured amplitude, the meter has no fabricated reading or level', () => {
  assert.equal(initialText('sdSignalCoreMeterValue'), '—');
  const bar = html.match(/<span\b[^>]*id="sdSignalCoreMeterBar"[^>]*>/)?.[0];
  assert.ok(bar, 'meter bar must exist');
  assert.match(bar, /style="[^"]*--sd-meter-level:\s*0%;/);
});
