// Unit tests for the Studio workspace wiring adapter's PURE helpers
// (docs/ui/SIGNAL_DESK_SPEC.md section 6). Mirrors libraryWorkspace.test.mjs's
// approach: only the DOM-free "data -> view model" logic is exercised here
// (persona signature-color mapping, trait/slider value mapping, reliability
// bar mapping, blend-weight normalization, description/heading heuristics) --
// createStudioWorkspaceFeature()'s DOM wiring itself needs a real document
// and is exercised manually via signal-desk-preview.html per the phase brief.
//
// Run with: node --test app/tests/studioWorkspace.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  TRAIT_KEYS,
  NEUTRAL_TRAITS,
  PERSONA_SIGNATURE_COLOR_VARS,
  personaSignatureKey,
  personaSignatureColorVar,
  clampPercent,
  derivePersonaTraits,
  traitsAreUnknown,
  reliabilityPercentFromPersona,
  reliabilityBarWidth,
  exampleCountFromPersona,
  derivePersonaDescription,
  buildWhyThisWorksBullets,
  wordCountLabel,
  guessToneLabel,
  outputColumnHeading,
  isBuiltinPersonaName,
  deriveNextPersonaCopyName,
  deriveVoiceBlendCards,
  normalizeStudioBlend,
  STRESS_TEST_SAMPLES,
  STUDIO_ELEMENT_IDS,
  collectStudioElements,
  createStudioWorkspaceFeature,
  contactsPreferring,
  traitBandLabel,
  STUDIO_PLACEMENT_MAP,
  PERSONA_TRAITS_STATUS,
  personaTraitsDisclosureLines,
} from '../src/renderer/features/studioWorkspace.js';
import { installDomGlobals, makeBackendBridge, makeDocument } from './helpers/rendererDom.mjs';

// --- personaSignatureKey / personaSignatureColorVar --------------------------

test('personaSignatureColorVar: the 5 SPEC 2 archetypes map to their exact colors', () => {
  assert.equal(personaSignatureColorVar('Natural'), 'var(--sd-persona-natural)');
  assert.equal(personaSignatureColorVar('Direct'), 'var(--sd-persona-direct)');
  assert.equal(personaSignatureColorVar('Warm'), 'var(--sd-persona-warm)');
  assert.equal(personaSignatureColorVar('Professional'), 'var(--sd-persona-professional)');
  assert.equal(personaSignatureColorVar('Playful'), 'var(--sd-persona-playful)');
});

test('personaSignatureColorVar: matching is case-insensitive', () => {
  assert.equal(personaSignatureColorVar('NATURAL'), 'var(--sd-persona-natural)');
  assert.equal(personaSignatureColorVar('warm'), 'var(--sd-persona-warm)');
  assert.equal(personaSignatureColorVar('  Direct  '.trim()), 'var(--sd-persona-direct)');
});

test('personaSignatureColorVar: an unknown/custom persona name still resolves to one of the 5 known colors', () => {
  const color = personaSignatureColorVar('True Janitor');
  assert.ok(Object.values(PERSONA_SIGNATURE_COLOR_VARS).includes(color));
});

test('personaSignatureKey: unknown names are deterministic (same name -> same bucket every call)', () => {
  const a = personaSignatureKey('Pompous 1800s Lord');
  const b = personaSignatureKey('Pompous 1800s Lord');
  assert.equal(a, b);
});

test('personaSignatureKey: different unknown names can land in different buckets (not all collapsed to one default)', () => {
  const names = ['True Janitor', 'Formal', 'Polished', 'Unhinged', 'Pompous 1800s Lord', 'Bob', 'Zara', 'Custom Persona 9'];
  const buckets = new Set(names.map((n) => personaSignatureKey(n)));
  // Not asserting exact distribution (hash-based) -- just that the fallback
  // isn't degenerate (everything landing on the same single bucket).
  assert.ok(buckets.size > 1, `expected more than one distinct bucket, got: ${[...buckets]}`);
});

test('personaSignatureColorVar: empty/undefined name still returns a valid color, never throws', () => {
  assert.ok(Object.values(PERSONA_SIGNATURE_COLOR_VARS).includes(personaSignatureColorVar(undefined)));
  assert.ok(Object.values(PERSONA_SIGNATURE_COLOR_VARS).includes(personaSignatureColorVar('')));
});

// --- clampPercent / derivePersonaTraits (slider value mapping) ---------------

test('clampPercent: clamps into [0,100] and rounds', () => {
  assert.equal(clampPercent(50.4), 50);
  assert.equal(clampPercent(50.6), 51);
  assert.equal(clampPercent(-10), 0);
  assert.equal(clampPercent(150), 100);
});

test('clampPercent: non-finite input falls back to the given default', () => {
  assert.equal(clampPercent(undefined, 42), 42);
  assert.equal(clampPercent(null, 42), 42);
  assert.equal(clampPercent(NaN, 42), 42);
  assert.equal(clampPercent('not a number', 7), 7);
});

test('derivePersonaTraits: reports null per axis when the backend supplies nothing', () => {
  // No persona schema field supplies traits, so any number here is invented.
  // This used to return numbers from a TRAIT_PRESETS table keyed to the
  // mockup's archetype names -- names that are not this app's real builtins,
  // so every real persona rendered either a flat 50 or another persona's
  // shape, presented as though measured.
  const traits = derivePersonaTraits({});
  for (const key of TRAIT_KEYS) {
    assert.ok(key in traits, `${key} should still be reported`);
    assert.equal(traits[key], null, `${key} must be null, not an invented number`);
  }
});

