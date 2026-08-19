import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  QUICK_SETUP_STEPS,
  QUICK_SETUP_STORAGE_KEY,
  createQuickSetupTour,
  hasSeenQuickSetup,
  markQuickSetupSeen,
} from '../src/renderer/features/quickSetupTour.js';
import { makeDocument, makeLocalStorage } from './helpers/rendererDom.mjs';

function makeHarness({ reducedMotion = false } = {}) {
  const doc = makeDocument();
  const documentListeners = new Map();
  doc.defaultView = {
    matchMedia: () => ({ matches: reducedMotion }),
  };
  doc.addEventListener = (type, handler) => {
    if (!documentListeners.has(type)) documentListeners.set(type, []);
    documentListeners.get(type).push(handler);
  };
  doc.removeEventListener = (type, handler) => {
    const listeners = documentListeners.get(type) || [];
    const index = listeners.indexOf(handler);
    if (index >= 0) listeners.splice(index, 1);
  };
  doc.emit = (type, event = {}) => {
    for (const handler of [...(documentListeners.get(type) || [])]) handler(event);
  };

  const priorFocus = doc.createElement('button');
  priorFocus.isConnected = true;
  doc.body.append(priorFocus);
  priorFocus.focus();

  const targets = new Map();
  for (const step of QUICK_SETUP_STEPS) {
    const target = doc.createElement('button');
    target.setAttribute('data-tour-target', step.id);
    target.isConnected = true;
    target.scrollCalls = [];
    target.scrollIntoView = (options) => target.scrollCalls.push(options);
    doc.body.append(target);
    targets.set(step.id, target);
  }

  const storage = makeLocalStorage();
  const navigated = [];
  const tour = createQuickSetupTour({
    doc,
    storage,
    navigate: (step) => navigated.push(step),
  });
  return { doc, navigated, priorFocus, storage, targets, tour };
}

test('quick setup contains the seven approved destinations', () => {
  assert.deepEqual(
    QUICK_SETUP_STEPS.map(({ id }) => id),
    ['talk', 'speech', 'models', 'recording', 'review', 'cleanup', 'privacy'],
  );
  assert.match(QUICK_SETUP_STEPS[0].body, /\?/);
  assert.match(QUICK_SETUP_STEPS[6].body, /replay/i);
});

test('quick setup persistence is versioned', () => {
  const storage = makeLocalStorage();
  assert.equal(QUICK_SETUP_STORAGE_KEY, 'bf_quick_setup_v1_seen');
  assert.equal(hasSeenQuickSetup(storage), false);
  markQuickSetupSeen(storage);
  assert.equal(hasSeenQuickSetup(storage), true);
});

test('open, Next, Back, and Skip navigate real targets and clean up focus/highlight', () => {
  const { doc, navigated, priorFocus, storage, targets, tour } = makeHarness();
  const next = tour.root.querySelector('[data-action="next"]');
  const back = tour.root.querySelector('[data-action="back"]');
  const skip = tour.root.querySelector('[data-action="skip"]');

  tour.open();
  assert.equal(tour.isOpen(), true);
  assert.deepEqual(navigated, ['talk']);
  assert.equal(targets.get('talk').classList.contains('bf-quick-setup-target'), true);
  assert.equal(doc.activeElement, next, 'tour navigation keeps keyboard focus on its primary action');
  assert.equal(back.disabled, true);

  next.emit('click');
  assert.deepEqual(navigated, ['talk', 'speech']);
  assert.equal(targets.get('talk').classList.contains('bf-quick-setup-target'), false);
  assert.equal(targets.get('speech').classList.contains('bf-quick-setup-target'), true);
  assert.equal(back.disabled, false);

  back.emit('click');
  assert.deepEqual(navigated, ['talk', 'speech', 'talk']);
  skip.emit('click');
  assert.equal(tour.isOpen(), false);
  assert.equal(storage.getItem(QUICK_SETUP_STORAGE_KEY), '1');
  assert.equal(targets.get('talk').classList.contains('bf-quick-setup-target'), false);
  assert.equal(doc.activeElement, priorFocus);
});

test('Done closes and marks the tour seen', () => {
  const { storage, tour } = makeHarness();
  const next = tour.root.querySelector('[data-action="next"]');
  tour.open();
  for (let step = 1; step < QUICK_SETUP_STEPS.length; step += 1) next.emit('click');
  assert.equal(next.textContent, 'Done');
  assert.equal(tour.isOpen(), true);
  next.emit('click');
  assert.equal(tour.isOpen(), false);
  assert.equal(storage.getItem(QUICK_SETUP_STORAGE_KEY), '1');
});

test('document-level Escape skips even when focus is outside the coachmark', () => {
  const { doc, storage, targets, tour } = makeHarness();
  tour.open();
  targets.get('talk').focus();
  let prevented = false;
  doc.emit('keydown', { key: 'Escape', preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(tour.isOpen(), false);
  assert.equal(storage.getItem(QUICK_SETUP_STORAGE_KEY), '1');
});

test('reduced-motion users receive non-animated target scrolling', () => {
  const { targets, tour } = makeHarness({ reducedMotion: true });
  tour.open();
  assert.equal(targets.get('talk').scrollCalls[0].behavior, 'auto');
});

test('bootstrap starts only after durable consent and for already-consented users', () => {
  const source = fs.readFileSync(
    new URL('../src/renderer/bootstrap/signalDeskApp.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /onComplete:\s*maybeStartQuickSetup/);
  assert.match(source, /if \(!gate\.show\) maybeStartQuickSetup\(\)/);
  assert.doesNotMatch(source, /onboarding\?\.isComplete/);
});

test('Signal Desk ships no fabricated global bindings and explains every hotkey', () => {
  const source = fs.readFileSync(
    new URL('../src/renderer/signal-desk.html', import.meta.url),
    'utf8',
  );
  assert.doesNotMatch(source, /Hold Ctrl \+ Space/);
  assert.doesNotMatch(source, /value="(?:Ctrl\+Space|Escape|Ctrl\+Enter|Ctrl\+R|Ctrl\+Alt\+R|Ctrl\+G|Ctrl\+M)"/);
  for (const phrase of [
    'In Toggle mode, press once to start or stop recording',
    'Stops recording, transcription, automated typing, and text-to-speech immediately.',
    'Pastes the oldest pending draft',
    'Starts or stops text-to-speech for the current review draft.',
    'Creates a cleaned, review-only draft from selected text',
    'simulates this app-specific key before pasting',
    'holds this key while recording when push-to-mute is enabled',
  ]) {
    assert.ok(source.includes(phrase), `missing hotkey explanation: ${phrase}`);
  }
});
