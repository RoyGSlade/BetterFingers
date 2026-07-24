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

test('derivePersonaTraits: known archetype names get their mockup-read preset, every trait key present and in range', () => {
  const traits = derivePersonaTraits({}, 'Natural');
  for (const key of TRAIT_KEYS) {
    assert.ok(key in traits);
    assert.ok(traits[key] >= 0 && traits[key] <= 100);
  }
  // Natural reads warmer/higher-confidence than Direct in the mockup.
  const direct = derivePersonaTraits({}, 'Direct');
  assert.ok(traits.warmth > direct.warmth);
  assert.ok(direct.directness > traits.directness);
});

test('derivePersonaTraits: an unrecognized persona name with no persona.traits override defaults to flat neutral (50 each)', () => {
  const traits = derivePersonaTraits({}, 'True Janitor');
  assert.deepEqual(traits, NEUTRAL_TRAITS);
});

test('derivePersonaTraits: an explicit persona.traits field overrides the preset/neutral default, per-key', () => {
  const traits = derivePersonaTraits({ traits: { warmth: 90 } }, 'True Janitor');
  assert.equal(traits.warmth, 90);
  // Untouched keys still fall back to neutral (the persona only overrode warmth).
  assert.equal(traits.directness, 50);
});

test('derivePersonaTraits: an explicit traits value is clamped the same as anything else', () => {
  const traits = derivePersonaTraits({ traits: { confidence: 500, formality: -20 } }, 'Natural');
  assert.equal(traits.confidence, 100);
  assert.equal(traits.formality, 0);
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