test('derivePersonaTraits: a persona name can never conjure trait values', () => {
  // The old behaviour: naming a persona "Natural" gave it the mockup's numbers.
  for (const name of ['Natural', 'Direct', 'Warm', 'Professional', 'Playful', 'True Janitor']) {
    const traits = derivePersonaTraits({}, name);
    assert.ok(traitsAreUnknown(traits), `"${name}" fabricated traits from its name alone`);
  }
});

test('derivePersonaTraits: an explicit persona.traits field is read, per-key', () => {
  // Future-proofing: when the schema gains user-authored traits, this already
  // reads them -- and axes the user has not set stay unknown rather than
  // defaulting to a middle value they never chose.
  const traits = derivePersonaTraits({ traits: { warmth: 90 } });
  assert.equal(traits.warmth, 90);
  assert.equal(traits.directness, null);
});

test('derivePersonaTraits: an explicit traits value is still clamped', () => {
  const traits = derivePersonaTraits({ traits: { confidence: 500, formality: -20 } });
  assert.equal(traits.confidence, 100);
  assert.equal(traits.formality, 0);
});

test('buildWhyThisWorksBullets: says nothing when there are no traits to reason from', () => {
  // Each bullet is a claim ABOUT the traits. With none, spreading nulls over
  // NEUTRAL_TRAITS would emit the else-branch of every test as if measured.
  assert.deepEqual(buildWhyThisWorksBullets(derivePersonaTraits({})), []);
  assert.deepEqual(buildWhyThisWorksBullets({}), []);
  assert.deepEqual(buildWhyThisWorksBullets(null), []);
});

// --- reliabilityPercentFromPersona / reliabilityBarWidth ---------------------

test('reliabilityPercentFromPersona: reads persona_card.reliability_score when present', () => {
  assert.equal(reliabilityPercentFromPersona({ persona_card: { reliability_score: 94 } }), 94);
});

test('reliabilityPercentFromPersona: returns null (not a fabricated 0) when absent -- a manually-built persona has no persona_card', () => {
  assert.equal(reliabilityPercentFromPersona({}), null);
  assert.equal(reliabilityPercentFromPersona(null), null);
  assert.equal(reliabilityPercentFromPersona({ persona_card: {} }), null);
});

test('reliabilityPercentFromPersona: a non-numeric score is treated as absent rather than crashing', () => {
  assert.equal(reliabilityPercentFromPersona({ persona_card: { reliability_score: 'high' } }), null);
});

test('reliabilityBarWidth: formats a percent CSS width string, 0% for null/unknown', () => {
  assert.equal(reliabilityBarWidth(94), '94%');
  assert.equal(reliabilityBarWidth(null), '0%');
  assert.equal(reliabilityBarWidth(undefined), '0%');
  assert.equal(reliabilityBarWidth(150), '100%');
});

// --- exampleCountFromPersona --------------------------------------------------

test('exampleCountFromPersona: sums few_shot + eval_cases + the caller-supplied learned-example count', () => {
  const persona = {
    few_shot: [{ raw: 'a', out: 'b' }, { raw: 'c', out: 'd' }],
    persona_card: { eval_cases: [{ input: 'x', output: 'y', verdict: 'approved' }] },
  };
  assert.equal(exampleCountFromPersona(persona, 5), 2 + 1 + 5);
});

test('exampleCountFromPersona: missing fields count as zero, never throws', () => {
  assert.equal(exampleCountFromPersona({}), 0);
  assert.equal(exampleCountFromPersona(null), 0);
  assert.equal(exampleCountFromPersona(undefined, -3), 0); // negative learned count clamps to 0
});

// --- derivePersonaDescription -------------------------------------------------

test('derivePersonaDescription: Natural gets the exact mockup 03 copy', () => {
  assert.equal(
    derivePersonaDescription({}, 'Natural'),
    'Conversational, clear, and friendly. Balances warmth with clarity to help messages feel human and easy to read.',
  );
});

test('derivePersonaDescription: a Foundry-compiled persona (has persona_card.archetype) builds a description from it', () => {
  const desc = derivePersonaDescription({ persona_card: { archetype: 'The Sardonic Editor', temperament: ['dry', 'precise'] } }, 'Custom One');
  assert.equal(desc, 'The Sardonic Editor (dry, precise).');
});

test('derivePersonaDescription: no archetype and no known name -> honest "not set" fallback, not fabricated text', () => {
  assert.equal(derivePersonaDescription({}, 'True Janitor'), 'Custom persona — no description set yet.');
});

// --- buildWhyThisWorksBullets -------------------------------------------------

test('buildWhyThisWorksBullets: returns at most 3 bullets', () => {
  const bullets = buildWhyThisWorksBullets(NEUTRAL_TRAITS);
  assert.ok(bullets.length <= 3);
  assert.ok(bullets.length > 0);
});

test('buildWhyThisWorksBullets: high-directness traits mention clarity/flow; low-directness keeps original phrasing', () => {
  const highDirectness = buildWhyThisWorksBullets({ ...NEUTRAL_TRAITS, directness: 90 });
  const lowDirectness = buildWhyThisWorksBullets({ ...NEUTRAL_TRAITS, directness: 10 });
  assert.equal(highDirectness[0], 'Adds clarity and flow');
  assert.equal(lowDirectness[0], 'Keeps phrasing close to what you said');
});

