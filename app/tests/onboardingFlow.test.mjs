// First-run onboarding on the guided-flow shell (features/onboardingFlow.js).
//
// The consequential rules here are consent and the completion flag: a bug that
// lets the gate be walked past is a consent failure, and a bug that writes the
// flag too early means a user never sees the policy at all.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ONBOARDING_FLAG,
  buildOnboardingSteps,
  collectOnboardingElements,
  createOnboardingFlow,
  markOnboardingComplete,
  renderRecommendation,
  shouldShowOnboarding,
  speechModelState,
} from '../src/renderer/features/onboardingFlow.js';
import { canAdvanceFrom } from '../src/renderer/features/guidedFlow.js';

function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    dump: () => Object.fromEntries(map),
  };
}

const throwingStorage = {
  getItem() { throw new Error('storage disabled'); },
  setItem() { throw new Error('storage disabled'); },
};

// --- gating flag -------------------------------------------------------------

test('onboarding shows until the flag is set', () => {
  assert.equal(shouldShowOnboarding(memoryStorage()), true);
  assert.equal(shouldShowOnboarding(memoryStorage({ [ONBOARDING_FLAG]: 'true' })), false);
});

test('a broken storage shows onboarding rather than skipping it', () => {
  // Showing the policy twice is an annoyance; skipping it is a consent failure.
  assert.equal(shouldShowOnboarding(throwingStorage), true);
});

test('marking complete reports whether it persisted', () => {
  const storage = memoryStorage();
  assert.equal(markOnboardingComplete(storage), true);
  assert.equal(storage.dump()[ONBOARDING_FLAG], 'true');
  assert.equal(markOnboardingComplete(throwingStorage), false);
});

// --- steps -------------------------------------------------------------------

test('only the consent step gates', () => {
  const steps = buildOnboardingSteps({ isConsented: () => false });
  assert.deepEqual(steps.map((s) => s.id), ['welcome', 'consent', 'how', 'models']);
  assert.equal(canAdvanceFrom(0, steps), true);
  assert.equal(canAdvanceFrom(1, steps), false, 'consent must gate');
  assert.equal(canAdvanceFrom(2, steps), true);
  assert.equal(canAdvanceFrom(3, steps), true);
});

test('consent releases the gate once checked', () => {
  let checked = false;
  const steps = buildOnboardingSteps({ isConsented: () => checked });
  assert.equal(canAdvanceFrom(1, steps), false);
  checked = true;
  assert.equal(canAdvanceFrom(1, steps), true);
});

// --- speech-model state ------------------------------------------------------

test('a model counts as present when downloaded or installed', () => {
  assert.equal(speechModelState({ models: [{ downloaded: true }] }), 'present');
  assert.equal(speechModelState({ models: [{ installed: true }] }), 'present');
  assert.equal(speechModelState({ models: [{ downloaded: false }] }), 'missing');
});

test('an unusable payload reads as missing, not present', () => {
  // Telling a user with no model that they are ready to go is the worse of the
  // two wrong answers -- they would go and find nothing works.
  assert.equal(speechModelState(undefined), 'missing');
  assert.equal(speechModelState({}), 'missing');
  assert.equal(speechModelState({ models: 'nope' }), 'missing');
});

// --- recommendation rendering ------------------------------------------------

function fakeDoc() {
  const make = (tag) => ({
    tag,
    className: '',
    children: [],
    hidden: false,
    set textContent(v) { this._text = v; this.children = v === '' ? [] : this.children; },
    get textContent() {
      if (this.children.length) {
        return this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join('');
      }
      return this._text ?? '';
    },
    append(...nodes) { this.children.push(...nodes.flatMap((n) => (n?.tag === '#fragment' ? n.children : [n]))); },
  });
  return {
    createElement: make,
    createDocumentFragment: () => make('#fragment'),
  };
}

test('the recommendation renders backend text as text, never markup', () => {
  const doc = fakeDoc();
  const box = doc.createElement('div');
  box.hidden = true;
  const ok = renderRecommendation(box, {
    recommendation: {
      tier_label: '<img src=x onerror=alert(1)>',
      llm: { recommended: 'a', models: [{ id: 'a', name: 'Model A', note: 'fast' }] },
      whisper: { recommended: 'base.en' },
    },
  }, doc);

  assert.equal(ok, true);
  assert.equal(box.hidden, false);
  const text = box.textContent;
  // Present as literal characters in a text node -- no element was created for
  // it, which is the whole point of building this with createElement.
  assert.match(text, /<img src=x onerror=alert\(1\)>/);
  assert.match(text, /Model A — fast/);
  assert.match(text, /base\.en/);
});

test('no recommendation leaves the box hidden', () => {
  const doc = fakeDoc();
  const box = doc.createElement('div');
  box.hidden = true;
  assert.equal(renderRecommendation(box, {}, doc), false);
  assert.equal(box.hidden, true, 'an empty box must not be revealed');
});

// --- wiring ------------------------------------------------------------------

function makeEl(extra = {}) {
  const listeners = {};
  return {
    hidden: false,
    disabled: false,
    checked: false,
    textContent: '',
    dataset: {},
    isConnected: true,
    offsetParent: {},
    addEventListener: (evt, fn) => { (listeners[evt] ||= []).push(fn); },
    removeEventListener: () => {},
    setAttribute(name, value) { (this.attrs ||= {})[name] = value; },
    focus() { this.focused = true; },
    fire: (evt) => (listeners[evt] || []).forEach((fn) => fn()),
    ...extra,
  };
}

