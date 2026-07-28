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
} from '../src/renderer/features/studioWorkspace.js';

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

function withFakeDocument(trigger, fn) {
  const had = 'document' in globalThis;
  const previous = globalThis.document;
  globalThis.document = { getElementById: () => trigger };
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

test('with no hook, Build with AI still falls back to the dashboard trigger', () => {
  // The fallback is what keeps this adapter usable on index.html; removing it
  // would trade one broken page for another.
  const openFoundryButton = stubButton();
  const fallbackTrigger = stubButton();

  withFakeDocument(fallbackTrigger, () => {
    const feature = createStudioWorkspaceFeature({
      elements: { openFoundryButton },
      hooks: { showToast: () => {} },
    });
    feature.init();
    openFoundryButton.click();
  });

  assert.equal(fallbackTrigger.clicked, 1);
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