// --- wordCountLabel / guessToneLabel / outputColumnHeading --------------------

test('wordCountLabel: singular/plural and empty text', () => {
  assert.equal(wordCountLabel('hello'), '1 word');
  assert.equal(wordCountLabel('I will be there'), '4 words');
  assert.equal(wordCountLabel(''), '0 words');
  assert.equal(wordCountLabel('   '), '0 words');
});

test('guessToneLabel: formality wins over warmth, warmth wins over neutral default', () => {
  assert.equal(guessToneLabel({ ...NEUTRAL_TRAITS, formality: 80, warmth: 80 }), 'Formal');
  assert.equal(guessToneLabel({ ...NEUTRAL_TRAITS, warmth: 80 }), 'Friendly');
  assert.equal(guessToneLabel(NEUTRAL_TRAITS), 'Neutral');
});

test('outputColumnHeading: matches mockup 03\'s literal "NATURAL OUTPUT" pattern', () => {
  assert.equal(outputColumnHeading('Natural'), 'NATURAL OUTPUT');
  assert.equal(outputColumnHeading('Direct'), 'DIRECT OUTPUT');
  assert.equal(outputColumnHeading(null), 'OUTPUT');
});

// --- isBuiltinPersonaName / deriveNextPersonaCopyName -------------------------

test('isBuiltinPersonaName: matches against a Set or a plain array', () => {
  assert.equal(isBuiltinPersonaName('Formal', new Set(['Formal', 'Polished'])), true);
  assert.equal(isBuiltinPersonaName('Formal', ['Formal', 'Polished']), true);
  assert.equal(isBuiltinPersonaName('Custom', ['Formal', 'Polished']), false);
});

test('deriveNextPersonaCopyName: first free "(copy)"/"(copy N)" slot', () => {
  assert.equal(deriveNextPersonaCopyName('Natural', []), 'Natural (copy)');
  assert.equal(deriveNextPersonaCopyName('Natural', ['Natural (copy)']), 'Natural (copy 2)');
  assert.equal(deriveNextPersonaCopyName('Natural', ['Natural (copy)', 'Natural (copy 2)']), 'Natural (copy 3)');
});

// --- deriveVoiceBlendCards / normalizeStudioBlend (blend-weight normalization) ---

test('deriveVoiceBlendCards: base card is always first and marked selected, percents sum to ~100', () => {
  const cards = deriveVoiceBlendCards('Clarity Core', [
    { voiceId: 'warmth_air', weight: 0.3 },
    { voiceId: 'presence_boost', weight: 0.15 },
  ]);
  assert.equal(cards[0].label, 'Clarity Core');
  assert.equal(cards[0].selected, true);
  assert.equal(cards[1].selected, false);
  assert.equal(cards[2].selected, false);
  const total = cards.reduce((sum, c) => sum + c.pct, 0);
  assert.ok(total >= 99 && total <= 101, `expected ~100, got ${total}`);
});

test('deriveVoiceBlendCards: no extra layers -> a single 100% base card', () => {
  const cards = deriveVoiceBlendCards('Clarity Core', []);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].pct, 100);
  assert.equal(cards[0].selected, true);
});

test('normalizeStudioBlend: drops zero/negative/non-finite weights and clamps into [0,1] (delegates to voiceStudio.js, no local reimplementation)', () => {
  const normalized = normalizeStudioBlend([
    { voiceId: 'a', weight: 0.5 },
    { voiceId: 'b', weight: 0 },
    { voiceId: 'c', weight: -1 },
    { voiceId: 'd', weight: 1.5 },
  ]);
  assert.equal(normalized.a, 0.5);
  assert.equal(normalized.b, undefined);
  assert.equal(normalized.c, undefined);
  assert.equal(normalized.d, 1);
});

test('normalizeStudioBlend: an empty/no-layer input normalizes to null (matches voiceStudio.js contract)', () => {
  assert.equal(normalizeStudioBlend([]), null);
  assert.equal(normalizeStudioBlend(undefined), null);
});

// --- STRESS_TEST_SAMPLES -------------------------------------------------------

test('STRESS_TEST_SAMPLES: a small fixed, non-empty adversarial battery, each with a category + sample', () => {
  assert.ok(STRESS_TEST_SAMPLES.length > 0);
  for (const sample of STRESS_TEST_SAMPLES) {
    assert.ok(sample.category);
    assert.ok(sample.sample);
  }
});

// --- collectStudioElements ------------------------------------------------------

test('collectStudioElements: every STUDIO_ELEMENT_IDS key resolves to null against a doc with no matching ids (never throws)', () => {
  const fakeDoc = { getElementById: () => null };
  const els = collectStudioElements(fakeDoc);
  for (const key of Object.keys(STUDIO_ELEMENT_IDS)) {
    assert.equal(els[key], null);
  }
});

test('collectStudioElements: looks up each id from the given root', () => {
  const seen = [];
  const fakeDoc = { getElementById: (id) => { seen.push(id); return { id }; } };
  const els = collectStudioElements(fakeDoc);
  assert.equal(els.personaGrid.id, STUDIO_ELEMENT_IDS.personaGrid);
  assert.ok(seen.includes(STUDIO_ELEMENT_IDS.teachSection));
});