function harness({ storage = memoryStorage(), hooks = {} } = {}) {
  const primary = makeEl();
  const back = makeEl();
  const title = makeEl();
  const progress = makeEl();
  const consent = makeEl();
  const decline = makeEl();
  const recommendation = makeEl();
  const modelsPresent = makeEl();
  const modelsMissing = makeEl();
  const stepEls = [makeEl(), makeEl(), makeEl(), makeEl()];
  const dots = [makeEl(), makeEl(), makeEl(), makeEl()];

  const root = {
    hidden: true,
    querySelector: (sel) => ({
      '[data-flow-primary]': primary,
      '[data-flow-back]': back,
      '[data-flow-title]': title,
      '[data-flow-progress]': progress,
    }[sel] ?? null),
    querySelectorAll: (sel) => ({
      '[data-flow-step]': stepEls,
      '[data-flow-dot]': dots,
    }[sel] ?? []),
  };

  const doc = {
    activeElement: null,
    addEventListener() {},
    removeEventListener() {},
  };

  const elements = {
    root, consent, decline, recommendation, modelsPresent, modelsMissing,
  };
  const onboarding = createOnboardingFlow({ elements, storage, hooks, doc });
  return { onboarding, root, primary, back, title, progress, consent, decline, recommendation, modelsPresent, modelsMissing, stepEls, storage };
}

test('init opens the flow on a fresh profile and reports that it did', () => {
  const h = harness();
  assert.equal(h.onboarding.init(), true);
  assert.equal(h.root.hidden, false);
  assert.equal(h.primary.textContent, 'Get started');
});

test('init is a no-op once onboarding is complete', () => {
  const h = harness({ storage: memoryStorage({ [ONBOARDING_FLAG]: 'true' }) });
  assert.equal(h.onboarding.init(), false);
  assert.equal(h.root.hidden, true, 'a returning user must not meet the modal');
});

test('the consent step disables the primary button until the box is ticked', () => {
  const h = harness();
  h.onboarding.init();
  h.primary.fire('click');                       // welcome -> consent
  assert.equal(h.onboarding.flow.getIndex(), 1);
  assert.equal(h.primary.disabled, true, 'consent must not be walked past');

  h.primary.fire('click');
  assert.equal(h.onboarding.flow.getIndex(), 1, 'clicking a dead button must not advance');

  h.consent.checked = true;
  h.consent.fire('change');
  assert.equal(h.primary.disabled, false, 'ticking the box must release the gate live');
  h.primary.fire('click');
  assert.equal(h.onboarding.flow.getIndex(), 2);
});

test('the consent gate is live even when the flow is opened without init()', () => {
  // Found by QA: binding on init() left the dialog half-live for anyone who
  // opened it another way -- steps advanced, but the checkbox was inert, which
  // is indistinguishable from a gate that can never be satisfied.
  const h = harness({ storage: memoryStorage({ [ONBOARDING_FLAG]: 'true' }) });
  h.onboarding.flow.open(1);
  assert.equal(h.primary.disabled, true);
  h.consent.checked = true;
  h.consent.fire('change');
  assert.equal(h.primary.disabled, false, 'consent checkbox not bound');
});

test('the flag is written only at the end, never on the way through', () => {
  const h = harness();
  h.onboarding.init();
  h.consent.checked = true;
  h.primary.fire('click');   // -> consent
  h.primary.fire('click');   // -> how
  assert.equal(h.storage.dump()[ONBOARDING_FLAG], undefined, 'flag written mid-flow');

  h.primary.fire('click');   // -> models
  h.primary.fire('click');   // finish
  assert.equal(h.storage.dump()[ONBOARDING_FLAG], 'true');
  assert.equal(h.root.hidden, true);
});

test('Decline & quit quits and does not mark onboarding complete', () => {
  // Otherwise declining once would permanently skip the policy on next launch.
  const quits = [];
  const h = harness({ hooks: { quitApp: () => quits.push('quit') } });
  h.onboarding.init();
  h.decline.fire('click');
  assert.deepEqual(quits, ['quit']);
  assert.equal(h.storage.dump()[ONBOARDING_FLAG], undefined);
});

test('the speech-models step reflects live model state', async () => {
  const h = harness({ hooks: { fetchWhisperModels: async () => ({ models: [{ downloaded: true }] }) } });
  h.onboarding.init();
  h.consent.checked = true;
  h.primary.fire('click');
  h.primary.fire('click');
  h.primary.fire('click');   // -> models
  await new Promise((r) => setImmediate(r));
  assert.equal(h.modelsPresent.hidden, false);
  assert.equal(h.modelsMissing.hidden, true);
});

test('a failing model probe says "missing", not "ready to go"', async () => {
  const h = harness({ hooks: { fetchWhisperModels: async () => { throw new Error('backend down'); } } });
  h.onboarding.init();
  h.consent.checked = true;
  h.primary.fire('click');
  h.primary.fire('click');
  h.primary.fire('click');
  await new Promise((r) => setImmediate(r));
  assert.equal(h.modelsMissing.hidden, false);
  assert.equal(h.modelsPresent.hidden, true);
});

test('progress is announced positionally, not just drawn', () => {
  const h = harness();
  h.onboarding.init();
  assert.equal(h.progress.attrs['aria-label'], 'Step 1 of 4');
  h.primary.fire('click');
  assert.equal(h.progress.attrs['aria-label'], 'Step 2 of 4');
});

test('collectOnboardingElements looks up the documented ids', () => {
  const seen = [];
  const doc = { getElementById: (id) => { seen.push(id); return { id }; } };
  const els = collectOnboardingElements(doc);
  assert.deepEqual(seen, [
    'sdOnboarding',
    'sdOnboardConsent',
    'sdOnboardDecline',
    'sdOnboardRecommendation',
    'sdOnboardModelsPresent',
    'sdOnboardModelsMissing',
  ]);
  assert.equal(els.root.id, 'sdOnboarding');
});
