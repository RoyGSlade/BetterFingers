// Parity gates for Talk / Library / Studio.
//
// utilitiesWorkspace.js's INVENTORY_PLACEMENT_MAP plus its completeness tests
// are the only machine-checked proof that the Signal Desk redesign lost no
// feature. Utilities and Settings had that gate; Talk, Library and Studio did
// not -- and those three are exactly where the gaps cluster, so the surfaces
// most at risk were the ones nothing was measuring.
//
// These tests apply the same four invariants to the three new maps. They are
// deliberately introduced BEFORE the work they gate, with most entries seeded
// `wired: false`: a gate added afterwards rubber-stamps whatever shipped, while
// a gate added first measures the gap and turns each later phase's diff into
// `wired: false -> true` plus the code that earns it.
//
// Note what is NOT asserted: that everything is wired. Asserting that today
// would just fail, and a permanently-red gate teaches people to ignore it --
// the same failure mode as the QA runner that could not report red. What IS
// asserted is that every gap is declared and explained.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { TALK_PLACEMENT_MAP, isValidTalkSection } from '../src/renderer/features/talkWorkspace.js';
import { LIBRARY_PLACEMENT_MAP, isValidLibrarySection } from '../src/renderer/features/libraryWorkspace.js';
import { STUDIO_PLACEMENT_MAP, isValidStudioSection } from '../src/renderer/features/studioWorkspace.js';

const GATES = [
  { name: 'Talk', map: TALK_PLACEMENT_MAP, isValidSection: isValidTalkSection },
  { name: 'Library', map: LIBRARY_PLACEMENT_MAP, isValidSection: isValidLibrarySection },
  { name: 'Studio', map: STUDIO_PLACEMENT_MAP, isValidSection: isValidStudioSection },
];

// Keys drawn from docs/ui/CURRENT_UI_INVENTORY.md that each workspace MUST
// account for. Adding a row here is how a reviewer says "this must not be
// quietly dropped"; the entry may be unwired, but it may not be absent.
const REQUIRED_KEYS = {
  Talk: [
    // §6.3 Review Draft Panel -- the surface Talk replaces.
    'refine.rawTranscript', 'refine.refinedText', 'refine.confidence', 'refine.tokenSummary',
    'refine.metadata', 'review.editor', 'review.saveEdit', 'review.rewriteShorter',
    'review.rewriteClearer', 'review.rewriteTone', 'review.rewriteCustom', 'review.readSelection',
    'review.listen', 'delivery.accept', 'delivery.decline', 'delivery.retry', 'delivery.copy',
    'delivery.sendInsert', 'delivery.sendResult', 'capture.toggleRecording', 'capture.emergencyStop',
  ],
  Library: [
    'search.fullText', 'search.clearHistory', 'timeline.cards', 'timeline.duration',
    'timeline.waveformThumb',
    'selected.detail', 'selected.reopen', 'selected.resend', 'selected.delete',
    'recovery.recordings', 'recovery.retranscribe',
  ],
  Studio: [
    // §3 Foundry, §7.5/§7.5.1 personas + wizard, §7.9 voice studio.
    'personas.list', 'personas.new', 'personas.foundry', 'personas.wizard', 'personas.traits',
    'detail.testPersona', 'detail.save', 'detail.delete',
    'voice.presets', 'voice.modulation', 'voice.ttsSpeed', 'voice.voiceHint', 'voice.cloning',
    'learning.teachFromEdit', 'learning.exampleList', 'learning.consent',
  ],
};

for (const { name, map, isValidSection } of GATES) {
  test(`COMPLETENESS (${name}): every required inventory key has an entry`, () => {
    const missing = REQUIRED_KEYS[name].filter((key) => !map[key]);
    assert.deepEqual(missing, [], `missing ${name} placement entries: ${missing.join(', ')}`);
  });

  test(`COMPLETENESS (${name}): every entry names a valid section`, () => {
    for (const [key, entry] of Object.entries(map)) {
      assert.ok(isValidSection(entry.section), `${key} has an invalid section "${entry.section}"`);
    }
  });

  test(`COMPLETENESS (${name}): every entry has a non-empty control description`, () => {
    for (const [key, entry] of Object.entries(map)) {
      assert.ok(
        typeof entry.control === 'string' && entry.control.length > 0,
        `${key} has no control description`,
      );
    }
  });

  test(`COMPLETENESS (${name}): every entry has a boolean wired flag, and any unwired entry explains itself`, () => {
    for (const [key, entry] of Object.entries(map)) {
      assert.equal(typeof entry.wired, 'boolean', `${key}.wired must be a boolean`);
      if (!entry.wired) {
        assert.ok(
          typeof entry.note === 'string' && entry.note.length > 0,
          `${key} is unwired but has no explanatory note -- an undeclared gap is how features get lost`,
        );
      }
    }
  });
}

test('the three maps do not silently disagree about a shared concept', () => {
  // Talk's picker, Library's filter and Studio's preferred contact are three
  // views of ONE backing field. While it did not exist they were three
  // fabrications called "Destination"; now that contacts are real (Stage 11)
  // they are three views of contact_id / preferred_persona. Either way they
  // must agree: one flipping without the others is a real feature landing
  // half-way, or a fabrication returning, and either should be a deliberate
  // edit rather than drift nobody noticed.
  //
  // This test caught exactly that during Stage 11 -- Library and Studio were
  // rewired to contacts while Talk's entry still said "Destination (REMOVED)".
  const contactEntries = [
    TALK_PLACEMENT_MAP['context.contact'],
    LIBRARY_PLACEMENT_MAP['search.contactFilter'],
    STUDIO_PLACEMENT_MAP['detail.preferredContacts'],
  ];
  for (const [i, entry] of contactEntries.entries()) {
    assert.ok(entry, `contact entry ${i} is missing from its placement map`);
  }
  const wired = contactEntries.map((e) => e.wired);
  assert.equal(
    new Set(wired).size,
    1,
    'the recipient concept is wired in one workspace but not another -- they share one backing field',
  );
});

test('nothing depending on the draft editor can be wired before the editor is', () => {
  // The Talk draft editor is the keystone: Library's "Reopen in Talk" needs
  // somewhere to reopen INTO, and Studio's teach-from-edit needs an edit diff
  // to learn from. The implication is one-directional -- an unwired editor
  // forces its dependents unwired, while a wired editor merely UNBLOCKS them
  // (they still need their own work). Asserting the dependents are wired here
  // would be the "done claim outrunning reality" this file exists to prevent.
  const editorWired = TALK_PLACEMENT_MAP['review.editor'].wired;
  if (!editorWired) {
    assert.equal(
      LIBRARY_PLACEMENT_MAP['selected.reopen'].wired,
      false,
      'Reopen claims to be wired while the editor it reopens into is not',
    );
    assert.equal(
      STUDIO_PLACEMENT_MAP['learning.teachFromEdit'].wired,
      false,
      'teach-from-edit claims to be wired while the editor producing the edit is not',
    );
  }
});

test('reports the current parity score for each workspace', () => {
  // Not an assertion so much as a visible number: a gate you cannot read is a
  // gate nobody watches.
  const lines = GATES.map(({ name, map }) => {
    const entries = Object.values(map);
    const wired = entries.filter((e) => e.wired).length;
    return `${name}: ${wired}/${entries.length} wired`;
  });
  console.log(`    parity — ${lines.join(' · ')}`);
  assert.ok(lines.length === 3);
});