// --- createStudioWorkspaceFeature: light DOM-free smoke tests -----------------
// Full DOM wiring is exercised manually via signal-desk-preview.html (same
// convention as libraryWorkspace.js/talkWorkspace.js) -- these just confirm
// the feature can be constructed and driven with `elements: {}` (every
// access optional-chained) without throwing, and that setPersonas()/
// selectPersona() update the state getters correctly.

test('createStudioWorkspaceFeature: constructs and initializes safely with no elements/hooks at all', () => {
  const feature = createStudioWorkspaceFeature({});
  assert.doesNotThrow(() => feature.init());
});

test('createStudioWorkspaceFeature: setPersonas() seeds state and auto-selects the first persona', () => {
  const feature = createStudioWorkspaceFeature({ elements: {} });
  feature.setPersonas({ Natural: { prompt: 'p1' }, Direct: { prompt: 'p2' } });
  assert.equal(feature.getSelectedName(), 'Natural');
  assert.deepEqual(feature.getSelectedPersona(), { prompt: 'p1' });
});

test('createStudioWorkspaceFeature: selectPersona() switches selection; selecting an unknown name is a no-op', () => {
  const feature = createStudioWorkspaceFeature({ elements: {} });
  feature.setPersonas({ Natural: { prompt: 'p1' }, Direct: { prompt: 'p2' } });
  feature.selectPersona('Direct');
  assert.equal(feature.getSelectedName(), 'Direct');
  feature.selectPersona('Nonexistent');
  assert.equal(feature.getSelectedName(), 'Direct');
});

// --- Wave 12 collab task A: refresh() retry-once + keep-last-good ------------
//
// refresh() fetches Studio's OWN persona/builtin-name/voice lists directly
// (api/backend.js's fetchPersonas/fetchBuiltinPersonaNames/fetchTtsVoices),
// independently of bootstrap/signalDeskApp.js's loadPersonaList (which only
// guards the Settings dropdown, a separate surface). These exercise the same
// house standard applied to Studio's own fetch: retry once, never let a
// failure or an empty/malformed payload blank a working grid.

const TIMEOUT_FAILURE = { ok: false, status: 0, error: 'timeout' };

function mountStudio({ routes = {}, elements = {}, document: docParam } = {}) {
  const bridge = makeBackendBridge({
    'GET /personas': { Natural: { prompt: 'p1' } },
    'GET /personas-builtins': { builtins: ['Natural'] },
    'GET /tts/voices': { defaults: [{ id: 'af_bella', name: 'Bella' }], cloned: [] },
    ...routes,
  });
  const restore = installDomGlobals({ document: docParam, betterFingers: { backendRequest: bridge.request } });
  const toasts = [];
  const feature = createStudioWorkspaceFeature({
    elements,
    hooks: { showToast: (msg, tone) => toasts.push({ msg, tone }) },
  });
  return { feature, bridge, toasts, restore };
}

test('refresh() retries once before giving up on a slow/failed first response', async () => {
  let attempts = 0;
  const ctx = mountStudio({
    routes: {
      'GET /personas': () => {
        attempts += 1;
        return attempts === 1 ? TIMEOUT_FAILURE : { Natural: { prompt: 'p1' } };
      },
    },
  });
  try {
    await ctx.feature.refresh();
    assert.equal(attempts, 2, 'a slow first response must be retried once, not treated as a dead endpoint');
    assert.equal(ctx.feature.getSelectedName(), 'Natural');
  } finally {
    ctx.restore();
  }
});

test('a refresh that fails AFTER personas were already loaded keeps them on screen', async () => {
  let call = 0;
  const ctx = mountStudio({
    routes: {
      'GET /personas': () => {
        call += 1;
        return call <= 1 ? { Natural: { prompt: 'p1' } } : TIMEOUT_FAILURE;
      },
    },
  });
  try {
    await ctx.feature.refresh();
    assert.equal(ctx.feature.getSelectedName(), 'Natural', 'sanity: the first refresh succeeded');

    await ctx.feature.refresh();
    assert.equal(
      ctx.feature.getSelectedName(), 'Natural',
      'a later failed refresh must not blank a persona grid that was already populated',
    );
    assert.ok(
      ctx.toasts.some((t) => /Could not refresh Studio personas/.test(t.msg)),
      'a total failure must be reported honestly, not silently swallowed',
    );
  } finally {
    ctx.restore();
  }
});

test('refresh() treats an empty {} personas payload as a failure, not as "no personas configured"', async () => {
  const ctx = mountStudio({ routes: { 'GET /personas': {} } });
  try {
    await ctx.feature.refresh();
    assert.equal(ctx.feature.getSelectedName(), null);
    assert.ok(ctx.toasts.some((t) => /Could not refresh Studio personas/.test(t.msg)));
  } finally {
    ctx.restore();
  }
});

test('refresh() keeps the previously-loaded voice roster when a later voices fetch fails', async () => {
  let call = 0;
  const ctx = mountStudio({
    routes: {
      'GET /tts/voices': () => {
        call += 1;
        return call <= 1 ? { defaults: [{ id: 'af_bella', name: 'Bella' }], cloned: [] } : TIMEOUT_FAILURE;
      },
    },
  });
  try {
    await ctx.feature.refresh();
    await ctx.feature.refresh();
    assert.ok(
      ctx.toasts.some((t) => /Could not refresh Studio voices/.test(t.msg)),
      'the voices failure must be reported too',
    );
  } finally {
    ctx.restore();
  }
});

test('a cold-start refresh failure renders an honest error in the grid, not "No personas yet"', async () => {
  const doc = makeDocument(['personaGrid']);
  const ctx = mountStudio({
    routes: { 'GET /personas': TIMEOUT_FAILURE },
    elements: { personaGrid: doc.getElementById('personaGrid') },
    document: doc,
  });
  try {
    await ctx.feature.refresh();
    const text = doc.getElementById('personaGrid').textContent;
    assert.match(text, /Could not load your personas/);
    assert.doesNotMatch(text, /No personas yet/);
  } finally {
    ctx.restore();
  }
});

test('a genuinely empty (real) persona set still renders the honest empty-state copy', async () => {
  const doc = makeDocument(['personaGrid']);
  const ctx = mountStudio({
    // setPersonas() (not refresh()) is the test/preview-only direct seed path
    // -- confirms it is unaffected by the new failure-tracking flag.
    elements: { personaGrid: doc.getElementById('personaGrid') },
    document: doc,
  });
  try {
    ctx.feature.setPersonas({});
    const text = doc.getElementById('personaGrid').textContent;
    assert.match(text, /No personas yet/);
  } finally {
    ctx.restore();
  }
});

// --- Wave 12A: the blend roster is named on screen (product-owner finding 3) --
//
// "The user cannot SEE [...] what voices exist to blend." The "+ Add Voice"
// button picks the first unused voice out of voiceOptionsCache and adds it;
// until this wave nothing on the page listed that roster, so it was
// discoverable only by clicking until the button ran out of voices.
//
// `blendCards` is deliberately left off the stub element set below:
// buildBlendCard() reaches for the global `document`, which does not exist
// under node --test, and the roster line is rendered by the same pass without
// needing it. Same DOM-free convention as the smoke tests above.

function stubTextElement() {
  return { textContent: '', disabled: false };
}

const THREE_VOICES = [
  { id: 'af_bella', name: 'Bella' },
  { id: 'af_nicole', name: 'Nicole' },
  { id: 'am_michael', name: 'Michael' },
];

test('the blend strip names the voices still available to blend', () => {
  const blendAvailable = stubTextElement();
  const feature = createStudioWorkspaceFeature({ elements: { blendAvailable } });
  feature.setPersonas(
    { Natural: { prompt: 'p1' } },
    { voices: THREE_VOICES, blend: { base: { voiceId: 'af_bella', label: 'Bella' }, layers: [] } },
  );

  assert.match(blendAvailable.textContent, /^Available to blend: /);
  assert.match(blendAvailable.textContent, /Nicole/);
  assert.match(blendAvailable.textContent, /Michael/);
  assert.doesNotMatch(
    blendAvailable.textContent,
    /Bella/,
    'the base voice is already in the mix, so offering it as "available to blend" would be a lie',
  );
});

test('the blend strip says so plainly when every voice is already in the mix', () => {
  const blendAvailable = stubTextElement();
  const feature = createStudioWorkspaceFeature({ elements: { blendAvailable } });
  feature.setPersonas(
    { Natural: { prompt: 'p1' } },
    {
      // Two voices, both used -- exhausted roster, but still under the layer cap,
      // so this is the "nothing left to offer" case and not the "blend is full"
      // one. The two failure modes read identically to a user staring at a
      // disabled button, which is why each gets its own sentence.
      voices: THREE_VOICES.slice(0, 2),
      blend: {
        base: { voiceId: 'af_bella', label: 'Bella' },
        layers: [{ voiceId: 'af_nicole', weight: 0.3 }],
      },
    },
  );

  assert.equal(blendAvailable.textContent, 'Every available voice is already in this blend.');
});

test('the blend strip distinguishes a full blend from an exhausted roster', () => {
  const blendAvailable = stubTextElement();
  const feature = createStudioWorkspaceFeature({ elements: { blendAvailable } });
  feature.setPersonas(
    { Natural: { prompt: 'p1' } },
    {
      // Four voices, only two of them used -- but the blend is at
      // MAX_BLEND_LAYERS, so the reason "+ Add Voice" is disabled is the cap,
      // not the roster. Saying "every voice is already in this blend" here
      // would be false and would send the user looking for more voices.
      voices: [...THREE_VOICES, { id: 'bf_emma', name: 'Emma' }],
      blend: {
        base: { voiceId: 'af_bella', label: 'Bella' },
        layers: [{ voiceId: 'af_nicole', weight: 0.3 }, { voiceId: 'am_michael', weight: 0.3 }],
      },
    },
  );

  assert.match(blendAvailable.textContent, /^Blend is full at 2 layers/);
  assert.doesNotMatch(blendAvailable.textContent, /Emma/, 'Emma is available; the cap is what blocks adding her');
});

test('the blend strip does not claim voices are available before any have loaded', () => {
  const blendAvailable = stubTextElement();
  const feature = createStudioWorkspaceFeature({ elements: { blendAvailable } });
  feature.setPersonas({ Natural: { prompt: 'p1' } }, { voices: [] });

  assert.match(blendAvailable.textContent, /nothing to blend/);
});

// --- persona entry points: injected hook beats the cross-document fallback ----
//
// Both handlers can either call an injected hook or reach across the document
// for the shipping dashboard's own trigger. handleOpenFoundryClick had those in
// the opposite order to handleNewPersonaClick, which broke the moment Signal
// Desk mounted the Foundry: the trigger existed, so the guess won over the
// host's explicit decision, clicked it directly, and started an interview
// inside a dialog nothing had opened -- leaving the dialog hidden and the
// interview's error message off screen.

function stubButton() {
  const listeners = [];
  return {
    clicked: 0,
    addEventListener: (_evt, fn) => listeners.push(fn),
    click() { this.clicked += 1; listeners.forEach((fn) => fn()); },
  };
}

/**
 * A DOM node stub good enough for the render path.
 *
 * renderAll() builds persona cards with createElement/append, so any test that
 * selects a persona needs createElement to return something. Deliberately
 * minimal: it records what it was given rather than emulating a browser, so a
 * test that starts depending on real layout fails loudly instead of passing on
 * a half-truth.
 */
function stubElement() {
  const el = {
    children: [],
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    textContent: '',
    innerHTML: '',
    hidden: false,
    setAttribute() {},
    addEventListener() {},
    append(...kids) { el.children.push(...kids); },
    appendChild(kid) { el.children.push(kid); return kid; },
    replaceChildren(...kids) { el.children = kids; },
  };
  return el;
}

function withFakeDocument(trigger, fn) {
  const had = 'document' in globalThis;
  const previous = globalThis.document;
  globalThis.document = { getElementById: () => trigger, createElement: () => stubElement() };
  try {
    fn();
  } finally {
    if (had) globalThis.document = previous;
    else delete globalThis.document;
  }
}

test('Build with AI prefers the injected hook over #openFoundryButton', () => {
  const openFoundryButton = stubButton();
  const fallbackTrigger = stubButton();
  const calls = [];
  const toasts = [];

  withFakeDocument(fallbackTrigger, () => {
    const feature = createStudioWorkspaceFeature({
      elements: { openFoundryButton },
      hooks: {
        onOpenFoundryRequested: () => calls.push('hook'),
        showToast: (m) => toasts.push(m),
      },
    });
    feature.init();
    openFoundryButton.click();
  });

  assert.deepEqual(calls, ['hook']);
  assert.equal(fallbackTrigger.clicked, 0, 'the DOM fallback must not also fire');
  assert.deepEqual(toasts, []);
});

test('New Persona prefers the injected hook too', () => {
  const newPersonaButton = stubButton();
  const calls = [];

  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({
      elements: { newPersonaButton },
      hooks: { onNewPersonaRequested: () => calls.push('hook'), showToast: () => {} },
    });
    feature.init();
    newPersonaButton.click();
  });

  assert.deepEqual(calls, ['hook']);
});

// Wave 5 replaced the assertion this test used to make. It required that with
// no hook, Build with AI reach across the AMBIENT document for
// #openFoundryButton and click it. That reach is the bug: `document` here is
// whichever page the renderer has loaded, not the document this workspace was
// mounted into, so the fallback could drive a dialog in another document -- and
// did, starting an interview inside a dialog nothing had opened. The release
// rule is no cross-document element lookup, so the fallback is gone and its
// absence is now the thing under test.
test('with no hook, Build with AI reaches for no element in any document', () => {
  const openFoundryButton = stubButton();
  const strayTrigger = stubButton();
  const toasts = [];

  withFakeDocument(strayTrigger, () => {
    const feature = createStudioWorkspaceFeature({
      elements: { openFoundryButton },
      hooks: { showToast: (msg, tone) => toasts.push({ msg, tone }) },
    });
    feature.init();
    openFoundryButton.click();
  });

  assert.equal(strayTrigger.clicked, 0, 'an element in another document must never be clicked');
  assert.equal(toasts.length, 1, 'the user is told nothing happened rather than left guessing');
  assert.match(toasts[0].msg, /isn’t wired into this page/);
});

test('with no hook, New Persona reaches for no element in any document', () => {
  const newPersonaButton = stubButton();
  const strayTrigger = stubButton();
  const toasts = [];

  withFakeDocument(strayTrigger, () => {
    const feature = createStudioWorkspaceFeature({
      elements: { newPersonaButton },
      hooks: { showToast: (msg, tone) => toasts.push({ msg, tone }) },
    });
    feature.init();
    newPersonaButton.click();
  });

  assert.equal(strayTrigger.clicked, 0);
  assert.equal(toasts.length, 1);
});

test('Edit routes through the hook with the selected persona, and never types into another document', () => {
  const editButton = stubButton();
  const strayInput = stubButton();
  const edits = [];

  withFakeDocument(strayInput, () => {
    const feature = createStudioWorkspaceFeature({
      elements: { editButton },
      hooks: {
        onEditPersonaRequested: (name) => edits.push(name),
        showToast: () => {},
      },
    });
    feature.init();
    feature.setPersonas({ Formal: { prompt: 'p' } });
    feature.selectPersona('Formal');
    editButton.click();
  });

  assert.deepEqual(edits, ['Formal'], 'Edit hands the selected persona to the one shell');
  assert.equal(strayInput.clicked, 0);
});

test('Edit with nothing selected does nothing at all', () => {
  const editButton = stubButton();
  const edits = [];
  const toasts = [];

  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({
      elements: { editButton },
      hooks: {
        onEditPersonaRequested: (name) => edits.push(name),
        showToast: (msg) => toasts.push(msg),
      },
    });
    feature.init();
    editButton.click();
  });

  assert.deepEqual(edits, []);
  assert.deepEqual(toasts, [], 'nothing selected is not an error worth a toast');
});

// --- preferred contact (Stage 11) --------------------------------------------
//
// Replaces "Preferred Destinations", which read persona.preferred_destinations
// -- a field no persona has ever carried -- and rendered it as Discord/Gmail/
// Slack icons. The relationship is real in the other direction: contacts carry
// preferred_persona.

const CONTACTS = [
  { id: 'a', name: 'Zoe', preferred_persona: 'Natural' },
  { id: 'b', name: 'Priya', preferred_persona: 'Formal' },
  { id: 'c', name: 'Sam', preferred_persona: 'Natural' },
  { id: 'd', name: 'Nobody', preferred_persona: null },
];

test('contactsPreferring reads the relationship from the end that stores it', () => {
  assert.deepEqual(contactsPreferring('Natural', CONTACTS).map((c) => c.name), ['Sam', 'Zoe']);
});

test('contactsPreferring sorts by name so chips do not reshuffle between renders', () => {
  const shuffled = [CONTACTS[2], CONTACTS[0]];
  assert.deepEqual(contactsPreferring('Natural', shuffled).map((c) => c.name), ['Sam', 'Zoe']);
});

test('a persona nobody prefers gets an empty list, not a fabricated one', () => {
  assert.deepEqual(contactsPreferring('Playful', CONTACTS), []);
  assert.deepEqual(contactsPreferring('', CONTACTS), []);
  assert.deepEqual(contactsPreferring('Natural', null), []);
});

test('contactsPreferring ignores contacts with no name', () => {
  assert.deepEqual(contactsPreferring('Natural', [{ id: 'x', preferred_persona: 'Natural' }]), []);
});

// --- trait bands (Stage 10) ---------------------------------------------------
//
// A slider offers 101 values and a model acts on about five. The band label is
// what makes that visible instead of implying a precision the prompt lacks.

test('traitBandLabel mirrors the backend band boundaries', () => {
  assert.equal(traitBandLabel(0), 'Very low');
  assert.equal(traitBandLabel(19), 'Very low');
  assert.equal(traitBandLabel(20), 'Low');
  assert.equal(traitBandLabel(39), 'Low');
  assert.equal(traitBandLabel(40), 'Neutral');
  assert.equal(traitBandLabel(59), 'Neutral');
  assert.equal(traitBandLabel(60), 'High');
  assert.equal(traitBandLabel(79), 'High');
  assert.equal(traitBandLabel(80), 'Very high');
  assert.equal(traitBandLabel(100), 'Very high');
});

test('values inside one band read identically', () => {
  // 63 and 67 compose to the same prompt, so they must read the same too.
  assert.equal(traitBandLabel(63), traitBandLabel(67));
  assert.equal(traitBandLabel(44), traitBandLabel(56));
});

test('an unset axis has no band label rather than a default one', () => {
  // Unknown is reported as unknown -- the rule that replaced the archetype
  // fabrication.
  assert.equal(traitBandLabel(null), '');
  assert.equal(traitBandLabel(undefined), '');
  assert.equal(traitBandLabel('nonsense'), '');
  // Number('') is 0, not NaN -- an empty value must not read "Very low".
  assert.equal(traitBandLabel(''), '');
});

test('derivePersonaTraits still reports unknown for a persona with no traits', () => {
  const traits = derivePersonaTraits({ prompt: 'x' });
  assert.equal(traitsAreUnknown(traits), true);
});

test('derivePersonaTraits reads a real traits field', () => {
  const traits = derivePersonaTraits({ traits: { warmth: 90, directness: 10 } });
  assert.equal(traits.warmth, 90);
  assert.equal(traits.directness, 10);
  assert.equal(traits.formality, null, 'an axis the persona omits stays unknown');
});

// --- Wave 5: the "Active" badge is a fact about the profile ------------------
//
// It used to be a fact about the cursor. With no getActivePersonaName hook the
// badge defaulted to "active", so clicking through a grid of five personas lit
// "Active" on each in turn while only one of them was the profile's
// current_preset. A badge that is correct only when the host remembered to wire
// it is a badge that lies by default.

test('with no getActivePersonaName hook, no persona is claimed to be active', () => {
  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({ elements: {}, hooks: {} });
    feature.init();
    assert.equal(feature.isActivePersona('Formal'), false);
    assert.equal(feature.isActivePersona(''), false);
  });
});

test('the badge follows current_preset, not the selection', () => {
  withFakeDocument(stubButton(), () => {
    let currentPreset = 'True Janitor';
    const feature = createStudioWorkspaceFeature({
      elements: {},
      hooks: { getActivePersonaName: () => currentPreset },
    });
    feature.init();

    assert.equal(feature.isActivePersona('True Janitor'), true);
    assert.equal(feature.isActivePersona('Formal'), false,
      'selecting another persona must not move the Active badge to it');

    currentPreset = 'Formal';
    assert.equal(feature.isActivePersona('Formal'), true);
    assert.equal(feature.isActivePersona('True Janitor'), false);
  });
});

test('a stored current_preset with stray whitespace still matches its persona', () => {
  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({
      elements: {},
      hooks: { getActivePersonaName: () => '  Formal  ' },
    });
    feature.init();
    assert.equal(feature.isActivePersona('Formal'), true);
  });
});

test('the badge element is hidden for a persona that is not the active one', () => {
  const detailBadge = stubElement();
  const ctxBadge = stubElement();

  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({
      elements: { detailBadge, ctxBadge },
      hooks: { getActivePersonaName: () => 'True Janitor' },
    });
    feature.init();
    feature.setPersonas({ Formal: { prompt: 'p' }, 'True Janitor': { prompt: 'p' } });

    feature.selectPersona('Formal');
    assert.equal(detailBadge.hidden, true, 'Formal is selected but not active');
    assert.equal(ctxBadge.hidden, true);

    feature.selectPersona('True Janitor');
    assert.equal(detailBadge.hidden, false);
    assert.equal(ctxBadge.hidden, false);
  });
});

// --- Wave 5: fields with no backing schema are gone, not blank --------------

test('the element map no longer names tags or last-updated elements', () => {
  const ids = Object.values(STUDIO_ELEMENT_IDS);
  for (const gone of ['sdCtxTags', 'sdCtxAddTagButton', 'sdCtxLastUpdated']) {
    assert.equal(ids.includes(gone), false, `${gone} must not be looked up any more`);
  }
});

test('the feature exposes no add-tag action', () => {
  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({ elements: {}, hooks: {} });
    assert.equal('handleAddTagClick' in feature, false,
      'a button whose only behaviour is to apologise for itself is still a promise');
  });
});

test('the parity ledger records the cuts rather than losing the rows', () => {
  for (const key of ['detail.tags', 'detail.lastUpdated']) {
    const entry = STUDIO_PLACEMENT_MAP[key];
    assert.ok(entry, `${key} must stay in the ledger so the removal is reviewable`);
    assert.equal(entry.wired, false);
    assert.equal(entry.cut, true);
    assert.match(entry.note, /CUT in Wave 5/);
  }
});

test('rendering a persona that carries tags or an updated label emits neither', () => {
  // Defence against the fields creeping back via data rather than markup: even
  // if some persona payload grows a `tags` array, nothing here renders it.
  const ctxTags = stubElement();
  const ctxLastUpdated = stubElement();

  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({
      elements: { ctxTags, ctxLastUpdated },
      hooks: {},
    });
    feature.init();
    feature.setPersonas({ Formal: { prompt: 'p', tags: ['work', 'email'], updated_at_label: 'yesterday' } });
    feature.selectPersona('Formal');
  });

  assert.deepEqual(ctxTags.children, [], 'no tag chips are rendered');
  assert.equal(ctxLastUpdated.textContent, '', 'no last-updated value is rendered');
});

// --- Wave 5: persona traits are Experimental — unavailable (D-0006) ---------

test('the traits status is unavailable and names its decision', () => {
  assert.equal(PERSONA_TRAITS_STATUS.available, false);
  assert.equal(PERSONA_TRAITS_STATUS.profileKey, 'use_persona_traits');
  assert.equal(PERSONA_TRAITS_STATUS.decision, 'D-0006');
  assert.equal(PERSONA_TRAITS_STATUS.label, 'Persona traits: Experimental — unavailable');
});

test('the disclosure states the reason: preservation qualification has not passed', () => {
  const [label, reason, detail] = personaTraitsDisclosureLines();
  assert.match(label, /Experimental — unavailable/);
  assert.match(reason, /[Pp]reservation qualification has not passed/);
  assert.ok(detail.length > 0, 'the user is told why, not just that');
});

test('the disclosure never claims traits affect output', () => {
  const text = personaTraitsDisclosureLines().join(' ');
  assert.match(text, /not applied to cleanup/);
  assert.equal(/\bwill (?:be )?(?:apply|applied|affect)\b/.test(text), false);
});

test('the status object cannot be rewritten into saying traits are available', () => {
  assert.throws(() => { PERSONA_TRAITS_STATUS.available = true; },
    'a frozen status is what stops a later caller from flipping the disclosure');
  assert.equal(PERSONA_TRAITS_STATUS.available, false);
});

test('the traits status renders into its elements and offers no control', () => {
  const traitsStatusLabel = stubElement();
  const traitsStatusReason = stubElement();
  const traitsStatusDetail = stubElement();

  withFakeDocument(stubButton(), () => {
    const feature = createStudioWorkspaceFeature({
      elements: { traitsStatusLabel, traitsStatusReason, traitsStatusDetail },
      hooks: {},
    });
    feature.init();
  });

  assert.equal(traitsStatusLabel.textContent, 'Persona traits: Experimental — unavailable');
  assert.match(traitsStatusReason.textContent, /qualification has not passed/);
  assert.ok(traitsStatusDetail.textContent.length > 0);

  const ids = Object.values(STUDIO_ELEMENT_IDS).join(' ');
  assert.equal(/[Tt]raits(Toggle|Switch|Enable|Checkbox)/.test(ids), false,
    'D-0006 forbids an enabling switch');
});

test('the placement map marks traits unwired and cites D-0006', () => {
  const entry = STUDIO_PLACEMENT_MAP['personas.traits'];
  assert.equal(entry.wired, false, 'saved values do not reach the prompt');
  assert.match(entry.note, /D-0006/);
});
